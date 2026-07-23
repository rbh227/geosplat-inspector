"""`complete` must say whether the scene actually changed: the frontend gates
its reload-and-reframe on it, so a read-only survey must never yank the
operator's camera when the run ends."""

from __future__ import annotations

import asyncio

from backend.agent import AgentLoop, ToolDispatcher
from backend.agent.mocks import MockBackendExecutor, MockFrontendChannel, MockProvider, tool_turn


def _run(coro):
    return asyncio.run(coro)


def _complete(channel: MockFrontendChannel) -> dict:
    return [e for e in channel.events if e.get("type") == "complete"][-1]


def test_lookonly_run_completes_with_scene_changed_false():
    channel = MockFrontendChannel()
    provider = MockProvider([
        tool_turn(("capture_frame", {})),
        tool_turn(("answer", {"text": "Two rooftops visible."})),
    ])
    loop = AgentLoop(provider, ToolDispatcher(MockBackendExecutor(), channel), channel, stage="understand")
    _run(loop.run("what do you see?"))
    assert _complete(channel)["scene_changed"] is False


def test_undo_marks_scene_changed_true():
    channel = MockFrontendChannel()
    executor = MockBackendExecutor()
    executor.snapshot()  # give undo something to restore
    provider = MockProvider([
        tool_turn(("undo", {})),
        tool_turn(("answer", {"text": "reverted"})),
    ])
    loop = AgentLoop(provider, ToolDispatcher(executor, channel), channel, stage="clean")
    _run(loop.run("undo that"))
    assert _complete(channel)["scene_changed"] is True
