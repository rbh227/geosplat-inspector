"""Normalized provider errors.

Adapters translate vendor-specific exceptions into these so the agent loop
never imports a vendor SDK and can handle failures uniformly.
"""

from __future__ import annotations


class ProviderError(Exception):
    """Base class for any model-provider failure."""


class RateLimitError(ProviderError):
    """The provider signalled a rate limit / quota exhaustion (e.g. HTTP 429).

    `retry_after` is seconds if the vendor supplied it, else None.
    """

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class ProviderConfigError(ProviderError):
    """Misconfiguration: missing SDK, missing API key, or unknown provider."""


__all__ = ["ProviderError", "RateLimitError", "ProviderConfigError"]
