"""Tier-4 closed loops: detect -> fix -> verify -> keep/undo (§7).

These are deterministic orchestrations over the `ToolDispatcher` (no model in
the inner loop), used for the flagship demo and as ground-truth tests of the
verify/keep/undo machinery. The agent loop can also reach these behaviours by
calling the same tools; here they are explicit and repeatable.

Four problem kinds, each a fix tool + the metric it must lower + a loosening
schedule (more aggressive params on retry, ≤ max_retries):
  floaters  -> opacity_threshold  (opacity.nearTransparentFraction)
  outliers  -> remove_outliers    (spatial.outlierFraction)
  oversized -> prune_oversized    (scale.oversizedFraction)
  needles   -> remove_needles     (scale.axisRatio.needleFraction)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from backend.contracts import ToolCall
from backend.contracts.constants import (
    FLOATER_ALPHA,
    NEEDLE_RATIO,
    OUTLIER_K,
    OUTLIER_STD_RATIO,
    OVERSIZED_SCENE_FRAC,
)

from .dispatch import ToolDispatcher
from .types import ev_narrate
from .verify import verify_edit


@dataclass
class FixSpec:
    kind: str
    tool: str
    # params(attempt) -> args dict; attempt 0 = baseline, then progressively looser
    params: Callable[[int], dict]


FIXES: dict[str, FixSpec] = {
    "floaters": FixSpec(
        "floaters",
        "opacity_threshold",
        lambda a: {"min_alpha": round(FLOATER_ALPHA * (1.5 ** a), 4)},
    ),
    "outliers": FixSpec(
        "outliers",
        "remove_outliers",
        lambda a: {"k": OUTLIER_K, "std_ratio": round(OUTLIER_STD_RATIO - 0.5 * a, 3)},
    ),
    "oversized": FixSpec(
        "oversized",
        "prune_oversized",
        lambda a: {"max_axis_scene_frac": round(OVERSIZED_SCENE_FRAC * (0.7 ** a), 5)},
    ),
    "needles": FixSpec(
        "needles",
        "remove_needles",
        lambda a: {"max_axis_ratio": round(NEEDLE_RATIO * (0.8 ** a), 3)},
    ),
}


@dataclass
class FixOutcome:
    kind: str
    kept: bool
    attempts: int
    before: float | None
    after: float | None
    detail: str
    trace: list[dict] = field(default_factory=list)


async def run_fix_verify(
    dispatcher: ToolDispatcher,
    kind: str,
    *,
    max_retries: int = 2,
) -> FixOutcome:
    """Detect->fix->verify->keep/undo for one problem kind, with loosen-retry."""
    spec = FIXES[kind]
    trace: list[dict] = []
    best_before: float | None = None

    for attempt in range(max_retries + 1):
        before = await _metrics(dispatcher)
        if best_before is None:
            best_before = _dig(before, _metric_path(spec.tool))

        call = ToolCall(spec.tool, spec.params(attempt))
        result = await dispatcher.dispatch(call)  # auto-snapshots + edits
        trace.append({"attempt": attempt, "tool": spec.tool, "args": call.args, "result": result})

        after = await _metrics(dispatcher)
        vr = verify_edit(spec.tool, before, after)

        if vr.improved:
            return FixOutcome(kind, True, attempt + 1, vr.before, vr.after, vr.detail, trace)

        # worse/flat -> undo and (maybe) retry looser
        await dispatcher.dispatch(ToolCall("undo", {}))
        trace.append({"attempt": attempt, "undo": True, "verify": vr.detail})

    return FixOutcome(
        kind, False, max_retries + 1, best_before, best_before,
        f"no improvement after {max_retries + 1} attempts", trace,
    )


async def flagship_floater_cleanup(
    dispatcher: ToolDispatcher,
    *,
    also_outliers: bool = True,
) -> dict:
    """The flagship loop (§7): read metrics -> rank regions -> fly+scan+marker+
    narrate -> snapshot+fix -> re-measure + before/after capture -> keep/undo ->
    report. Returns a structured, grounded summary."""
    channel = dispatcher.channel

    metrics0 = await _metrics(dispatcher)
    regions = (await dispatcher.dispatch(ToolCall("list_problem_regions", {}))).get("result", [])

    summary: dict = {"before": _key_fractions(metrics0), "regions": len(regions), "fixes": []}

    # Fly to the worst region and make it visible.
    if regions:
        top = regions[0]
        center = top.get("center") or _bbox_center(top)
        await channel.emit_event(ev_narrate(f"Inspecting worst region: {top.get('label', 'region')}"))
        await dispatcher.dispatch(ToolCall("look_at", {"target": center}))
        await dispatcher.dispatch(ToolCall("drop_marker", {"position": center, "label": top.get("label", "problem")}))
        await dispatcher.dispatch(ToolCall("scan_pause", {"ms": 800}))

    before_frames = (await dispatcher.dispatch(ToolCall("capture_frame", {}))).get("frames", [])

    floaters = await run_fix_verify(dispatcher, "floaters")
    summary["fixes"].append(_outcome_dict(floaters))
    if also_outliers:
        outliers = await run_fix_verify(dispatcher, "outliers")
        summary["fixes"].append(_outcome_dict(outliers))

    after_frames = (await dispatcher.dispatch(ToolCall("capture_frame", {}))).get("frames", [])
    metrics1 = await _metrics(dispatcher)

    summary["after"] = _key_fractions(metrics1)
    summary["captured_before"] = len(before_frames)
    summary["captured_after"] = len(after_frames)
    summary["kept_any"] = any(f["kept"] for f in summary["fixes"])
    return summary


# -- helpers --------------------------------------------------------------
_METRIC_PATH = {
    "opacity_threshold": "opacity.nearTransparentFraction",
    "remove_outliers": "spatial.outlierFraction",
    "prune_oversized": "scale.oversizedFraction",
    "remove_needles": "scale.axisRatio.needleFraction",
}


def _metric_path(tool: str) -> str:
    return _METRIC_PATH[tool]


def _dig(metrics: dict, path: str):
    cur = metrics
    for key in path.split("."):
        cur = cur[key]
    return cur


async def _metrics(dispatcher: ToolDispatcher) -> dict:
    return (await dispatcher.dispatch(ToolCall("get_metrics", {}))).get("result", {})


def _key_fractions(m: dict) -> dict:
    return {
        "gaussianCount": m.get("gaussianCount"),
        "nearTransparentFraction": m["opacity"]["nearTransparentFraction"],
        "outlierFraction": m["spatial"]["outlierFraction"],
        "oversizedFraction": m["scale"]["oversizedFraction"],
        "needleFraction": m["scale"]["axisRatio"]["needleFraction"],
    }


def _bbox_center(region: dict) -> list[float]:
    lo, hi = region.get("bbox_min", [0, 0, 0]), region.get("bbox_max", [0, 0, 0])
    return [(a + b) / 2 for a, b in zip(lo, hi)]


def _outcome_dict(o: FixOutcome) -> dict:
    return {
        "kind": o.kind,
        "kept": o.kept,
        "attempts": o.attempts,
        "before": o.before,
        "after": o.after,
        "detail": o.detail,
    }


__all__ = ["run_fix_verify", "flagship_floater_cleanup", "FixOutcome", "FIXES"]
