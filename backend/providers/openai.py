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
        base_url: str | None = None,
        max_attempts: int = 5,
        system_instruction: str | None = None,
    ):
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        # When base_url points at a local/self-hosted OpenAI-compatible server
        # (vLLM, Ollama, LM Studio, ...), the same OpenAIProvider becomes a
        # universal backend. Defaults to OPENAI_BASE_URL so it stays env-only.
        self.base_url = base_url or os.environ.get("OPENAI_BASE_URL")
        self.max_attempts = max_attempts
        self.system_instruction = system_instruction
        self._client: Any = None
        # Whether the server accepts tool_choice="required" — assumed until a
        # 400 proves otherwise (see generate()).
        self._tool_choice_required = True

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import openai  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise ProviderConfigError(
                "openai not installed; `pip install openai`"
            ) from exc
        # Local endpoints don't authenticate, but the SDK still needs a
        # non-empty key, so fall back to a placeholder when a base_url is set.
        # A real OpenAI call (no base_url) keeps the strict key requirement.
        api_key = self.api_key
        if not api_key:
            if self.base_url:
                api_key = "not-needed"
            else:
                raise ProviderConfigError("No OPENAI_API_KEY (env-only).")
        import httpx  # openai's own transport dep, always present with it

        # Bounded timeout: the SDK default (600s per attempt, 2 retries) turns
        # a half-dead SSH tunnel into a ~30-minute silent hang inside
        # `generate`. A wedged socket must surface as a provider error within
        # ~2 minutes. Retries are with_retry's job (rate limits only) — an
        # SDK-level retry would just multiply the wait.
        self._client = openai.OpenAI(
            api_key=api_key,
            base_url=self.base_url,
            timeout=httpx.Timeout(120.0, connect=10.0),
            max_retries=0,
        )
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
            # Preserve system/assistant; everything else (incl. the loop's
            # synthetic [tool_result ...] turns) is a user turn. Keeping the
            # system role lets tool-aware chat templates put it in the system
            # block where the tool list is injected.
            src = msg.get("role")
            role = src if src in ("assistant", "system") else "user"
            out.append({"role": role, "content": str(msg.get("content", ""))})
        if images:
            parts: list[dict] = [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{_image_mime(img)};base64,"
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
            # tool_choice="required": the loop is tool-driven end to end (even
            # finishing is the answer() tool), and weaker models drift into
            # narrating plans in prose instead of acting — forcing a tool call
            # per turn removes that failure mode structurally. Servers that
            # don't support "required" get one 400, then we remember and fall
            # back to auto for the life of this provider.
            payload_tools = self._to_tools(tools) or None
            # max_tokens is REQUIRED against vLLM: without it the server
            # budgets KV for the full remaining context (~27K tokens), which
            # cannot co-schedule at tight KV configs — measured live as a
            # 150s hang vs 0.7s with the cap. A tool call is ~16 tokens and
            # an answer a few hundred; 1024 is generous.
            kwargs: dict[str, Any] = {"max_tokens": 1024}
            if payload_tools and self._tool_choice_required:
                kwargs["tool_choice"] = "required"
            try:
                return client.chat.completions.create(
                    model=self.model,
                    messages=self._to_messages(messages, images),
                    tools=payload_tools,
                    **kwargs,
                )
            except Exception as exc:  # noqa: BLE001
                name = type(exc).__name__.lower()
                if "ratelimit" in name or "429" in str(exc):
                    raise RateLimitError(f"OpenAI rate limit: {exc}") from exc
                if "tool_choice" in kwargs:
                    msg = str(exc)
                    if "tool_choice" in msg:
                        # Server rejects the parameter outright — remember.
                        self._tool_choice_required = False
                    elif not ("json_invalid" in msg or "Invalid JSON" in msg
                              or "EOF while parsing" in msg):
                        raise
                    # Grammar degeneration (observed live on Qwen3-VL + vLLM):
                    # forced into the tool-call grammar on a turn where it
                    # wants prose, the model emits whitespace until the token
                    # cap and the server 400s with invalid JSON. Retry THIS
                    # turn unforced — the loop's stall guard handles prose.
                    return client.chat.completions.create(
                        model=self.model,
                        messages=self._to_messages(messages, images),
                        tools=payload_tools,
                        max_tokens=1024,
                    )
                raise

        raw = with_retry(_call, max_attempts=self.max_attempts)
        return _parse_response(raw)


def _image_mime(img: bytes) -> str:
    """Captures are JPEG since the WS-size fix; older callers may still send
    PNG. The data URL must describe the actual bytes."""
    return "image/jpeg" if img[:2] == b"\xff\xd8" else "image/png"


def _parse_response(raw: Any) -> ModelResponse:
    choice = (getattr(raw, "choices", None) or [None])[0]
    message = getattr(choice, "message", None)
    text = getattr(message, "content", None)
    truncated = getattr(choice, "finish_reason", None) == "length"
    tool_calls: list[ToolCall] = []
    notes: list[str] = []
    for tc in getattr(message, "tool_calls", None) or []:
        fn = getattr(tc, "function", None)
        name = getattr(fn, "name", "")
        try:
            args = json.loads(getattr(fn, "arguments", "") or "{}")
        except json.JSONDecodeError:
            # NEVER coerce to {} silently: a length-truncated answer() would
            # complete the run with a BLANK answer, and a truncated edit call
            # would dispatch with missing args and a misleading error. Drop
            # the call and tell the model (via text) so it retries smaller.
            notes.append(
                f"(your {name} tool call had truncated/invalid JSON arguments"
                f"{' — you hit the output token limit' if truncated else ''}; "
                f"retry it with shorter arguments)"
            )
            continue
        tool_calls.append(ToolCall(name=name, args=args))
    if notes:
        text = " ".join(filter(None, [text, *notes]))
    return ModelResponse(text=text, tool_calls=tool_calls, raw=raw)


__all__ = ["OpenAIProvider", "DEFAULT_MODEL"]
