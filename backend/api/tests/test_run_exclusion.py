"""One active agent run per scene (Codex adversarial review): a second
concurrent loop would race edits/undo against the same history and orphan a
parked no-timeout proposal. /agent/run returns 409 while a run is active and
accepts again once it finishes."""

from __future__ import annotations

import asyncio
import os

import httpx
import pytest

from backend import server as server_mod

EXAMPLES = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "examples",
)
MESSY = os.path.join(EXAMPLES, "messy.ply")


@pytest.fixture
def anyio_backend():
    return "asyncio"


class BlockingRunner:
    """run() parks on an event so the run stays 'active' until released."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def run(self, prompt, scene, channel, stage: str = "clean") -> None:
        self.started.set()
        await self.release.wait()


@pytest.mark.anyio
async def test_second_concurrent_run_is_rejected_with_409(monkeypatch):
    runner = BlockingRunner()
    monkeypatch.setattr(server_mod, "_select_runner", lambda: runner)
    app = server_mod.create_app()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with open(MESSY, "rb") as f:
            up = await client.post(
                "/scene", files={"file": ("messy.ply", f, "application/octet-stream")}
            )
        assert up.status_code == 200, up.text
        scene_id = up.json()["id"]
        body = {"scene_id": scene_id, "prompt": "clean", "stage": "clean"}

        r1 = await client.post("/agent/run", json=body)
        assert r1.status_code == 200, r1.text
        await asyncio.wait_for(runner.started.wait(), timeout=5)

        # a second run on the same scene while the first is active: refused
        r2 = await client.post("/agent/run", json=body)
        assert r2.status_code == 409
        assert "already active" in r2.json()["detail"]

        # once the first run finishes, the scene accepts a new run again
        runner.release.set()
        for _ in range(50):  # let the task + done-callback drain
            await asyncio.sleep(0.01)
            r3 = await client.post("/agent/run", json=body)
            if r3.status_code == 200:
                break
        assert r3.status_code == 200, r3.text
