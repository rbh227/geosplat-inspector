"""Edit verification — the "verify" in perceive→act→verify (§3.4, §7).

After a destructive edit the loop re-measures and asks: did the metric this
edit targets actually improve? If not, the edit is undone. The improvement
direction for each tool lives here, once, derived from the Metrics schema
(§6.4). The outlier *criterion* itself lives in the metrics engine (R3); here
we only compare the resulting fractions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.contracts import Metrics

# tool -> (dotted metric path, must decrease?). "intended-shrink" edits
# (crops) are judged by gaussianCount going down; recolor/adjust/truncate_sh
# are appearance-only and always "kept" (no objective metric to worsen).
_TARGET: dict[str, tuple[str, bool]] = {
    "opacity_threshold": ("opacity.nearTransparentFraction", True),
    "remove_outliers": ("spatial.outlierFraction", True),
    "prune_oversized": ("scale.oversizedFraction", True),
    "remove_needles": ("scale.axisRatio.needleFraction", True),
    "crop_bbox": ("gaussianCount", True),
    "crop_sphere": ("gaussianCount", True),
}

_APPEARANCE_ONLY = {"recolor", "adjust_opacity", "truncate_sh"}


@dataclass
class VerifyResult:
    improved: bool
    metric: str | None
    before: float | None
    after: float | None
    detail: str


def _dig(metrics: Metrics, path: str) -> float:
    cur: Any = metrics
    for key in path.split("."):
        cur = cur[key]
    return float(cur)


def verify_edit(tool: str, before: Metrics, after: Metrics) -> VerifyResult:
    """Return whether `tool`'s target metric improved from before->after."""
    if tool in _APPEARANCE_ONLY:
        return VerifyResult(True, None, None, None, f"{tool}: appearance-only, kept")
    target = _TARGET.get(tool)
    if target is None:
        return VerifyResult(True, None, None, None, f"{tool}: no metric target, kept")

    path, must_decrease = target
    b, a = _dig(before, path), _dig(after, path)
    improved = (a < b) if must_decrease else (a > b)
    arrow = "↓" if a < b else ("↑" if a > b else "=")
    detail = f"{path}: {b:.4g} {arrow} {a:.4g} ({'improved' if improved else 'worse/flat'})"
    return VerifyResult(improved, path, b, a, detail)


def silhouette_intact(before: Metrics, after: Metrics, max_drop: float = 0.5) -> bool:
    """Cheap guard: an edit shouldn't delete more than `max_drop` of the scene
    (a proxy for 'silhouette intact' until vision confirms). Used by the
    flagship floater loop alongside the before/after capture check."""
    b = before["gaussianCount"]
    a = after["gaussianCount"]
    if b == 0:
        return True
    return (b - a) / b <= max_drop


__all__ = ["verify_edit", "VerifyResult", "silhouette_intact"]
