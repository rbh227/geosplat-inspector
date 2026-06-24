"""ModelProvider interface and related types (ARCHITECTURE.md §6.6). Frozen."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict


@dataclass
class ToolCall:
    name: str
    args: dict


@dataclass
class ModelResponse:
    text: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: Any = None


class ModelProvider(Protocol):
    def generate(
        self,
        messages: list[dict],
        tools: list[ToolSpec],
        images: list[bytes] | None = None,
    ) -> ModelResponse: ...
