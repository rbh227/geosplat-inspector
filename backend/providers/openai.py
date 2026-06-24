"""OpenAIProvider — drop-in ModelProvider adapter (stub, satisfies §6.6).

Normalization for the Chat Completions API:
  - ToolSpec[]          -> tools=[{type:function, function:{name,description,parameters}}]
  - images: list[bytes] -> image_url (data URL) content parts on last user turn
  - 429                 -> providers.errors.RateLimitError
  - message.tool_calls  -> ModelResponse.tool_calls (args JSON-parsed)

Lazy SDK import; loop-agnostic. Stub because Gemini is the demo default.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

from backend.contracts import ModelResponse, ToolCall, ToolSpec

from .errors import ProviderConfigError, RateLimitError
from .retry import with_retry

DEFAULT_MODEL = "gpt-4o-mini"


class OpenAIProvider:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        *,
        max_attempts: int = 5,
        system_instruction: str | None = None,
    ):
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.max_attempts = max_attempts
        self.system_instruction = system_instruction
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import openai  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise ProviderConfigError(
                "openai not installed; `pip install openai`"
            ) from exc
        if not self.api_key:
            raise ProviderConfigError("No OPENAI_API_KEY (env-only).")
        self._client = openai.OpenAI(api_key=self.api_key)
        return self._client

    def _to_tools(self, tools: list[ToolSpec]) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters or {"type": "object", "properties": {}},
                },
            }
            for t in tools
        ]

    def _to_messages(self, messages: list[dict], images: list[bytes] | None) -> list[dict]:
        out: list[dict] = []
        if self.system_instruction:
            out.append({"role": "system", "content": self.system_instruction})
        for msg in messages:
            role = "assistant" if msg.get("role") == "assistant" else "user"
            out.append({"role": role, "content": str(msg.get("content", ""))})
        if images:
            parts: list[dict] = [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/png;base64,"
                        + base64.b64encode(img).decode("ascii")
                    },
                }
                for img in images
            ]
            if out and out[-1]["role"] == "user":
                text = out[-1]["content"]
                out[-1]["content"] = [{"type": "text", "text": text}, *parts]
            else:
                out.append({"role": "user", "content": parts})
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
                return client.chat.completions.create(
                    model=self.model,
                    messages=self._to_messages(messages, images),
                    tools=self._to_tools(tools) or None,
                )
            except Exception as exc:  # noqa: BLE001
                name = type(exc).__name__.lower()
                if "ratelimit" in name or "429" in str(exc):
                    raise RateLimitError(f"OpenAI rate limit: {exc}") from exc
                raise

        raw = with_retry(_call, max_attempts=self.max_attempts)
        return _parse_response(raw)


def _parse_response(raw: Any) -> ModelResponse:
    choice = (getattr(raw, "choices", None) or [None])[0]
    message = getattr(choice, "message", None)
    text = getattr(message, "content", None)
    tool_calls: list[ToolCall] = []
    for tc in getattr(message, "tool_calls", None) or []:
        fn = getattr(tc, "function", None)
        try:
            args = json.loads(getattr(fn, "arguments", "") or "{}")
        except json.JSONDecodeError:
            args = {}
        tool_calls.append(ToolCall(name=getattr(fn, "name", ""), args=args))
    return ModelResponse(text=text, tool_calls=tool_calls, raw=raw)


__all__ = ["OpenAIProvider", "DEFAULT_MODEL"]
