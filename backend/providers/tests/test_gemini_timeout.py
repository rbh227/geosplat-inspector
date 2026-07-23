"""Gemini path of the bounded-timeout rule (see test_openai_timeout)."""
import pytest

genai = pytest.importorskip("google.genai")

from backend.providers.gemini import GeminiProvider


def test_client_carries_bounded_timeout(monkeypatch):
    captured: dict = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(genai, "Client", FakeClient)
    provider = GeminiProvider(model="m", api_key="k")
    provider._get_client()
    opts = captured.get("http_options")
    assert opts is not None, "client must set http_options with a bounded timeout"
    assert opts.timeout is not None and opts.timeout <= 180_000  # milliseconds
