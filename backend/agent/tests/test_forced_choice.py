"""ask_forced: one tiny context, one tool, safe-None on every failure mode."""
from __future__ import annotations

import asyncio
import time

from backend.agent.forced_choice import ask_forced
from backend.contracts import ModelResponse, ToolCall

SPEC = {
    "name": "judge_candidate",
    "description": "Judge the highlighted cluster.",
    "parameters": {"type": "object", "properties": {
        "verdict": {"type": "string", "enum": ["junk", "structure", "look_closer"]},
        "reason": {"type": "string"}}, "required": ["verdict", "reason"]},
}


class OneShotProvider:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def generate(self, messages, tools, images=None):
        self.calls.append({"messages": messages, "tools": tools, "images": images})
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _run(coro):
    return asyncio.run(coro)


def test_happy_path_returns_args_and_sends_one_tool():
    p = OneShotProvider([ModelResponse(text=None, tool_calls=[
        ToolCall("judge_candidate", {"verdict": "junk", "reason": "floating blob"})])])
    args = _run(ask_forced(p, "Is the highlighted cluster junk?", SPEC, image=b"png"))
    assert args == {"verdict": "junk", "reason": "floating blob"}
    call = p.calls[0]
    assert len(call["tools"]) == 1 and call["tools"][0].name == "judge_candidate"
    assert call["images"] == [b"png"]
    assert len(call["messages"]) == 1 and call["messages"][0]["role"] == "user"


def test_no_image_passes_none():
    p = OneShotProvider([ModelResponse(text=None, tool_calls=[
        ToolCall("judge_candidate", {"verdict": "structure", "reason": "wall"})])])
    args = _run(ask_forced(p, "q", SPEC))
    assert args["verdict"] == "structure"
    assert p.calls[0]["images"] is None


def test_wrong_tool_name_retries_then_none():
    bad = ModelResponse(text=None, tool_calls=[ToolCall("answer", {"text": "hi"})])
    p = OneShotProvider([bad, bad])
    assert _run(ask_forced(p, "q", SPEC, retries=1)) is None
    assert len(p.calls) == 2


def test_prose_only_retries_then_none():
    prose = ModelResponse(text="it looks fine", tool_calls=[])
    p = OneShotProvider([prose, prose])
    assert _run(ask_forced(p, "q", SPEC, retries=1)) is None


def test_exception_returns_none():
    p = OneShotProvider([RuntimeError("boom"), RuntimeError("boom")])
    assert _run(ask_forced(p, "q", SPEC, retries=1)) is None


def test_recovers_on_retry():
    good = ModelResponse(text=None, tool_calls=[
        ToolCall("judge_candidate", {"verdict": "junk", "reason": "x"})])
    p = OneShotProvider([RuntimeError("blip"), good])
    assert _run(ask_forced(p, "q", SPEC, retries=1)) == {"verdict": "junk", "reason": "x"}


def test_timeout_returns_none():
    class SlowProvider:
        def generate(self, messages, tools, images=None):
            time.sleep(0.5)
            return ModelResponse(text=None, tool_calls=[
                ToolCall("judge_candidate", {"verdict": "junk", "reason": "x"})])

    assert _run(ask_forced(SlowProvider(), "q", SPEC, timeout_s=0.05, retries=0)) is None
