"""Exponential backoff for rate-limited provider calls (Risk R4).

Vendor adapters wrap their network call in `with_retry`. On `RateLimitError`
it sleeps `base_delay * 2**attempt` (capped, with jitter), honoring an
explicit `retry_after` when present. After `max_attempts` it re-raises the
last `RateLimitError` with a clear, surfaced message — the loop turns that
into a `complete` event rather than crashing.

`sleep` is injectable so tests can assert backoff without real waiting.
"""

from __future__ import annotations

import random
import time
from typing import Callable, TypeVar

from .errors import RateLimitError

T = TypeVar("T")


def with_retry(
    call: Callable[[], T],
    *,
    max_attempts: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter: bool = True,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Invoke `call`, retrying on RateLimitError with exponential backoff.

    Returns the call result. Raises the final RateLimitError if all attempts
    are exhausted (message names the attempt count so the failure is legible).
    """
    last_exc: RateLimitError | None = None
    for attempt in range(max_attempts):
        try:
            return call()
        except RateLimitError as exc:
            last_exc = exc
            if attempt == max_attempts - 1:
                break
            delay = min(base_delay * (2 ** attempt), max_delay)
            if exc.retry_after is not None:
                delay = max(delay, exc.retry_after)
            if jitter:
                delay += random.uniform(0, base_delay)
            sleep(delay)
    assert last_exc is not None
    raise RateLimitError(
        f"Provider rate-limited after {max_attempts} attempts: {last_exc}",
        retry_after=last_exc.retry_after,
    )


__all__ = ["with_retry"]
