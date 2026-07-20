"""backend.providers.factory.get_provider — argument forwarding for the
in-app model picker (api_key/base_url), on top of the existing name/model
resolution (env -> default)."""

from __future__ import annotations

import pytest

from backend.providers.errors import ProviderConfigError
from backend.providers.factory import get_provider


def test_forwards_api_key_and_base_url_to_openai_adapter():
    provider = get_provider("openai", "gpt-4o-mini", api_key="k-123", base_url="http://localhost:11434/v1")
    assert provider.api_key == "k-123"
    assert provider.base_url == "http://localhost:11434/v1"


def test_forwards_api_key_to_gemini_adapter():
    provider = get_provider("gemini", api_key="gk-123")
    assert provider.api_key == "gk-123"


def test_forwards_api_key_to_anthropic_adapter():
    provider = get_provider("anthropic", api_key="ak-123")
    assert provider.api_key == "ak-123"


def test_base_url_rejected_for_non_openai_provider():
    with pytest.raises(ProviderConfigError):
        get_provider("gemini", base_url="http://localhost:11434/v1")


def test_omitted_api_key_falls_back_to_adapter_env_default(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    provider = get_provider("gemini")
    assert provider.api_key == "env-key"


def test_unknown_provider_name_still_raises():
    with pytest.raises(ProviderConfigError):
        get_provider("not-a-real-provider")
