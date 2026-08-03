"""capture_frame must be a perception barrier: tool calls queued after a
capture in the same model response would run blind (the frame reaches the
model only on the NEXT generate), so the loop drops them and says so. And
Stop/Pause must be honored BEFORE an action executes, not one action late."""

from __future__ import annotations

import asyncio

from backend.agent import AgentLoop, ToolDispatcher
from backend.agent.mocks import MockBackendExecutor, MockFrontendChannel, MockProvider, text_then_tools, tool_turn


def _run(coro):
    return asyncio.run(coro)


def test_calls_after_a_capture_in_the_same_batch_are_dropped():
    channel = MockFrontendChannel()
    provider = MockProvider([
        text_then_tools(
            "Capturing, then moving.",
            ("capture_frame", {}),
            ("move_camera", {"direction": "forward", "duration_ms": 400}),
            ("turn", {"direction": "left", "duration_ms": 300}),
        ),
        tool_turn(("answer", {"text": "done"})),
    ])
    # Clean stage: Understand no longer lets the model capture (v0.6
    # app-owned survey); the perception barrier still guards Clean captures.
    loop = AgentLoop(provider, ToolDispatcher(MockBackendExecutor(), channel), channel, stage="clean")
    _run(loop.run("survey"))

    types = [c.get("type") for c in channel.commands]
    assert types.count("capture_request") == 1
    assert "movement_input" not in types, "post-capture moves must not run blind"
    assert "rotation_input" not in types
    note = [m for m in loop._messages if "dropped 2 queued action(s)" in str(m.get("content", ""))]
    assert note, "the model must be told its queued actions were dropped"


def test_interrupt_is_honored_before_the_first_action():
    class InterruptedChannel(MockFrontendChannel):
        def __init__(self):
            super().__init__()
            self._flag = True

        @property
        def interrupted(self) -> bool:  # consume-once, like the real channel
            v = self._flag
            self._flag = False
            return v

    channel = InterruptedChannel()
    provider = MockProvider([
        tool_turn(("move_camera", {"direction": "forward", "duration_ms": 400})),
    ])
    loop = AgentLoop(provider, ToolDispatcher(MockBackendExecutor(), channel), channel, stage="understand")
    result = _run(loop.run("survey"))

    assert result.status == "interrupted"
    assert "movement_input" not in [c.get("type") for c in channel.commands], (
        "Stop must prevent the NEXT action, not fire one more"
    )
