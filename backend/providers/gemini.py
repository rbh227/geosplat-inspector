"""GeminiProvider — default ModelProvider adapter (ARCHITECTURE.md §6.6, §2.3).

Uses `google-genai` with `gemini-2.5-flash` (free tier). Supports vision
(captured PNG frames as inline image parts) and function calling. The SDK is
imported lazily inside methods so this module imports cleanly even when
`google-genai` is absent (local dev / test); the loop talks only to the
`ModelProvider` Protocol.

Normalization responsibilities of this adapter:
  - ToolSpec[]              -> a single genai Tool with function_declarations
  - list[dict] messages     -> genai `contents` (role/parts)
  - images: list[bytes]     -> inline_data parts on the latest user turn
  - vendor 429 / quota      -> providers.errors.RateLimitError
  - vendor response         -> contracts.ModelResponse(text, tool_calls, raw)
"""

from __future__ import annotations

import os
from typing import Any

from backend.contracts import ModelResponse, ToolCall, ToolSpec

from .errors import ProviderConfigError, RateLimitError
from .retry import with_retry

DEFAULT_MODEL = "gemini-2.5-flash"


class GeminiProvider:
    """Implements the ModelProvider Protocol against Google's google-genai SDK."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        *,
        max_attempts: int = 5,
        system_instruction: str | None = None,
    ):
        self.model = model
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get(
            "GOOGLE_API_KEY"
        )
        self.max_attempts = max_attempts
        self.system_instruction = system_instruction
        self._client: Any = None  # built lazily

    # -- SDK plumbing -----------------------------------------------------
    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from google import genai  # type: ignore
        except ImportError as exc:  # pragma: no cover - exercised in Docker image
            raise ProviderConfigError(
                "google-genai not installed; `pip install google-genai`"
            ) from exc
        if not self.api_key:
            raise ProviderConfigError(
                "No Gemini API key. Set GEMINI_API_KEY (env-only; never in code)."
            )
        from google.genai import types  # type: ignore

        # Bounded timeout (ms): mirrors openai.py — the SDK default turns a
        # half-dead tunnel into a multi-minute silent hang inside `generate`.
        self._client = genai.Client(
            api_key=self.api_key,
            http_options=types.HttpOptions(timeout=120_000),
        )
        return self._client

    def _to_genai_tools(self, tools: list[ToolSpec]) -> list[Any]:
        from google.genai import types  # type: ignore

        declarations = [
            types.FunctionDeclaration(
                name=t.name,
                description=t.description,
                parameters=t.parameters or {"type": "object", "properties": {}},
            )
            for t in tools
        ]
        return [types.Tool(function_declarations=declarations)]

    def _to_contents(self, messages: list[dict], images: list[bytes] | None) -> list[Any]:
        from google.genai import types  # type: ignore

        contents: list[Any] = []
        for msg in messages:
            role = "model" if msg.get("role") == "assistant" else "user"
            parts = [types.Part.from_text(text=str(msg.get("content", "")))]
            contents.append(types.Content(role=role, parts=parts))
        if images:
            img_parts = [
                types.Part.from_bytes(data=img, mime_type="image/png") for img in images
            ]
            if contents and contents[-1].role == "user":
                contents[-1].parts.extend(img_parts)
            else:
                contents.append(types.Content(role="user", parts=img_parts))
        return contents

    # -- ModelProvider interface -----------------------------------------
    def generate(
        self,
        messages: list[dict],
        tools: list[ToolSpec],
        images: list[bytes] | None = None,
    ) -> ModelResponse:
        client = self._get_client()
        from google.genai import types  # type: ignore

        config = types.GenerateContentConfig(
            tools=self._to_genai_tools(tools) if tools else None,
            system_instruction=self.system_instruction,
        )
        contents = self._to_contents(messages, images)

        def _call() -> Any:
            try:
                return client.models.generate_content(
                    model=self.model, contents=contents, config=config
                )
            except Exception as exc:  # noqa: BLE001 - normalize vendor errors
                if _is_rate_limit(exc):
                    raise RateLimitError(f"Gemini rate limit: {exc}") from exc
                raise

        raw = with_retry(_call, max_attempts=self.max_attempts)
        return _parse_response(raw)


def _is_rate_limit(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    return (
        code == 429
        or "resourceexhausted" in name
        or "ratelimit" in name
        or "429" in str(exc)
    )


def _parse_response(raw: Any) -> ModelResponse:
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    candidates = getattr(raw, "candidates", None) or []
    for cand in candidates:
        content = getattr(cand, "content", None)
        for part in getattr(content, "parts", None) or []:
            if getattr(part, "text", None):
                text_parts.append(part.text)
            fc = getattr(part, "function_call", None)
            if fc is not None:
                args = dict(getattr(fc, "args", {}) or {})
                tool_calls.append(ToolCall(name=fc.name, args=args))
    text = "\n".join(text_parts) if text_parts else None
    return ModelResponse(text=text, tool_calls=tool_calls, raw=raw)


__all__ = ["GeminiProvider", "DEFAULT_MODEL"]
