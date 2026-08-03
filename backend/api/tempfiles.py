"""Per-run temp dir for scene files, and a startup sweep of stale ones.

Uploads and cached exports go under `<tmp>/splatagent/run-<pid>-<token>/` —
one unique dir per process START, claimed with a marker file — so a later
boot can tell which dirs belong to a live backend and which are leftovers it
is safe to delete.

Ownership is generation-aware, not PID-based (Codex review, 2026-08-03):
in fixed-PID environments (the shipped Docker image runs uvicorn as PID 1 on
every container restart) a plain per-pid dir from a crashed run would be
mistaken for the live process's dir forever and the leak would never be
reclaimed. A dir whose marker claims OUR pid but whose run token differs is
provably from a dead generation — one pid names one live process, and that's
us — so it is safe to remove.

The sweep only ever deletes what it can prove it owns: the name must match
the run-dir pattern AND carry the marker file. Anything else under the
shared root — another app's namespace collision, a parked diagnostic dir, a
future layout — is left alone.
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
import tempfile

_APP_DIR = "splatagent"
_MARKER = ".splatagent-owner"
_RUN_DIR_RE = re.compile(r"^run-(\d+)-[0-9a-f]{8}$")

# This process's unique dir name, minted once per process start.
_run_dir_name: str | None = None


def _my_run_dir_name() -> str:
    global _run_dir_name
    if _run_dir_name is None:
        _run_dir_name = f"run-{os.getpid()}-{secrets.token_hex(4)}"
    return _run_dir_name


def scene_temp_dir() -> str:
    """This process's scene-file dir, created (and claimed) on first use."""
    path = os.path.join(tempfile.gettempdir(), _APP_DIR, _my_run_dir_name())
    os.makedirs(path, exist_ok=True)
    marker = os.path.join(path, _MARKER)
    if not os.path.exists(marker):
        with open(marker, "w", encoding="ascii") as f:
            f.write(f"{os.getpid()}\n")
    return path


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    return True


def sweep_stale(root: str | None = None) -> int:
    """Delete sibling run dirs whose owning process generation is gone.

    A candidate must look like ours (`run-<pid>-<token>`) AND carry the
    ownership marker; everything else is skipped, never deleted. A candidate
    is stale when its pid is dead, or when it claims OUR pid under a
    different token (fixed-PID restart: a previous generation of this very
    process). A live foreign pid is a concurrently running backend sharing
    the root — left alone. Returns the number of dirs removed.
    """
    app_root = os.path.join(root or tempfile.gettempdir(), _APP_DIR)
    if not os.path.isdir(app_root):
        return 0
    removed = 0
    for name in os.listdir(app_root):
        path = os.path.join(app_root, name)
        match = _RUN_DIR_RE.match(name)
        if match is None or not os.path.isdir(path):
            continue  # not provably ours — never touch it
        if name == _my_run_dir_name():
            continue  # our own live dir
        if not os.path.exists(os.path.join(path, _MARKER)):
            continue  # right shape but no ownership proof — leave it
        pid = int(match.group(1))
        if pid != os.getpid() and _pid_alive(pid):
            continue  # another live backend instance
        shutil.rmtree(path, ignore_errors=True)
        removed += 1
    return removed


__all__ = ["scene_temp_dir", "sweep_stale"]
