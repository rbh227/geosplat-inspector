"""App-owned survey phase (spec 2026-08-03-app-owned-survey-analyst)."""
from __future__ import annotations

import asyncio
import base64

from backend.agent.dispatch import ToolDispatcher
from backend.agent.loop import AgentLoop
from backend.agent.mocks import MockBackendExecutor
from backend.contracts import ModelResponse, ToolCall

PNG = b"\x89PNG-fake"
PNG_B64 = base64.b64encode(PNG).decode()

LABELS = [
    "operator's view",
    "top-down",
    "oblique view from the north-east",
    "oblique view from the south-west",
]


class SurveyChannel:
    """FrontendChannel fake: answers survey_capture like ws.py would after
    frame decoding, and records every command."""

    def __init__(self, *, unchanged_at: int | None = None, fail: bool = False):
        self.commands: list[dict] = []
        self.events: list[dict] = []
        self.unchanged_at = unchanged_at
        self.fail = fail

    async def send_command(self, cmd: dict) -> dict:
        self.commands.append(cmd)
        if cmd.get("tool") == "survey_capture":
            if self.fail:
                return {"frames": [], "labels": [], "revision": None}
            args = cmd.get("args") or {}
            if self.unchanged_at is not None and args.get("if_revision_not") == self.unchanged_at:
                return {"unchanged": True, "revision": self.unchanged_at}
            return {
                "frames": [PNG, PNG, PNG, PNG],
                "labels": list(LABELS),
                "revision": 3,
            }
        return {"ok": True}

    async def emit_event(self, event: dict) -> None:
        self.events.append(event)


class RecordingProvider:
    """Answers immediately; records the images passed to every generate call."""

    def __init__(self):
        self.image_batches: list[list[bytes] | None] = []
        self.messages_seen: list[list[dict]] = []

    def generate(self, messages, tools, images=None):
        self.image_batches.append(list(images) if images else None)
        self.messages_seen.append([dict(m) for m in messages])
        return ModelResponse(
            text=None,
            tool_calls=[ToolCall("answer", {"text": "Aerial imagery of a settlement."})],
            raw=None,
        )


def make_loop(channel, provider):
    dispatcher = ToolDispatcher(MockBackendExecutor(), channel)
    return AgentLoop(provider, dispatcher, channel, stage="understand")


def test_survey_runs_before_first_model_call_and_attaches_frames():
    channel, provider = SurveyChannel(), RecordingProvider()
    loop = make_loop(channel, provider)
    result = asyncio.run(loop.run("what does this scene show?"))
    assert result.status == "answered"
    # survey was dispatched before any model call
    assert channel.commands[0]["tool"] == "survey_capture"
    # all four frames attached to the (single) model call
    assert provider.image_batches[0] == [PNG, PNG, PNG, PNG]
    # labels are described to the model in a user turn
    joined = " ".join(str(m.get("content")) for m in provider.messages_seen[0])
    assert "top-down" in joined and "operator's view" in joined
    # survey_out exposed for persistence
    assert loop.survey_out and loop.survey_out["revision"] == 3
    assert len(loop.survey_out["frames"]) == 4


def test_frames_attach_to_every_call_not_just_the_first():
    channel = SurveyChannel()

    class TwoTurnProvider(RecordingProvider):
        def generate(self, messages, tools, images=None):
            self.image_batches.append(list(images) if images else None)
            self.messages_seen.append([dict(m) for m in messages])
            if len(self.image_batches) == 1:
                return ModelResponse(
                    text=None,
                    tool_calls=[ToolCall("narrate", {"text": "Looking."})],
                    raw=None,
                )
            return ModelResponse(
                text=None,
                tool_calls=[ToolCall("answer", {"text": "A settlement."})],
                raw=None,
            )

    provider = TwoTurnProvider()
    loop = make_loop(channel, provider)
    result = asyncio.run(loop.run("how many buildings?"))
    assert result.status == "answered"
    assert len(provider.image_batches) == 2
    assert provider.image_batches[0] == [PNG, PNG, PNG, PNG]
    assert provider.image_batches[1] == [PNG, PNG, PNG, PNG]  # re-attached


def test_unchanged_revision_reuses_stored_frames_without_reflight():
    channel, provider = SurveyChannel(unchanged_at=3), RecordingProvider()
    loop = make_loop(channel, provider)
    stored = {"frames": [PNG], "labels": ["operator's view"], "revision": 3}
    result = asyncio.run(loop.run("and the roads?", survey=stored))
    assert result.status == "answered"
    assert channel.commands[0]["args"] == {"if_revision_not": 3}
    assert provider.image_batches[0] == [PNG]  # stored frame reused


def test_survey_failure_finishes_with_error_not_answer():
    channel, provider = SurveyChannel(fail=True), RecordingProvider()
    loop = make_loop(channel, provider)
    result = asyncio.run(loop.run("what does this scene show?"))
    assert result.status == "error"
    assert "survey" in (result.error or "").lower()
    assert provider.image_batches == []  # model never called


def test_survey_failure_falls_back_to_stored_frames():
    channel, provider = SurveyChannel(fail=True), RecordingProvider()
    loop = make_loop(channel, provider)
    stored = {"frames": [PNG, PNG], "labels": LABELS[:2], "revision": 2}
    result = asyncio.run(loop.run("what does this scene show?", survey=stored))
    assert result.status == "answered"
    assert provider.image_batches[0] == [PNG, PNG]


def test_understand_offers_only_answer_and_narrate():
    from backend.agent.system_prompt import stage_tools

    assert stage_tools("understand") == frozenset({"answer", "narrate"})


def test_model_navigation_call_is_rejected_at_backstop():
    channel = SurveyChannel()

    class NavProvider(RecordingProvider):
        def generate(self, messages, tools, images=None):
            self.image_batches.append(list(images) if images else None)
            self.messages_seen.append([dict(m) for m in messages])
            if len(self.image_batches) == 1:
                return ModelResponse(
                    text=None,
                    tool_calls=[ToolCall("move_camera", {"direction": "forward"})],
                    raw=None,
                )
            return ModelResponse(
                text=None,
                tool_calls=[ToolCall("answer", {"text": "A settlement."})],
                raw=None,
            )

    provider = NavProvider()
    loop = make_loop(channel, provider)
    result = asyncio.run(loop.run("what does this scene show?"))
    assert result.status == "answered"
    # the hallucinated navigation call never reached the frontend
    assert all(c.get("tool") != "move_camera" for c in channel.commands)
