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


def solid_core(m: Metrics) -> float:
    """Estimated count of SOLID (non-near-transparent) Gaussians — a proxy for
    the dense subject, ignoring the mostly-transparent noise/floater halo."""
    return m["gaussianCount"] * (1.0 - m["opacity"]["nearTransparentFraction"])


def silhouette_intact(
    before: Metrics,
    after: Metrics,
    min_core_retained: float = 0.5,
    max_total_drop: float = 0.9,
    *,
    approved: bool = False,
    min_core_retained_approved: float = 0.01,
) -> bool:
    """Subject-aware guard: an edit is fine as long as it keeps the dense
    subject, even if it removes the majority of the *total* Gaussians (on messy
    outdoor scenes the noise — floaters/needles — is often the majority).

    Instead of judging by raw total count, judge by the SOLID core (the
    non-near-transparent Gaussians, a proxy for the actual subject). Keep the
    edit when the solid core is largely retained
    (``core_after / core_before >= min_core_retained``), so correctly removing
    transparent/noise Gaussians passes even when the total drop exceeds 50%,
    while an edit that destroys the dense subject still reverts.

    A catastrophic-total-drop backstop always reverts when the edit deletes more
    than ``max_total_drop`` of the entire scene, regardless of the core ratio.

    ``approved=True`` marks an operation the operator reviewed and approved (a
    banked ``propose_decision`` bound to this exact edit). Their approval is
    then the subject-protection mechanism, and only a catastrophic result
    overrides it: the core must survive at ``min_core_retained_approved``. The
    total-count backstop does NOT apply, because raw total is a meaningless
    denominator on junk-dominated captures — measured on
    ``public/demos/iona_park.ply``, 96.6% of the 2,000,000 splats are
    near-transparent, so an opacity sweep that retains 100% of the visible core
    still drops 96% of the scene and the backstop reverted it.

    Used by the flagship floater loop alongside the before/after capture check.
    """
    b = before["gaussianCount"]
    a = after["gaussianCount"]
    if b == 0:
        return True

    core_before = solid_core(before)
    core_after = solid_core(after)

    if approved:
        if core_before <= 0:
            # Nothing visible to protect; only a total wipe is catastrophic.
            return a > 0
        return core_after / core_before >= min_core_retained_approved

    # Catastrophic backstop: never let a single edit wipe out almost everything.
    if (b - a) / b > max_total_drop:
        return False

    if core_before <= 0:
        # No solid subject to protect; fall back to total-count survival.
        return (b - a) / b <= max_total_drop
    return core_after / core_before >= min_core_retained


__all__ = ["verify_edit", "VerifyResult", "silhouette_intact", "solid_core"]
