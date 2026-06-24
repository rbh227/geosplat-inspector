"""Serving acceptance: a 200MB+ .ply streams from disk without a memory blowup.

Runs the real ASGI app under uvicorn in a *subprocess* (so client-side
buffering can't pollute the measurement), registers a scene whose current .ply
is a >200MB file, then streams the GET while sampling the server process RSS.
A FileResponse streams in chunks, so the server's resident memory must stay far
below the file size.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import socket
import tempfile
import time

import httpx
import psutil
import pytest

TARGET_BYTES = 210 * 1024 * 1024  # > 200 MB


class _DummyScene:
    """Stand-in scene whose current .ply is a fixed on-disk file."""

    def __init__(self, path: str) -> None:
        self._path = path

    def metrics(self, region=None):
        return {"gaussianCount": 0}

    def count(self):
        return 0

    def export(self, path):  # not used (scene is never dirty)
        pass


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _run_server(big_path: str, port: int) -> None:  # child process entrypoint
    import uvicorn

    from backend.api.state import SceneState
    from backend.server import create_app

    app = create_app()
    app.state.store._scenes["big"] = SceneState("big", _DummyScene(big_path), big_path)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


@pytest.fixture
def big_ply():
    fd, path = tempfile.mkstemp(suffix=".ply", prefix="big_")
    os.close(fd)
    header = (
        b"ply\nformat binary_little_endian 1.0\nelement vertex 1\n"
        b"property float x\nend_header\n"
    )
    chunk = b"\0" * (8 * 1024 * 1024)
    with open(path, "wb") as f:
        f.write(header)
        written = len(header)
        while written < TARGET_BYTES:
            f.write(chunk)
            written += len(chunk)
    yield path
    os.remove(path)


def test_large_ply_streams_without_memory_blowup(big_ply):
    file_size = os.path.getsize(big_ply)
    assert file_size > 200 * 1024 * 1024

    port = _free_port()
    ctx = mp.get_context("spawn")
    proc = ctx.Process(target=_run_server, args=(big_ply, port), daemon=True)
    proc.start()
    try:
        base_url = f"http://127.0.0.1:{port}"
        # wait for the server to come up
        for _ in range(100):
            try:
                if httpx.get(f"{base_url}/health", timeout=1).status_code == 200:
                    break
            except Exception:
                time.sleep(0.2)
        else:
            raise RuntimeError("server did not start")

        ps = psutil.Process(proc.pid)
        baseline = ps.memory_info().rss
        peak = baseline
        total = 0
        with httpx.stream("GET", f"{base_url}/scene/big.ply", timeout=30) as r:
            assert r.status_code == 200
            for chunk in r.iter_bytes(chunk_size=1024 * 1024):
                total += len(chunk)
                if total % (32 * 1024 * 1024) < 1024 * 1024:
                    peak = max(peak, ps.memory_info().rss)
        peak = max(peak, ps.memory_info().rss)

        assert total == file_size, "must stream the entire file"
        growth = peak - baseline
        assert growth < 96 * 1024 * 1024, (
            f"server RSS grew {growth/1e6:.0f}MB serving a {file_size/1e6:.0f}MB "
            f"file — not streaming"
        )
    finally:
        proc.terminate()
        proc.join(timeout=10)
