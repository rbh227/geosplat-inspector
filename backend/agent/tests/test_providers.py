"""Provider-layer tests: factory swap, backoff, and response normalization.

No vendor SDKs required — adapters import lazily and we test the pure parse +
retry logic. Run: `pytest backend/agent/tests/test_providers.py`.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from backend.providers import (
    AnthropicProvider,
    GeminiProvider,
    OpenAIProvider,
    RateLimitError,
    get_provider,
    with_retry,
)
from backend.providers import anthropic as anth_mod
from backend.providers import gemini as gem_mod
from backend.providers import openai as oai_mod


# ── factory / swap ──────────────────────────────────────────────────────
def test_factory_default_is_gemini(monkeypatch):
    monkeypatch.delenv("MODEL_PROVIDER", raising=False)
    assert isinstance(get_provider(), GeminiProvider)


def test_factory_env_swaps_provider(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "anthropic")
    assert isinstance(get_provider(), AnthropicProvider)
    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    assert isinstance(get_provider(), OpenAIProvider)


def test_factory_model_name_override(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "gemini")
    monkeypatch.setenv("MODEL_NAME", "gemini-2.5-flash-lite")
    assert get_provider().model == "gemini-2.5-flash-lite"


def test_factory_unknown_provider_raises(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "nope")
    with pytest.raises(Exception):
        get_provider()


# ── backoff (R4) ────────────────────────────────────────────────────────
def test_with_retry_succeeds_after_transient_429():
    slept: list[float] = []
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RateLimitError("429")
        return "ok"

    out = with_retry(flaky, max_attempts=5, base_delay=0.01, jitter=False, sleep=slept.append)
    assert out == "ok"
    assert calls["n"] == 3
    assert len(slept) == 2  # backed off twice before success


def test_with_retry_exhausts_then_surfaces_clear_message():
    slept: list[float] = []

    def always():
        raise RateLimitError("quota exceeded")

    with pytest.raises(RateLimitError) as ei:
        with_retry(always, max_attempts=4, base_delay=0.01, jitter=False, sleep=slept.append)
    assert "after 4 attempts" in str(ei.value)
    assert len(slept) == 3  # slept between each of the 4 attempts


# ── response normalization (no SDK) ─────────────────────────────────────
def test_gemini_parse_text_and_tool_call():
    fc = SimpleNamespace(name="get_metrics", args={"region": None})
    part_text = SimpleNamespace(text="thinking", function_call=None)
    part_fc = SimpleNamespace(text=None, function_call=fc)
    raw = SimpleNamespace(
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part_text, part_fc]))]
    )
    resp = gem_mod._parse_response(raw)
    assert resp.text == "thinking"
    assert resp.tool_calls[0].name == "get_metrics"
    assert resp.tool_calls[0].args == {"region": None}


def test_anthropic_parse_tool_use():
    raw = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text="hi"),
            SimpleNamespace(type="tool_use", name="remove_outliers", input={"k": 16, "std_ratio": 2.0}),
        ]
    )
    resp = anth_mod._parse_response(raw)
    assert resp.text == "hi"
    assert resp.tool_calls[0].name == "remove_outliers"
    assert resp.tool_calls[0].args["k"] == 16


def test_openai_parse_tool_call_json_args():
    fn = SimpleNamespace(name="opacity_threshold", arguments='{"min_alpha": 0.05}')
    msg = SimpleNamespace(content="ok", tool_calls=[SimpleNamespace(function=fn)])
    raw = SimpleNamespace(choices=[SimpleNamespace(message=msg)])
    resp = oai_mod._parse_response(raw)
    assert resp.text == "ok"
    assert resp.tool_calls[0].name == "opacity_threshold"
    assert resp.tool_calls[0].args == {"min_alpha": 0.05}


def test_openai_image_mime_sniffed_from_bytes():
    """Captures are JPEG now (live-found: 6 PNG frames in one WS message blew
    uvicorn's 16MB receive limit and closed the socket mid-run). The data URL
    mime must match the actual bytes, sniffed, not hardcoded."""
    p = OpenAIProvider(api_key="x")
    jpeg = b"\xff\xd8\xff\xe0" + b"0" * 8
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 8
    out = p._to_messages([{"role": "user", "content": "look"}], [jpeg, png])
    parts = out[-1]["content"]
    urls = [c["image_url"]["url"] for c in parts if c.get("type") == "image_url"]
    assert urls[0].startswith("data:image/jpeg;base64,")
    assert urls[1].startswith("data:image/png;base64,")


def test_providers_import_without_sdk_and_share_interface():
    # Constructing never touches the SDK (lazy); generate would, but we don't call it.
    for cls in (GeminiProvider, AnthropicProvider, OpenAIProvider):
        p = cls(api_key="x")
        assert hasattr(p, "generate")


# ── OpenAI-compatible local backend (vLLM / Ollama / ...) ────────────────
def _fake_openai_module(monkeypatch):
    """Inject a fake `openai` module so _get_client builds without the SDK.

    Returns a dict that captures the kwargs OpenAI(...) was constructed with.
    """
    captured: dict = {}

    class _FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    fake = SimpleNamespace(OpenAI=_FakeClient)
    monkeypatch.setitem(__import__("sys").modules, "openai", fake)
    return captured


def test_openai_base_url_allows_placeholder_key(monkeypatch):
    # The whole point of the local path: no real key, just a base_url.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    captured = _fake_openai_module(monkeypatch)
    p = OpenAIProvider(base_url="http://localhost:8000/v1", api_key=None)
    p._get_client()  # must NOT raise ProviderConfigError
    assert captured["base_url"] == "http://localhost:8000/v1"
    assert captured["api_key"] == "not-needed"


def test_openai_no_base_url_still_requires_key(monkeypatch):
    from backend.providers.errors import ProviderConfigError

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _fake_openai_module(monkeypatch)
    p = OpenAIProvider(api_key=None)  # real OpenAI: strict key requirement
    with pytest.raises(ProviderConfigError):
        p._get_client()


def test_openai_base_url_from_env(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("MODEL_NAME", "Qwen/Qwen2.5-VL-7B-Instruct")
    p = get_provider()
    assert isinstance(p, OpenAIProvider)
    assert p.base_url == "http://localhost:8000/v1"
    assert p.model == "Qwen/Qwen2.5-VL-7B-Instruct"
