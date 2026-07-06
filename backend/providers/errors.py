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


class QuotaExhaustedError(RateLimitError):
    """A *hard* quota wall (e.g. free-tier daily limit) that backoff cannot clear.

    Distinct from a transient per-minute 429: there is no point sleeping and
    retrying the same model, so `with_retry` re-raises this immediately and the
    caller can switch to a different model/provider instead.
    """


class ProviderConfigError(ProviderError):
    """Misconfiguration: missing SDK, missing API key, or unknown provider."""


__all__ = [
    "ProviderError",
    "RateLimitError",
    "QuotaExhaustedError",
    "ProviderConfigError",
]
