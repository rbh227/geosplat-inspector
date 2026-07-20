"""Spatial grounding seed (real captures are NOT at the origin).

Before the model acts, the loop injects a `[scene]` message with the scene's
real center / bbox / radius so the model aims camera and selection tools at the
actual Gaussians instead of defaulting every coordinate to [0,0,0]. The bounds
come from a CHEAP min/max accessor (`get_bounds`) — NOT full `get_metrics` —
because the seed runs on every request, including look-only Understand, and must
never trigger the expensive k-NN metrics pass (Codex adversarial review, 0.1).
"""

from __future__ import annotations

import asyncio

from backend.agent.config import AgentConfig
from backend.agent.dispatch import ToolDispatcher
from backend.agent.loop import AgentLoop
from backend.agent.mocks import (
    MockBackendExecutor,
    MockFrontendChannel,
    MockProvider,
    tool_turn,
)


class _OffOriginExecutor(MockBackendExecutor):
    """A scene centered far from the origin, like a real capture."""

    def get_bounds(self) -> dict:
        return {"min": [1000.0, 2000.0, 3000.0], "max": [3000.0, 4000.0, 7000.0]}


class _NoBoundsExecutor(MockBackendExecutor):
    def get_bounds(self) -> dict:
        return {}  # no min/max available -> seed skips silently


class _MetricsSpyExecutor(MockBackendExecutor):
    """Counts calls into the expensive metrics implementation."""

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.metrics_calls = 0

    def get_metrics(self, region: dict | None = None) -> dict:
        self.metrics_calls += 1
        return super().get_metrics(region)


def _make_loop(executor, stage: str = "clean") -> tuple[AgentLoop, MockFrontendChannel]:
    channel = MockFrontendChannel()
    provider = MockProvider(script=[tool_turn(("answer", {"text": "done"}))])
    loop = AgentLoop(
        provider,
        ToolDispatcher(executor, channel),
        channel,
        config=AgentConfig(enforce_grounding=False),
        stage=stage,  # type: ignore[arg-type]
    )
    return loop, channel


def _scene_messages(loop: AgentLoop) -> list[dict]:
    return [
        m
        for m in loop._messages
        if isinstance(m.get("content"), str) and m["content"].startswith("[scene]")
    ]


def test_seed_injects_real_scene_center_between_system_and_user():
    loop, _ = _make_loop(_OffOriginExecutor())
    asyncio.run(loop.run("look around"))

    scene_msgs = _scene_messages(loop)
    assert len(scene_msgs) == 1
    body = scene_msgs[0]["content"]
    # center = midpoint of the off-origin bbox
    assert "[2000.0, 3000.0, 5000.0]" in body
    assert "not centered at the origin" in body.lower()

    # ordered: system, [scene], user prompt
    assert loop._messages[0]["role"] == "system"
    assert loop._messages[1] is scene_msgs[0]
    assert loop._messages[2]["content"] == "look around"


def test_seed_runs_for_understand_stage_too():
    loop, _ = _make_loop(_OffOriginExecutor(), stage="understand")
    result = asyncio.run(loop.run("what is here?"))
    assert result.status == "answered"
    assert len(_scene_messages(loop)) == 1


def test_seed_does_not_leak_a_tool_call_event():
    """The internal bounds probe must not register as a model tool call —
    Understand stays look-only and the grounding ledger is untouched."""
    loop, _ = _make_loop(_OffOriginExecutor(), stage="understand")
    result = asyncio.run(loop.run("what is here?"))
    tool_calls = {e.get("name") for e in result.trace if e.get("type") == "tool_call"}
    assert "get_metrics" not in tool_calls
    assert "get_bounds" not in tool_calls


def test_seed_never_calls_expensive_metrics():
    """Seeding an Understand run must use the cheap bounds path, never the
    full k-NN metrics implementation (Codex review no-ship)."""
    executor = _MetricsSpyExecutor()
    loop, _ = _make_loop(executor, stage="understand")
    asyncio.run(loop.run("what is here?"))
    assert executor.metrics_calls == 0


def test_seed_is_best_effort_when_bounds_missing():
    loop, _ = _make_loop(_NoBoundsExecutor())
    result = asyncio.run(loop.run("look around"))
    assert result.status == "answered"  # run still completes
    assert _scene_messages(loop) == []  # no grounding message, no crash
