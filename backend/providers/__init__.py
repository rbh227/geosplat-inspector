"""Model providers — adapters behind the frozen `ModelProvider` interface (§6.6).

Gemini is the default; Anthropic/OpenAI are drop-in. Vendor SDKs import lazily
so this package imports cleanly without them. Select via `get_provider()`.
"""

from .anthropic import AnthropicProvider
from .errors import ProviderConfigError, ProviderError, RateLimitError
from .factory import DEFAULT_PROVIDER, PROVIDERS, get_provider
from .gemini import GeminiProvider
from .openai import OpenAIProvider
from .retry import with_retry

__all__ = [
    "get_provider",
    "PROVIDERS",
    "DEFAULT_PROVIDER",
    "GeminiProvider",
    "AnthropicProvider",
    "OpenAIProvider",
    "with_retry",
    "ProviderError",
    "RateLimitError",
    "ProviderConfigError",
]
