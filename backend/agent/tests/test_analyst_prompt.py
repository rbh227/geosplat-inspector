"""U11 analyst flow (R16, AE3): an Understand-stage run answers a counting
question via capture-then-answer with ZERO edit or metrics calls — the CI
proxy for the agent-blur regression AE3 exists to prevent. (Live-model answer
quality is evaluated manually; this guards the structural behavior.)"""

from __future__ import annotations

import asyncio

from backend.agent.config import AgentConfig
from backend.agent.dispatch import ToolDispatcher
from backend.agent.loop import AgentLoop
from backend.agent.mocks import (
    MockBackendExecutor,
    MockFrontendChannel,
    MockProvider,
    text_then_tools,
    tool_turn,
)
from backend.agent.system_prompt import system_prompt_for
from backend.agent.types import DESTRUCTIVE_TOOLS


def _run_analyst(script) -> tuple:
    executor = MockBackendExecutor()
    channel = MockFrontendChannel()
    provider = MockProvider(script=script)
    loop = AgentLoop(
        provider,
        ToolDispatcher(executor, channel),
        channel,
        config=AgentConfig(enforce_grounding=False),
        stage="understand",
    )
    result = asyncio.run(loop.run("how many damaged buildings?"))
    return result, channel, executor


def test_count_question_is_answered_capture_first_with_no_edits():
    result, channel, executor = _run_analyst([
        text_then_tools(
            "Looking around from the operator's view.",
            ("move_camera", {"direction": "forward", "duration_ms": 400}),
            ("turn", {"direction": "left", "duration_ms": 300}),
            ("capture_frame", {}),
        ),
        tool_turn(("answer", {"text": "I count 3 damaged buildings: two collapsed roofs near the center and one leaning facade on the east side."})),
    ])
    assert result.status == "answered"
    assert "3 damaged buildings" in (result.answer or "")

    # capture happened through the frontend channel
    capture_cmds = [c for c in channel.commands if c.get("type") == "capture_request"]
    assert capture_cmds, "expected at least one capture"

    # zero mutating tool calls reached anything (AE3/AE2)
    tool_names = {e.get("name") for e in result.trace if e.get("type") == "tool_call"}
    assert tool_names & DESTRUCTIVE_TOOLS == set()
    assert "get_metrics" not in tool_names
    assert executor.edits == [] if hasattr(executor, "edits") else True


def test_analyst_prompt_teaches_pixels_over_metrics():
    prompt = system_prompt_for("understand")
    assert "ANSWER FROM PIXELS" in prompt
    # Skill names no longer render into the prompt (models called them as
    # tools); the analyst is taught to converse and match effort instead.
    assert "count_objects" not in prompt
    assert "CONVERSATION" in prompt
    assert "Gaussian counts" in prompt or "Gaussian statistics" in prompt
    # the editing vocabulary is absent from the analyst identity
    for name in ("delete_selection", "opacity_threshold", "crop_bbox"):
        assert name not in prompt


def test_hallucinated_metrics_call_is_rejected_in_understand():
    """get_metrics is not offered in Understand; a hallucinated call bounces."""
    result, channel, _ = _run_analyst([
        tool_turn(("get_metrics", {})),
        tool_turn(("capture_frame", {})),
        tool_turn(("answer", {"text": "The scene shows a damaged street."})),
    ])
    assert result.status == "answered"
    rejections = [
        e for e in result.trace
        if e.get("type") == "tool_result" and "not available in the understand stage" in str(e.get("result", {}))
    ]
    assert rejections
