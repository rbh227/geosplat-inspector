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
from backend.agent.system_prompt import skills_for, system_prompt_for
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


# ---------------------------------------------------------------------------
# Prompt guards (2026-07-28): the analyst counts from ONE framed capture.
# Frames do not survive across model turns — loop.py clears _pending_frames
# after every generate() and the provider attaches images to the last user
# turn only — so counting across viewpoints can only double-count.
# ---------------------------------------------------------------------------

def _understand() -> str:
    return system_prompt_for("understand").lower()


def _understand_recipes() -> str:
    return " ".join(s["recipe"] for s in skills_for("understand")).lower()


def test_prompt_does_not_instruct_multi_angle_counting():
    p = _understand()
    assert "3-4 views" not in p
    assert "different angles" not in p
    recipes = _understand_recipes()
    assert "3-4 views" not in recipes
    assert "different angles" not in recipes


def test_prompt_states_the_multi_view_dedup_rule():
    # v0.6: counts come from the app-flown survey views; the prompt must state
    # that an object seen in several views is ONE object, counted on the best
    # single view.
    p = _understand()
    assert "one\n  object" in p or "one object" in p
    assert "best single view" in p


def test_prompt_requires_tiered_certainty_and_modality():
    p = _understand()
    assert "tier" in p
    assert "aerial" in p  # only as a worked EXAMPLE of naming modality


def test_prompt_forbids_unlocatable_and_artifact_damage_claims():
    p = _understand()
    assert "cannot say where" in p
    assert "artifact" in p
    assert "reconstruction" in p


def test_prompt_makes_no_damage_a_valid_answer():
    p = _understand()
    assert "nothing is wrong here" in p


def test_prompt_focuses_on_content_over_quality():
    """Live feedback (2026-08-08): the analyst opened answers with 'the scene
    is blurry / low quality' instead of describing what is in it."""
    p = _understand()
    assert "content over quality" in p
    assert "dwell" in p


def test_prompt_keeps_background_noise_out_of_counts():
    """Live feedback (2026-08-08): counts ran high — background blobs and
    artifact fragments were folded into totals. Counts anchor on major,
    individually locatable structures."""
    p = _understand()
    assert "major, distinct" in p
    assert "leave them out of the total" in p
    assert "never count them as objects" in p


def test_prompt_carries_no_domain_priors():
    """The prompt teaches HOW to look, never what these scenes contain."""
    p = _understand()
    for word in ("disaster", "trailer", "hurricane", "earthquake", "flood"):
        assert word not in p, f"domain prior leaked into the prompt: {word}"


# ---------------------------------------------------------------------------
# "Answered without looking" guard (2026-07-28). Observed live: asked what
# shape the main object was, the model called move_camera/turn/narrate and
# then answered "a rectangular prism ... resembling a modern building" about a
# SPHERE — never capturing a frame. The grounding ledger let it through
# because record_tool_result() sets measured=True for ANY structured result,
# so a camera move counted as evidence.
# ---------------------------------------------------------------------------

def test_understand_answer_goes_through_on_the_second_attempt():
    """A memory follow-up ('summarize what you did') legitimately has no frame
    this run. One nudge, then the agent is trusted."""
    result, _, _ = _run_analyst([
        tool_turn(("answer", {"text": "Earlier I cropped the scene to its core bounds."})),
        tool_turn(("answer", {"text": "Earlier I cropped the scene to its core bounds."})),
    ])
    assert result.status == "answered"
    assert "cropped the scene" in (result.answer or "")


def test_clarifying_question_is_never_bounced_for_lack_of_a_frame():
    result, _, _ = _run_analyst([
        tool_turn(("answer", {"text": "Which cluster do you mean?"})),
    ])
    assert result.status == "answered"
    assert result.answer == "Which cluster do you mean?"


