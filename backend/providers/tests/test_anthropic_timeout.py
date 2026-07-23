"""Same rationale as test_openai_timeout: a wedged connection must surface as
a provider error within ~2 minutes, not hang for the SDK's 10-minute default."""
import pytest

pytest.importorskip("anthropic")

from backend.providers.anthropic import AnthropicProvider


def test_client_timeout_and_retries_are_bounded():
    provider = AnthropicProvider(model="m", api_key="k")
    client = provider._get_client()
    t = client.timeout
    assert t is not None, "client must not use the SDK's unbounded default"
    for phase in ("connect", "read", "write", "pool"):
        v = getattr(t, phase)
        assert v is not None and v <= 180, f"{phase} timeout too long: {v}"
    assert client.max_retries <= 1
