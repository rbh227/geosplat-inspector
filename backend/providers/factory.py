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
) -> ModelProvider:
    """Construct the configured ModelProvider.

    Resolution order: explicit arg -> env -> default.
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
    return cls(**kwargs)


__all__ = ["get_provider", "PROVIDERS", "DEFAULT_PROVIDER"]
