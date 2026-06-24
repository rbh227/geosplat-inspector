"""Grounding enforcement (§8 grounding rule).

"The agent may only assert what it read from a metric or saw in a captured
frame." We can't fully parse natural language, so we enforce a pragmatic,
testable contract:

  1. The agent must have measured (get_metrics / a tool result) or seen
     (a captured frame) *something* before it answers.
  2. Any concrete numeric claim in the answer (percent or decimal) must match
     — within tolerance — a value the agent actually recorded.

The `GroundingLedger` accumulates recorded numbers as tools run; `check()`
raises `GroundingError` on an unsupported claim. The loop treats that as a
failed answer (and can ask the model to revise).
"""

from __future__ import annotations

import re
from typing import Any

_NUM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(%?)")


class GroundingError(Exception):
    """An answer asserted a number that was never measured or seen."""


class GroundingLedger:
    def __init__(self, tolerance: float = 0.02):
        self._values: set[float] = set()
        self.measured = False
        self.saw_frame = False
        self.tolerance = tolerance  # relative tolerance for matching claims

    # -- recording --------------------------------------------------------
    def record_metrics(self, metrics: dict) -> None:
        self.measured = True
        self._harvest(metrics)

    def record_tool_result(self, result: Any) -> None:
        if isinstance(result, (dict, list)):
            self.measured = True
            self._harvest(result)

    def record_frame(self) -> None:
        self.saw_frame = True

    def _harvest(self, obj: Any) -> None:
        if isinstance(obj, bool):
            return
        if isinstance(obj, (int, float)):
            v = float(obj)
            self._values.add(v)
            # Also register the percentage form of a [0,1] fraction.
            if 0.0 <= v <= 1.0:
                self._values.add(round(v * 100, 4))
            return
        if isinstance(obj, dict):
            for val in obj.values():
                self._harvest(val)
        elif isinstance(obj, (list, tuple)):
            for val in obj:
                self._harvest(val)

    # -- checking ---------------------------------------------------------
    def _is_known(self, claim: float) -> bool:
        for v in self._values:
            scale = max(abs(v), abs(claim), 1.0)
            if abs(v - claim) <= self.tolerance * scale:
                return True
        return False

    def check(self, text: str) -> None:
        """Raise GroundingError if `text` makes an unsupported numeric claim."""
        if not (self.measured or self.saw_frame):
            raise GroundingError(
                "Answer produced before any measurement or captured frame."
            )
        for raw, pct in _NUM_RE.findall(text or ""):
            claim = float(raw)
            # A bare small integer (e.g. "1 region", "2 passes") is narrative,
            # not a measurement claim; only scrutinize decimals and percents.
            if not pct and "." not in raw:
                continue
            if not self._is_known(claim):
                raise GroundingError(
                    f"Ungrounded numeric claim {raw}{pct!r}: not among measured values."
                )


__all__ = ["GroundingLedger", "GroundingError"]
