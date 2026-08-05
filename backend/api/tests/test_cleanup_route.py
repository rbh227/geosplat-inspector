"""v0.7 cleanup routing: POST /agent/run carries `mode` through to the runner,
and RealAgentRunner sends mode='cleanup' (or a bare 'cleanup_scene' prompt)
to the CleanupController instead of the freeform AgentLoop."""

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


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.done = asyncio.Event()

    async def run(self, prompt, scene, channel, stage: str = "clean", mode=None) -> None:
        self.calls.append({"prompt": prompt, "stage": stage, "mode": mode})
        self.done.set()


class FakeRenderer:
    async def accept(self) -> None: ...
    async def send_json(self, message: dict) -> None: ...
    async def close(self) -> None: ...


@pytest.mark.anyio
async def test_mode_field_reaches_the_runner(monkeypatch):
    runner = RecordingRunner()
    monkeypatch.setattr(server_mod, "_select_runner", lambda: runner)
    app = server_mod.create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with open(MESSY, "rb") as f:
            up = await client.post(
                "/scene", files={"file": ("messy.ply", f, "application/octet-stream")}
            )
        scene_id = up.json()["id"]
        await app.state.manager.connect(scene_id, FakeRenderer())
        r = await client.post("/agent/run", json={
            "scene_id": scene_id, "prompt": "cleanup_scene",
            "stage": "clean", "mode": "cleanup",
        })
        assert r.status_code == 200, r.text
        await asyncio.wait_for(runner.done.wait(), timeout=5)
    assert runner.calls == [{"prompt": "cleanup_scene", "stage": "clean", "mode": "cleanup"}]


# ---------------------------------------------------------------------------
# RealAgentRunner routing (unit level — provider + controller patched out)
# ---------------------------------------------------------------------------
class _FakeController:
    built: list["_FakeController"] = []

    def __init__(self, provider, dispatcher, channel, executor, splat_arrays, config=None):
        self.ran_with: str | None = None
        _FakeController.built.append(self)

    async def run(self, prompt: str):
        self.ran_with = prompt


class _FakeLoop:
    built: list["_FakeLoop"] = []

    def __init__(self, *a, **k):
        _FakeLoop.built.append(self)
        self.ledger = None
        self.survey_out = None

    async def run(self, prompt, history=None, ledger=None, survey=None):
        return None

    def transcript(self):
        return []


@pytest.fixture
def patched_engine(monkeypatch):
    import backend.agent as agent_pkg
    import backend.agent.cleanup_controller as cc
    import backend.providers as providers

    _FakeController.built = []
    _FakeLoop.built = []
    monkeypatch.setattr(cc, "CleanupController", _FakeController)
    monkeypatch.setattr(agent_pkg, "AgentLoop", _FakeLoop)
    monkeypatch.setattr(providers, "get_provider", lambda *a, **k: object())

    class _Store:
        def resolve(self):
            class Cfg:
                provider = "openai"
                model = "m"
                api_key = "k"
                base_url = None
                preset = "p"
            return Cfg()

    import backend.api.settings as settings_mod
    monkeypatch.setattr(settings_mod, "get_store", lambda: _Store())


def _scene():
    from backend.api.real_engine import RealBackend
    return RealBackend().load(MESSY)


@pytest.mark.anyio
async def test_real_runner_mode_cleanup_builds_controller(patched_engine):
    from backend.agent.mocks import MockFrontendChannel
    from backend.api.real_engine import RealAgentRunner

    await RealAgentRunner().run("please tidy", _scene(), MockFrontendChannel(),
                                stage="clean", mode="cleanup")
    assert len(_FakeController.built) == 1
    assert _FakeController.built[0].ran_with == "please tidy"
    assert _FakeLoop.built == []


@pytest.mark.anyio
async def test_real_runner_bare_prompt_routes_without_mode(patched_engine):
    from backend.agent.mocks import MockFrontendChannel
    from backend.api.real_engine import RealAgentRunner

    await RealAgentRunner().run("  cleanup_scene  ", _scene(), MockFrontendChannel(),
                                stage="clean")
    assert len(_FakeController.built) == 1


@pytest.mark.anyio
async def test_real_runner_understand_stage_never_routes_to_controller(patched_engine):
    from backend.agent.mocks import MockFrontendChannel
    from backend.api.real_engine import RealAgentRunner

    await RealAgentRunner().run("cleanup_scene", _scene(), MockFrontendChannel(),
                                stage="understand", mode="cleanup")
    assert _FakeController.built == []
    assert len(_FakeLoop.built) == 1
