"""A narrated intent with no tool call must NOT end the run — the agent used
to announce a plan ("I'll turn right for a better view") and just stop, because
free-form text was treated as an implicit answer. And conversation memory must
carry across runs (run(history=..., ledger=...) / transcript()) so follow-up
prompts aren't amnesiac."""

from __future__ import annotations

import asyncio

from backend.agent import AgentLoop, ToolDispatcher
from backend.agent.mocks import (
    MockBackendExecutor,
    MockFrontendChannel,
    MockProvider,
    tool_turn,
)
from backend.contracts import ModelResponse


def _run(coro):
    return asyncio.run(coro)


def _text_only(text: str) -> ModelResponse:
    return ModelResponse(text=text, tool_calls=[])


def _loop(provider, stage="understand"):
    channel = MockFrontendChannel()
    return AgentLoop(provider, ToolDispatcher(MockBackendExecutor(), channel), channel, stage=stage), channel


def test_narrated_intent_without_tool_call_does_not_end_the_run():
    provider = MockProvider([
        _text_only("I'll turn the camera to the right to get a better view."),
        tool_turn(("turn", {"direction": "right", "duration_ms": 300})),
        tool_turn(("capture_frame", {})),
        tool_turn(("answer", {"text": "done looking"})),
    ])
    # Clean stage: the Understand stage no longer offers navigation tools
    # (v0.6 app-owned survey), so the narrate-then-act contract lives in Clean.
    loop, channel = _loop(provider, stage="clean")
    result = _run(loop.run("survey the scene"))

    assert result.status == "answered"
    assert provider.calls == 4, "the run must continue past the text-only turn"
    assert "rotation_input" in [c.get("type") for c in channel.commands], (
        "after the nudge the model must get to actually execute the described turn"
    )


def test_second_consecutive_textonly_turn_is_the_answer():
    provider = MockProvider([
        tool_turn(("capture_frame", {})),
        _text_only("Looking around."),
        _text_only("The scene shows a sphere with some floaters."),
    ])
    loop, _ = _loop(provider)
    result = _run(loop.run("what do you see?"))

    assert result.status == "answered"
    assert "sphere" in (result.answer or "")


def test_plan_shaped_text_is_never_accepted_as_the_answer():
    provider = MockProvider([
        tool_turn(("capture_frame", {})),
        _text_only("The scene is noisy. Let me now focus on cleaning up the floaters:"),
        _text_only("I'll start by identifying problem regions."),
        tool_turn(("capture_frame", {})),
        tool_turn(("answer", {"text": "Captured the scene; it shows a sphere with floaters."})),
    ])
    loop, _ = _loop(provider)
    result = _run(loop.run("clean this up"))

    assert result.status == "answered"
    assert "floaters" in (result.answer or "")
    assert "Let me" not in (result.answer or ""), "a plan must not end the run"


def test_explicit_answer_that_is_a_plan_is_bounced():
    provider = MockProvider([
        tool_turn(("capture_frame", {})),
        tool_turn(("answer", {"text": "Let me now clean up the floaters:"})),
        tool_turn(("answer", {"text": "Done: the scene shows a sphere and scattered floaters."})),
    ])
    loop, _ = _loop(provider)
    result = _run(loop.run("survey"))

    assert result.status == "answered"
    assert result.answer.startswith("Done")


def test_a_model_that_only_plans_ends_stalled_not_with_a_fake_result():
    """The observed failure: the model wraps its running commentary in answer()
    ('Let me capture another frame to verify my position:'), and the run used
    to end showing that plan as the result. It must end as a VISIBLE stall."""
    provider = MockProvider([
        tool_turn(("answer", {"text": "Let me capture a frame to see the scene:"})),
        tool_turn(("answer", {"text": "I'll move closer to inspect the floaters."})),
        tool_turn(("answer", {"text": "Let me capture another frame to verify my position:"})),
        tool_turn(("answer", {"text": "Now I will examine the dense cluster:"})),
        tool_turn(("answer", {"text": "Let me try once more:"})),
    ])
    loop, channel = _loop(provider)
    result = _run(loop.run("clean up the splats"))

    assert result.status == "stalled"
    assert "without executing" in (result.error or "")
    complete = [e for e in channel.events if e.get("type") == "complete"][-1]
    assert complete["error"], "the stall must surface as a visible error, not an answer"


def test_repeated_identical_narration_is_a_stall_not_progress():
    """Observed live: a forced-tool-choice model loops narrate() with the same
    sentence instead of acting — 7x in a row burned the step budget. Repeats
    bounce (not shown to the operator again) and count toward the stall."""
    same = {"text": "I've identified the core and attempted to clean up floaters."}
    provider = MockProvider([tool_turn(("narrate", dict(same))) for _ in range(6)])
    loop, channel = _loop(provider, stage="clean")
    result = _run(loop.run("clean this up"))

    assert result.status == "stalled"
    narrated = [c for c in channel.commands if c.get("type") == "narrate"]
    assert len(narrated) == 1, "the repeat narrations must not reach the operator"


def test_varied_narration_with_real_work_is_fine():
    provider = MockProvider([
        tool_turn(("narrate", {"text": "Scanning the scene."})),
        tool_turn(("capture_frame", {})),
        tool_turn(("narrate", {"text": "Found floaters on the left."})),
        tool_turn(("capture_frame", {})),
        tool_turn(("answer", {"text": "Done: the scene shows a sphere with floaters."})),
    ])
    loop, _ = _loop(provider)
    result = _run(loop.run("survey"))
    assert result.status == "answered"


def test_plan_bounces_reset_when_the_model_actually_works():
    """plan -> real work -> plan -> ... never stalls: only CONSECUTIVE
    planning counts, so a chatty-but-working model finishes normally."""
    script = []
    for _ in range(3):
        script.append(tool_turn(("answer", {"text": "Let me look around first:"})))
        script.append(tool_turn(("capture_frame", {})))
    script.append(tool_turn(("answer", {"text": "Done: captured the scene from three angles."})))
    provider = MockProvider(script)
    loop, _ = _loop(provider)
    result = _run(loop.run("survey"))

    assert result.status == "answered"
    assert result.answer.startswith("Done")


def test_skill_name_called_as_tool_gets_the_recipe_back():
    provider = MockProvider([
        tool_turn(("survey_scene", {})),
        tool_turn(("capture_frame", {})),
        tool_turn(("answer", {"text": "done"})),
    ])
    # survey_scene is a Clean-stage routine since v0.6 (Understand is
    # survey-first and offers no navigation vocabulary to mistake for tools).
    loop, channel = _loop(provider, stage="clean")
    result = _run(loop.run("look around"))

    assert result.status == "answered"
    fed = [str(m.get("content", "")) for m in loop._messages]
    assert any("routine, not a tool" in c and "move_camera" in c for c in fed), (
        "the model must be handed the recipe steps, not a stage rejection"
    )


def test_history_and_ledger_carry_context_into_the_next_run():
    class RecordingProvider(MockProvider):
        def __init__(self, script):
            super().__init__(script)
            self.seen: list[list[dict]] = []

        def generate(self, messages, tools, images=None):
            self.seen.append([dict(m) for m in messages])
            return super().generate(messages, tools, images)

    first = RecordingProvider([
        tool_turn(("capture_frame", {})),
        tool_turn(("answer", {"text": "I saw two rooftops."})),
    ])
    loop1, _ = _loop(first)
    _run(loop1.run("survey the scene"))
    memory = loop1.transcript()
    assert any("two rooftops" in str(m.get("content", "")) for m in memory)
    assert not any(m.get("role") == "system" for m in memory)

    # Follow-up: no new capture — the carried ledger's evidence must back the
    # answer, and the carried history must reach the provider.
    second = RecordingProvider([
        tool_turn(("answer", {"text": "As I said: rooftops, seen from above."})),
    ])
    loop2, _ = _loop(second)
    result = _run(loop2.run("what did you find?", history=memory, ledger=loop1.ledger))

    assert result.status == "answered"
    sent = second.seen[0]
    assert any("survey the scene" in str(m.get("content", "")) for m in sent), (
        "the follow-up run must carry the prior conversation"
    )
