"""Survey frames persist on the scene between Understand runs (spec
2026-08-03-app-owned-survey-analyst)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import backend.agent as agent_pkg
import backend.providers as providers_pkg
from backend.api import settings as settings_mod
from backend.api.real_engine import RealAgentRunner


class FakeLoop:
    """Stands in for AgentLoop: records the survey it was given and exposes a
    fresh survey_out like a successful Understand run would."""

    instances: list["FakeLoop"] = []

    def __init__(self, *args, **kwargs):
        self.survey_out = {"frames": [b"png"], "labels": ["operator's view"], "revision": 5}
        self.captured_survey: dict | None = None
        self.ledger = None
        FakeLoop.instances.append(self)

    async def run(self, prompt, history=None, ledger=None, survey=None):
        self.captured_survey = survey
        from backend.agent.types import LoopResult

        return LoopResult(status="answered", answer="ok")

    def transcript(self):
        return []


class Channel:
    async def send_command(self, cmd):
        return {}

    async def emit_event(self, event):
        pass


def _patch(monkeypatch):
    FakeLoop.instances = []
    monkeypatch.setattr(agent_pkg, "AgentLoop", FakeLoop)
    monkeypatch.setattr(providers_pkg, "get_provider", lambda *a, **k: object())
    cfg = SimpleNamespace(provider="openai", model="m", api_key="k", base_url=None)
    monkeypatch.setattr(
        settings_mod, "get_store", lambda: SimpleNamespace(resolve=lambda: cfg)
    )


class Scene:
    """Minimal RealScene stand-in: the runner only touches these attributes
    (plus `editing` via RealBackendExecutor's isinstance-style check)."""

    def __init__(self):
        self.editing = object()
        self.chat_history: list = []
        self.agent_ledger = None
        self.survey_store: dict | None = None


def test_survey_store_round_trips(monkeypatch):
    _patch(monkeypatch)
    scene = Scene()
    runner = RealAgentRunner()

    asyncio.run(runner.run("what does this show?", scene, Channel(), stage="understand"))
    assert scene.survey_store == {
        "frames": [b"png"],
        "labels": ["operator's view"],
        "revision": 5,
    }

    asyncio.run(runner.run("how many?", scene, Channel(), stage="understand"))
    assert FakeLoop.instances[1].captured_survey == scene.survey_store


def test_clean_runs_do_not_touch_the_survey_store(monkeypatch):
    _patch(monkeypatch)
    scene = Scene()
    runner = RealAgentRunner()

    asyncio.run(runner.run("clean this up", scene, Channel(), stage="clean"))
    assert scene.survey_store is None
    assert FakeLoop.instances[0].captured_survey is None
