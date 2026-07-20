"""Mock executors for offline development & acceptance tests.

  - MockProvider:        scripted/scriptable ModelProvider (no network).
  - MockBackendExecutor: in-memory stand-in for Agent 2's engine + Agent 1's
    history. Metrics improve when the matching edit runs; snapshot/undo work.
  - MockFrontendChannel: records commands & events; returns a fake PNG frame.

These satisfy the same interfaces (`ModelProvider`, `BackendExecutor`,
`FrontendChannel`) the real components will, so the loop is wired identically
in tests and at integration.
"""

from __future__ import annotations

import copy
from typing import Callable

from backend.contracts import ModelResponse, ToolSpec
from backend.contracts.constants import HIST_BINS

# A minimal valid 1x1 PNG (enough for "we got bytes back" + vision plumbing).
FAKE_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000d49444154789c6360000002000100000500010d0a2db4"
    "0000000049454e44ae426082"
)


# ── Provider ────────────────────────────────────────────────────────────
class MockProvider:
    """Returns scripted responses in order. `script` is a list of
    ModelResponse OR a callable(messages, tools, images)->ModelResponse.
    Set `raises` to an exception instance to simulate provider failure."""

    def __init__(self, script: list, *, name: str = "mock", raises: Exception | None = None):
        self._script = list(script)
        self._i = 0
        self.name = name
        self.raises = raises
        self.calls = 0

    def generate(self, messages, tools, images=None) -> ModelResponse:  # noqa: ANN001
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        if self._i >= len(self._script):
            # Default to a graceful finish if the script runs out.
            from backend.contracts import ToolCall

            return ModelResponse(text=None, tool_calls=[ToolCall("answer", {"text": "Done."})])
        item = self._script[self._i]
        self._i += 1
        if callable(item):
            return item(messages, tools, images)
        return item


# ── Frontend channel ────────────────────────────────────────────────────
class MockFrontendChannel:
    def __init__(self, frame: bytes = FAKE_PNG):
        self.frame = frame
        self.commands: list[dict] = []
        self.events: list[dict] = []

    async def send_command(self, cmd: dict) -> dict:
        self.commands.append(cmd)
        if cmd.get("type") == "capture_request":
            tool = cmd.get("tool")
            if tool == "capture_orbit":
                n = int(cmd.get("args", {}).get("n", 1))
                return {"ok": True, "frames": [self.frame] * n}
            return {"ok": True, "frame": self.frame}
        return {"ok": True}

    async def emit_event(self, event: dict) -> None:
        self.events.append(event)

    # convenience for assertions
    def event_types(self) -> list[str]:
        return [e.get("type") for e in self.events]

    def command_tools(self) -> list[str]:
        return [c.get("tool") for c in self.commands]


# ── Backend executor ────────────────────────────────────────────────────
def _zeros(n: int = HIST_BINS) -> list[int]:
    return [0] * n


class MockBackendExecutor:
    """In-memory scene with a few tunable 'badness' fractions. Edits reduce the
    fraction they target and the gaussian count; snapshot/undo restore exactly.

    `worsen` flips edits to *increase* the targeted fraction — used to exercise
    the loop's keep/undo path."""

    def __init__(self, *, count: int = 200_000, worsen: bool = False):
        self.worsen = worsen
        self.state = {
            "count": count,
            "near_transparent": 0.18,
            "outlier": 0.12,
            "oversized": 0.04,
            "needle": 0.06,
        }
        self._stack: list[dict] = []
        self.exported_path: str | None = None

    # -- history --
    def snapshot(self) -> None:
        self._stack.append(copy.deepcopy(self.state))

    def undo(self) -> dict:
        if self._stack:
            self.state = self._stack.pop()
        return {"count": self.state["count"]}

    def redo(self) -> dict:
        return {"count": self.state["count"]}

    def export_ply(self) -> str:
        self.exported_path = "/tmp/geosplat_export.ply"
        return self.exported_path

    # -- analysis --
    def get_metrics(self, region: dict | None = None) -> dict:
        s = self.state
        return {
            "gaussianCount": s["count"],
            "opacity": {
                "histogram": _zeros(),
                "nearTransparentFraction": s["near_transparent"],
                "mean": 0.6,
                "median": 0.62,
            },
            "scale": {
                "histogram": _zeros(),
                "oversizedFraction": s["oversized"],
                "axisRatio": {"histogram": _zeros(), "needleFraction": s["needle"]},
            },
            "spatial": {
                "nnDistance": {"mean": 0.01, "std": 0.004, "histogram": _zeros()},
                "outlierFraction": s["outlier"],
                "density": 1234.5,
            },
            "bounds": {"min": [-1, -1, -1], "max": [1, 1, 1], "volume": 8.0},
            "color": {"dcMean": [0.5, 0.5, 0.5], "dcStd": [0.1, 0.1, 0.1]},
            "computedAt": "2026-06-22T00:00:00Z",
            "region": region,
        }

    def get_bounds(self) -> dict:
        # Matches the bounds get_metrics reports, so grounding is consistent.
        return {"min": [-1.0, -1.0, -1.0], "max": [1.0, 1.0, 1.0]}

    def list_problem_regions(self) -> list[dict]:
        return [
            {
                "label": "floater-cloud-NE",
                "kind": "floaters",
                "severity": 0.9,
                "bbox_min": [0.5, 0.5, 0.5],
                "bbox_max": [1.0, 1.0, 1.0],
                "center": [0.75, 0.75, 0.75],
            },
            {
                "label": "outlier-spray-S",
                "kind": "outliers",
                "severity": 0.6,
                "bbox_min": [-1.0, -1.0, -1.0],
                "bbox_max": [-0.5, -0.5, -0.5],
                "center": [-0.75, -0.75, -0.75],
            },
        ]

    # -- editing (each returns before/after counts) --
    def _edit(self, key: str, removed: int) -> dict:
        before = self.state["count"]
        if self.worsen:
            self.state[key] = min(1.0, self.state[key] * 1.5 + 0.05)
            after = before  # nothing actually removed in the worsen scenario
        else:
            self.state[key] = round(self.state[key] * 0.1, 6)
            after = max(0, before - removed)
        self.state["count"] = after
        return {"before": before, "after": after, "removed": before - after}

    def opacity_threshold(self, min_alpha: float) -> dict:
        return self._edit("near_transparent", 30_000)

    def remove_outliers(self, k: int, std_ratio: float) -> dict:
        return self._edit("outlier", 18_000)

    def prune_oversized(self, max_axis_scene_frac: float) -> dict:
        return self._edit("oversized", 6_000)

    def remove_needles(self, max_axis_ratio: float) -> dict:
        return self._edit("needle", 9_000)

    def crop_bbox(self, min, max) -> dict:  # noqa: A002
        before = self.state["count"]
        self.state["count"] = int(before * 0.8)
        return {"before": before, "after": self.state["count"], "removed": before - self.state["count"]}

    def crop_sphere(self, center, radius, invert: bool = False) -> dict:
        before = self.state["count"]
        self.state["count"] = int(before * 0.9)
        return {"before": before, "after": self.state["count"], "removed": before - self.state["count"]}

    def recolor(self, selection: dict, rgb) -> dict:
        return {"ok": True}

    def adjust_opacity(self, selection: dict, factor: float) -> dict:
        return {"ok": True}

    def truncate_sh(self, degree: int) -> dict:
        return {"ok": True}


# ── Script helpers ──────────────────────────────────────────────────────
def tool_turn(*calls) -> ModelResponse:
    """Build a ModelResponse with one or more ToolCalls. Each `call` is a
    (name, args) tuple."""
    from backend.contracts import ToolCall

    return ModelResponse(
        text=None, tool_calls=[ToolCall(name, args) for name, args in calls]
    )


def text_then_tools(text: str, *calls) -> ModelResponse:
    from backend.contracts import ToolCall

    return ModelResponse(
        text=text, tool_calls=[ToolCall(name, args) for name, args in calls]
    )


__all__ = [
    "MockProvider",
    "MockFrontendChannel",
    "MockBackendExecutor",
    "FAKE_PNG",
    "tool_turn",
    "text_then_tools",
]
