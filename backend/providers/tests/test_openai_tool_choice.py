"""tool_choice="required" forces a tool call per turn — the structural fix for
weak models narrating plans ('Let me…') instead of acting. Servers that reject
the parameter get exactly one 400, then the provider falls back to auto for
its lifetime."""

import pytest

pytest.importorskip("openai")

from backend.contracts import ToolSpec
from backend.providers.openai import OpenAIProvider

TOOLS = [ToolSpec(name="capture_frame", description="capture", parameters={})]


class _FakeMessage:
    content = "ok"
    tool_calls: list = []


class _FakeChoice:
    message = _FakeMessage()


class _FakeRaw:
    choices = [_FakeChoice()]


class _FakeCompletions:
    def __init__(self, reject_required: bool = False, degenerate: int = 0):
        self.reject_required = reject_required
        self.degenerate = degenerate  # first N required-calls 400 with invalid JSON
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.reject_required and kwargs.get("tool_choice") == "required":
            raise ValueError("invalid parameter: tool_choice 'required' is not supported")
        if self.degenerate > 0 and kwargs.get("tool_choice") == "required":
            self.degenerate -= 1
            raise ValueError(
                "Error code: 400 - Invalid JSON: EOF while parsing a list at line 1 "
                "[type=json_invalid]"
            )
        return _FakeRaw()


class _FakeClient:
    def __init__(self, completions: _FakeCompletions):
        self.chat = type("Chat", (), {"completions": completions})()


def _provider(completions: _FakeCompletions) -> OpenAIProvider:
    p = OpenAIProvider(model="m", api_key="k")
    p._client = _FakeClient(completions)
    return p


def test_required_tool_choice_is_sent_when_tools_are_present():
    completions = _FakeCompletions()
    provider = _provider(completions)
    provider.generate([{"role": "user", "content": "hi"}], TOOLS)
    assert completions.calls[0].get("tool_choice") == "required"


def test_max_tokens_is_always_bounded():
    """No max_tokens → vLLM budgets the full remaining context and the request
    can't co-schedule at tight KV configs (measured: 150s hang vs 0.7s)."""
    completions = _FakeCompletions()
    provider = _provider(completions)
    provider.generate([{"role": "user", "content": "hi"}], TOOLS)
    provider.generate([{"role": "user", "content": "hi"}], [])
    assert all(0 < c.get("max_tokens", 0) <= 4096 for c in completions.calls)

    rejecting = _FakeCompletions(reject_required=True)
    provider = _provider(rejecting)
    provider.generate([{"role": "user", "content": "hi"}], TOOLS)
    assert all(0 < c.get("max_tokens", 0) <= 4096 for c in rejecting.calls)


def test_no_tool_choice_without_tools():
    completions = _FakeCompletions()
    provider = _provider(completions)
    provider.generate([{"role": "user", "content": "hi"}], [])
    assert "tool_choice" not in completions.calls[0]


def test_grammar_degeneration_retries_that_turn_unforced_but_keeps_required():
    """The observed live failure: forced into the tool grammar on a prose turn,
    the model emits whitespace to the cap and the server 400s invalid-JSON.
    That ONE turn retries unforced; the NEXT turn is forced again."""
    completions = _FakeCompletions(degenerate=1)
    provider = _provider(completions)
    provider.generate([{"role": "user", "content": "hi"}], TOOLS)
    assert completions.calls[0].get("tool_choice") == "required"
    assert "tool_choice" not in completions.calls[1]      # degenerate turn: auto
    assert completions.calls[1].get("max_tokens", 0) > 0  # still bounded
    provider.generate([{"role": "user", "content": "next"}], TOOLS)
    assert completions.calls[2].get("tool_choice") == "required"


def test_unsupported_server_falls_back_once_and_permanently():
    completions = _FakeCompletions(reject_required=True)
    provider = _provider(completions)
    provider.generate([{"role": "user", "content": "hi"}], TOOLS)
    # first attempt with required, immediate retry without it
    assert completions.calls[0].get("tool_choice") == "required"
    assert "tool_choice" not in completions.calls[1]
    # the capability is remembered: no further required attempts
    provider.generate([{"role": "user", "content": "again"}], TOOLS)
    assert "tool_choice" not in completions.calls[2]
    assert len(completions.calls) == 3
