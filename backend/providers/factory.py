"""Provider selection via env (ARCHITECTURE.md §6.6).

`MODEL_PROVIDER` (default "gemini") picks the adapter; `MODEL_NAME` overrides
the model id. The agent loop receives a `ModelProvider` and never knows which
vendor it is — swapping providers is purely an env change, no loop edit.
"""

from __future__ import annotations

import os

from backend.contracts import ModelProvider

from .anthropic import AnthropicProvider
from .errors import ProviderConfigError
from .gemini import GeminiProvider
from .openai import OpenAIProvider

PROVIDERS: dict[str, type] = {
    "gemini": GeminiProvider,
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
}

DEFAULT_PROVIDER = "gemini"


def get_provider(
    name: str | None = None,
    model: str | None = None,
    *,
    system_instruction: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> ModelProvider:
    """Construct the configured ModelProvider.

    Resolution order: explicit arg -> env -> default. `api_key`/`base_url` are
    forwarded to the adapter when given (each adapter falls back to its own
    env var when omitted, so passing None here preserves today's behavior).
    """
    name = (name or os.environ.get("MODEL_PROVIDER") or DEFAULT_PROVIDER).lower()
    model = model or os.environ.get("MODEL_NAME")
    cls = PROVIDERS.get(name)
    if cls is None:
        raise ProviderConfigError(
            f"Unknown MODEL_PROVIDER={name!r}; choose one of {sorted(PROVIDERS)}"
        )
    kwargs: dict = {"system_instruction": system_instruction}
    if model:
        kwargs["model"] = model
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        if name != "openai":
            raise ProviderConfigError(
                f"base_url is only supported for the openai provider "
                f"(OpenAI-compatible self-hosted endpoints), not {name!r}"
            )
        kwargs["base_url"] = base_url
    return cls(**kwargs)


__all__ = ["get_provider", "PROVIDERS", "DEFAULT_PROVIDER"]
