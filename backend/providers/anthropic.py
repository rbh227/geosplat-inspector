"""AnthropicProvider — drop-in ModelProvider adapter (stub, satisfies §6.6).

Mirrors GeminiProvider's normalization for Claude's Messages API:
  - ToolSpec[]          -> tools=[{name, description, input_schema}]
  - images: list[bytes] -> base64 image blocks on the latest user turn
  - 429 / overloaded    -> providers.errors.RateLimitError
  - tool_use blocks     -> ModelResponse.tool_calls

Lazy SDK import; the loop never changes when swapping to this provider.
Functional enough to run if `anthropic` is installed and a key is set; kept
a stub because Gemini is the default for the demo.
"""

from __future__ import annotations

import base64
import os
from typing import Any

from backend.contracts import ModelResponse, ToolCall, ToolSpec

from .errors import ProviderConfigError, RateLimitError
from .retry import with_retry

DEFAULT_MODEL = "claude-sonnet-5"


class AnthropicProvider:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        *,
        max_attempts: int = 5,
        system_instruction: str | None = None,
        max_tokens: int = 2048,
    ):
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.max_attempts = max_attempts
        self.system_instruction = system_instruction
        self.max_tokens = max_tokens
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import anthropic  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise ProviderConfigError(
                "anthropic not installed; `pip install anthropic`"
            ) from exc
        if not self.api_key:
            raise ProviderConfigError("No ANTHROPIC_API_KEY (env-only).")
        self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def _to_tools(self, tools: list[ToolSpec]) -> list[dict]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.parameters or {"type": "object", "properties": {}},
            }
            for t in tools
        ]

    def _to_messages(self, messages: list[dict], images: list[bytes] | None) -> list[dict]:
        out: list[dict] = []
        for msg in messages:
            role = "assistant" if msg.get("role") == "assistant" else "user"
            out.append({"role": role, "content": str(msg.get("content", ""))})
        if images:
            blocks: list[dict] = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.b64encode(img).decode("ascii"),
                    },
                }
                for img in images
            ]
            if out and out[-1]["role"] == "user":
                text = out[-1]["content"]
                out[-1]["content"] = [{"type": "text", "text": text}, *blocks]
            else:
                out.append({"role": "user", "content": blocks})
        return out

    def generate(
        self,
        messages: list[dict],
        tools: list[ToolSpec],
        images: list[bytes] | None = None,
    ) -> ModelResponse:
        client = self._get_client()

        def _call() -> Any:
            try:
                return client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    system=self.system_instruction or "",
                    tools=self._to_tools(tools),
                    messages=self._to_messages(messages, images),
                )
            except Exception as exc:  # noqa: BLE001
                name = type(exc).__name__.lower()
                if "ratelimit" in name or "overloaded" in name or "429" in str(exc):
                    raise RateLimitError(f"Anthropic rate limit: {exc}") from exc
                raise

        raw = with_retry(_call, max_attempts=self.max_attempts)
        return _parse_response(raw)


def _parse_response(raw: Any) -> ModelResponse:
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    for block in getattr(raw, "content", None) or []:
        btype = getattr(block, "type", None)
        if btype == "text":
            text_parts.append(getattr(block, "text", ""))
        elif btype == "tool_use":
            tool_calls.append(
                ToolCall(name=block.name, args=dict(getattr(block, "input", {}) or {}))
            )
    return ModelResponse(
        text="\n".join(text_parts) if text_parts else None,
        tool_calls=tool_calls,
        raw=raw,
    )


__all__ = ["AnthropicProvider", "DEFAULT_MODEL"]
