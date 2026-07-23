"""The OpenAI client must carry an explicit bounded timeout.

The SDK default (600s per attempt x 3 attempts) turns a half-dead SSH tunnel
into a ~30-minute silent hang inside `provider.generate` — observed live
against the local vLLM path (2026-07-23): the tunnel side closed the socket,
the client sat in CLOSE_WAIT, and the agent loop looked frozen with no error.
A wedged connection must surface as a provider error within ~2 minutes.
"""
import pytest

pytest.importorskip("openai")

from backend.providers.openai import OpenAIProvider


def test_client_timeout_and_retries_are_bounded():
    provider = OpenAIProvider(model="m", base_url="http://localhost:1/v1")
    client = provider._get_client()
    t = client.timeout
    assert t is not None, "client must not use the SDK's unbounded default"
    for phase in ("connect", "read", "write", "pool"):
        v = getattr(t, phase)
        assert v is not None and v <= 180, f"{phase} timeout too long: {v}"
    # provider-level with_retry owns retries; SDK must not multiply the wait
    assert client.max_retries <= 1
