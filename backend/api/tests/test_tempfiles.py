"""Temp-file lifecycle: uploads/exports live in a per-process dir, scenes clean
up their files, dead processes' dirs are swept at startup, shutdown clears the
store. Guards the leak where every upload left an `upload_*.ply` in the system
temp dir forever."""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import tempfile

from fastapi.testclient import TestClient

from backend.api.state import SceneState, SceneStore
from backend.api.tempfiles import scene_temp_dir, sweep_stale
from backend.server import create_app

EXAMPLES = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "examples",
)
CLEAN = os.path.join(EXAMPLES, "clean.ply")


class _FakeScene:
    """Minimal engine `Scene`: count/export are all SceneState touches here."""

    def __init__(self, count: int = 10) -> None:
        self._count = count

    def count(self) -> int:
        return self._count

    def export(self, path: str) -> None:
        with open(path, "wb") as f:
            f.write(b"ply-bytes")


class _FakeBackend:
    def load(self, path: str) -> _FakeScene:
        return _FakeScene()


def _make_source(dir_: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".ply", prefix="upload_", dir=dir_)
    os.close(fd)
    return path


# ---- scene_temp_dir ------------------------------------------------------- #

def test_scene_temp_dir_is_per_run_and_claimed():
    path = scene_temp_dir()
    assert os.path.isdir(path)
    name = os.path.basename(path)
    # run-<pid>-<token>: unique per process START, so a fixed-PID restart
    # (Docker runs uvicorn as PID 1 every time) never collides with leftovers.
    assert re.fullmatch(rf"run-{os.getpid()}-[0-9a-f]{{8}}", name), name
    assert os.path.basename(os.path.dirname(path)) == "splatagent"
    assert os.path.exists(os.path.join(path, ".splatagent-owner"))
    assert scene_temp_dir() == path  # stable within one process


# ---- sweep_stale ---------------------------------------------------------- #

def _run_dir(root, pid: int, token: str = "deadbeef"):
    d = root / f"run-{pid}-{token}"
    d.mkdir()
    (d / ".splatagent-owner").write_text(f"{pid}\n")
    (d / "upload_x.ply").write_bytes(b"x")
    return d


def test_sweep_removes_dead_pid_dirs_keeps_live(tmp_path):
    root = tmp_path / "splatagent"
    root.mkdir()
    # a dir owned by a process that has definitely exited
    proc = subprocess.Popen(["true"])
    proc.wait()
    dead = _run_dir(root, proc.pid)
    # a dir owned by a DIFFERENT live process (our parent) must survive
    live = _run_dir(root, os.getppid())
    # this process's own dir must survive
    mine = root / os.path.basename(scene_temp_dir())
    mine.mkdir()
    (mine / ".splatagent-owner").write_text(f"{os.getpid()}\n")
    (mine / "upload_live.ply").write_bytes(b"x")

    removed = sweep_stale(str(tmp_path))

    assert removed == 1
    assert not dead.exists()
    assert live.exists()
    assert mine.exists()
    assert (mine / "upload_live.ply").exists()


def test_sweep_reclaims_previous_generation_after_pid_reuse(tmp_path):
    """Docker regression (Codex review): uvicorn is PID 1 on every container
    restart. A leftover dir claiming OUR pid but carrying a DIFFERENT run
    token is provably from a dead generation — one pid names one live
    process, and that's us — so it must be reclaimed, not preserved."""
    root = tmp_path / "splatagent"
    root.mkdir()
    previous_generation = _run_dir(root, os.getpid(), token="0ddba11c")
    mine = root / os.path.basename(scene_temp_dir())
    mine.mkdir(exist_ok=True)

    removed = sweep_stale(str(tmp_path))

    assert removed == 1
    assert not previous_generation.exists()
    assert mine.exists()


def test_sweep_never_touches_unrecognized_directories(tmp_path):
    """Overbroad-deletion regression (Codex review): the shared temp root can
    contain things that are not ours — other apps, parked diagnostics, a
    future layout. Only marker-carrying run dirs are ever deleted."""
    root = tmp_path / "splatagent"
    root.mkdir()
    foreign = root / "someones-notes"
    foreign.mkdir()
    (foreign / "keep.txt").write_bytes(b"x")
    legacy_numeric = root / "99999999"  # dead-pid-shaped but not our layout
    legacy_numeric.mkdir()
    proc = subprocess.Popen(["true"])
    proc.wait()
    unmarked = root / f"run-{proc.pid}-cafef00d"  # our shape, no marker
    unmarked.mkdir()

    removed = sweep_stale(str(tmp_path))

    assert removed == 0
    assert foreign.exists() and (foreign / "keep.txt").exists()
    assert legacy_numeric.exists()
    assert unmarked.exists()


def test_sweep_is_noop_without_app_dir(tmp_path):
    assert sweep_stale(str(tmp_path)) == 0


# ---- SceneState.cleanup --------------------------------------------------- #

def test_cleanup_removes_source_and_export(tmp_path):
    source = _make_source(str(tmp_path))
    scene = _FakeScene(count=10)
    state = SceneState("s1", scene, source)
    scene._count = 7  # simulate a destructive edit
    export = state.current_ply_path()
    assert os.path.exists(export) and export != source

    state.cleanup()

    assert not os.path.exists(source)
    assert not os.path.exists(export)


# ---- SceneStore.clear ----------------------------------------------------- #

def test_store_clear_cleans_all_scenes(tmp_path):
    async def run() -> tuple[str, str, SceneStore]:
        store = SceneStore(_FakeBackend())
        a = await store.create(_make_source(str(tmp_path)))
        b = await store.create(_make_source(str(tmp_path)))
        await store.clear()
        return a.source_path, b.source_path, store

    src_a, src_b, store = asyncio.run(run())
    assert len(store) == 0
    assert not os.path.exists(src_a)
    assert not os.path.exists(src_b)


# ---- end to end: upload lands in the process dir, shutdown removes it ----- #

def test_upload_spools_to_process_dir_and_shutdown_cleans():
    # Scoped to files THIS client creates: the dir is per-pid, so other tests'
    # apps in the same pytest process share it.
    before = set(os.listdir(scene_temp_dir()))
    with TestClient(create_app()) as client:
        with open(CLEAN, "rb") as f:
            resp = client.post(
                "/scene", files={"file": ("clean.ply", f, "application/octet-stream")}
            )
        assert resp.status_code == 200, resp.text
        created = set(os.listdir(scene_temp_dir())) - before
        assert any(p.startswith("upload_") for p in created), (
            "upload must be written inside the per-process dir"
        )
    # TestClient exit runs shutdown -> store.clear() -> files removed
    leftovers = set(os.listdir(scene_temp_dir())) & created
    assert leftovers == set(), f"shutdown left temp files behind: {leftovers}"
