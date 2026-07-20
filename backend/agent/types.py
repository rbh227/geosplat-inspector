"""Agent-loop-internal types and trace-event constructors.

Trace events are plain dicts matching the WS protocol (§6.8):
`thought`, `tool_call`, `tool_result`, `complete` (+ `narrate` via emit_event).
They are emitted fire-and-forget through `FrontendChannel.emit_event`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

# Backend tools that mutate the alive mask / parameters → must snapshot first
# and trigger a verify step. Sourced from the tool contract (§6.5).
DESTRUCTIVE_TOOLS: frozenset[str] = frozenset(
    {
        "opacity_threshold",
        "remove_outliers",
        "prune_oversized",
        "remove_needles",
        "crop_bbox",
        "crop_sphere",
        "recolor",
        "adjust_opacity",
        "truncate_sh",
        # v0.2 — selection edits go through the same snapshot + verify loop
        "delete_selection",
        "keep_selection",
    }
)

# Capture tools count against the vision budget (R4/R5).
VISION_TOOLS: frozenset[str] = frozenset({"capture_frame", "capture_orbit"})


def _now() -> float:
    return time.time()


def ev_thought(text: str, step: int) -> dict:
    return {"type": "thought", "text": text, "step": step, "t": _now()}


def ev_tool_call(name: str, args: dict, step: int) -> dict:
    return {"type": "tool_call", "name": name, "args": args, "step": step, "t": _now()}


def ev_tool_result(name: str, result: Any, step: int) -> dict:
    return {"type": "tool_result", "name": name, "result": result, "step": step, "t": _now()}


def ev_narrate(text: str) -> dict:
    return {"type": "narrate", "text": text, "t": _now()}


def ev_complete(status: str, *, answer: str | None = None, error: str | None = None) -> dict:
    return {"type": "complete", "status": status, "answer": answer, "error": error, "t": _now()}


@dataclass
class ProblemRegion:
    """A ranked region of interest (from list_problem_regions / metrics)."""

    label: str
    bbox_min: list[float]
    bbox_max: list[float]
    severity: float
    kind: str  # "floaters" | "outliers" | "oversized" | "needles" | ...

    def center(self) -> list[float]:
        return [(a + b) / 2.0 for a, b in zip(self.bbox_min, self.bbox_max)]


@dataclass
class LoopResult:
    """Outcome of an AgentLoop.run()."""

    status: str                       # "answered" | "max_steps" | "error" | "rate_limited"
    answer: str | None = None
    error: str | None = None
    steps: int = 0
    vision_calls: int = 0
    trace: list[dict] = field(default_factory=list)
    edits_kept: int = 0
    edits_reverted: int = 0


__all__ = [
    "DESTRUCTIVE_TOOLS",
    "VISION_TOOLS",
    "ProblemRegion",
    "LoopResult",
    "ev_thought",
    "ev_tool_call",
    "ev_tool_result",
    "ev_narrate",
    "ev_complete",
]
