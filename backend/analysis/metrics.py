"""Metrics engine (ARCHITECTURE.md §6.4) — reference-free, deterministic.

Computes every field of the ``Metrics`` schema from parameter-space statistics and
multi-view-independent spatial structure. No ground truth, no PSNR/SSIM.

R3 — the outlier criterion (``mean k-NN distance > mean + OUTLIER_STD_RATIO*std``) is
defined ONCE here, in :func:`outlier_mask`, and imported by the editing engine's
``remove_outliers``. It is never reimplemented elsewhere.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from backend.contracts.constants import (
    FLOATER_ALPHA,
    HIST_BINS,
    NEEDLE_RATIO,
    OUTLIER_K,
    OUTLIER_STD_RATIO,
    OVERSIZED_SCENE_FRAC,
    VISIBILITY_ALPHA,
)
from backend.contracts.metrics import Metrics
from backend.contracts.splat_model import SplatModel

# --------------------------------------------------------------------------- #
# The single outlier criterion (R3)
# --------------------------------------------------------------------------- #


def per_point_mean_knn(model: SplatModel, k: int = OUTLIER_K) -> np.ndarray:
    """Mean distance from each alive Gaussian to its ``k`` nearest neighbours.

    Returns a ``(M,)`` array in alive order (``M`` = alive count). Empty/degenerate
    scenes (``M <= k``) yield zeros so callers degrade gracefully.
    """
    m = int(model.alive.sum())
    if m <= k + 1:
        return np.zeros(max(m, 0), dtype=np.float32)
    dist, _ = model.knn(k)  # (M, k), self-match already dropped by the model
    return dist.mean(axis=1).astype(np.float32)


def outlier_mask(
    model: SplatModel,
    k: int = OUTLIER_K,
    std_ratio: float = OUTLIER_STD_RATIO,
) -> np.ndarray:
    """THE outlier predicate (R3). Boolean mask over the ALIVE subset.

    A Gaussian is an outlier when its mean k-NN distance exceeds
    ``global_mean + std_ratio * global_std`` of that statistic across the scene.
    """
    d = per_point_mean_knn(model, k)
    if d.size == 0:
        return np.zeros(0, dtype=bool)
    thresh = float(d.mean() + std_ratio * d.std())
    return d > thresh


def outlier_indices(
    model: SplatModel,
    k: int = OUTLIER_K,
    std_ratio: float = OUTLIER_STD_RATIO,
) -> np.ndarray:
    """Full-N Gaussian ids flagged as outliers by :func:`outlier_mask`."""
    return model.alive_indices()[outlier_mask(model, k, std_ratio)]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _hist(values: np.ndarray, bins: int, rng: tuple[float, float] | None = None) -> list[int]:
    if values.size == 0:
        return [0] * bins
    counts, _ = np.histogram(values, bins=bins, range=rng)
    return counts.astype(int).tolist()


def _axis_ratio(scale_xyz: np.ndarray) -> np.ndarray:
    """max-axis / min-axis per Gaussian (>= 1)."""
    if scale_xyz.shape[0] == 0:
        return np.zeros(0, dtype=np.float32)
    mx = scale_xyz.max(axis=1)
    mn = np.clip(scale_xyz.min(axis=1), 1e-12, None)
    return (mx / mn).astype(np.float32)


def _bbox_member_mask(pts: np.ndarray, region: dict) -> np.ndarray:
    mn = np.asarray(region["min"], dtype=np.float32)
    mx = np.asarray(region["max"], dtype=np.float32)
    return np.all((pts >= mn) & (pts <= mx), axis=1)


# --------------------------------------------------------------------------- #
# Full metrics
# --------------------------------------------------------------------------- #


def compute_metrics(model: SplatModel, region: dict | None = None) -> Metrics:
    """Compute the full :class:`Metrics` payload over alive Gaussians.

    ``region`` (a ``{"min": [3], "max": [3]}`` bbox) restricts every field to the
    alive Gaussians inside it; spatial statistics still use the global k-NN graph and
    are then subset to the region members.
    """
    alive_idx = model.alive_indices()
    alive_pts = model.means[alive_idx]

    # Scene-level diagonal (always whole scene) for the oversized normalisation.
    if alive_pts.shape[0] > 0:
        scene_min, scene_max = model.bounds()
        scene_diag = float(np.linalg.norm(scene_max - scene_min))
    else:
        scene_min = scene_max = np.zeros(3, dtype=np.float32)
        scene_diag = 0.0

    # Per-alive arrays (computed once, then subset by region).
    opacity = model.opacity(alive_only=True)            # (M,)
    scale_xyz = model.scale(alive_only=True)            # (M,3)
    f_dc = model.f_dc[alive_idx]                        # (M,3) raw DC
    nn_mean = per_point_mean_knn(model, OUTLIER_K)      # (M,)
    out_mask = outlier_mask(model, OUTLIER_K, OUTLIER_STD_RATIO)  # (M,)
    max_axis = scale_xyz.max(axis=1) if scale_xyz.shape[0] else np.zeros(0)
    ratio = _axis_ratio(scale_xyz)

    # Region subset (in alive order).
    if region is not None:
        member = _bbox_member_mask(alive_pts, region)
    else:
        member = np.ones(alive_pts.shape[0], dtype=bool)

    sel_pts = alive_pts[member]
    opacity = opacity[member]
    scale_xyz = scale_xyz[member]
    f_dc = f_dc[member]
    nn_mean = nn_mean[member] if nn_mean.size else nn_mean
    out_mask = out_mask[member] if out_mask.size else out_mask
    max_axis = max_axis[member] if max_axis.size else max_axis
    ratio = ratio[member] if ratio.size else ratio

    count = int(sel_pts.shape[0])
    oversize_thresh = OVERSIZED_SCENE_FRAC * scene_diag

    # bounds + volume of the selection
    if count > 0:
        bmin = sel_pts.min(axis=0)
        bmax = sel_pts.max(axis=0)
        volume = float(np.prod(np.clip(bmax - bmin, 0.0, None)))
    else:
        bmin = bmax = np.zeros(3, dtype=np.float32)
        volume = 0.0

    metrics: Metrics = {
        "gaussianCount": count,
        "opacity": {
            "histogram": _hist(opacity, HIST_BINS, (0.0, 1.0)),
            "nearTransparentFraction": float((opacity < VISIBILITY_ALPHA).mean()) if count else 0.0,
            "mean": float(opacity.mean()) if count else 0.0,
            "median": float(np.median(opacity)) if count else 0.0,
        },
        "scale": {
            "histogram": _hist(max_axis, HIST_BINS),
            "oversizedFraction": float((max_axis > oversize_thresh).mean()) if (count and scene_diag > 0) else 0.0,
            "axisRatio": {
                "histogram": _hist(ratio, HIST_BINS),
                "needleFraction": float((ratio > NEEDLE_RATIO).mean()) if count else 0.0,
            },
        },
        "spatial": {
            "nnDistance": {
                "mean": float(nn_mean.mean()) if nn_mean.size else 0.0,
                "std": float(nn_mean.std()) if nn_mean.size else 0.0,
                "histogram": _hist(nn_mean, HIST_BINS),
            },
            "outlierFraction": float(out_mask.mean()) if out_mask.size else 0.0,
            "density": float(count / volume) if volume > 0 else 0.0,
        },
        "bounds": {
            "min": [float(x) for x in bmin],
            "max": [float(x) for x in bmax],
            "volume": volume,
        },
        "color": {
            "dcMean": [float(x) for x in f_dc.mean(axis=0)] if count else [0.0, 0.0, 0.0],
            "dcStd": [float(x) for x in f_dc.std(axis=0)] if count else [0.0, 0.0, 0.0],
        },
        "computedAt": datetime.now(timezone.utc).isoformat(),
        "region": region,
    }
    return metrics


# --------------------------------------------------------------------------- #
# Problem-region ranking
# --------------------------------------------------------------------------- #


def list_problem_regions(
    model: SplatModel,
    grid: int = 6,
    top_k: int = 8,
) -> list[dict]:
    """Voxelize the scene and rank cells by composite badness.

    Badness for a cell = count of Gaussians that are floaters (low opacity),
    spatial outliers, needles, or oversized. Returns up to ``top_k`` cells, each with
    a tight bbox of its members, the composite score, and a per-category breakdown.
    """
    alive_idx = model.alive_indices()
    pts = model.means[alive_idx]
    n = pts.shape[0]
    if n == 0:
        return []

    opacity = model.opacity(alive_only=True)
    scale_xyz = model.scale(alive_only=True)
    ratio = _axis_ratio(scale_xyz)
    max_axis = scale_xyz.max(axis=1)

    scene_min, scene_max = model.bounds()
    scene_diag = float(np.linalg.norm(scene_max - scene_min))
    oversize_thresh = OVERSIZED_SCENE_FRAC * scene_diag

    is_floater = opacity < FLOATER_ALPHA
    is_outlier = outlier_mask(model, OUTLIER_K, OUTLIER_STD_RATIO)
    is_needle = ratio > NEEDLE_RATIO
    is_oversized = max_axis > oversize_thresh if scene_diag > 0 else np.zeros(n, dtype=bool)
    bad = is_floater | is_outlier | is_needle | is_oversized

    # Assign each point to a voxel.
    span = np.clip(scene_max - scene_min, 1e-9, None)
    vox = np.floor((pts - scene_min) / span * grid).astype(int)
    vox = np.clip(vox, 0, grid - 1)
    keys = vox[:, 0] * grid * grid + vox[:, 1] * grid + vox[:, 2]

    regions: list[dict] = []
    for key in np.unique(keys):
        cell = keys == key
        bad_cell = bad & cell
        bad_count = int(bad_cell.sum())
        if bad_count == 0:
            continue
        cpts = pts[cell]
        regions.append({
            "bbox": {
                "min": [float(x) for x in cpts.min(axis=0)],
                "max": [float(x) for x in cpts.max(axis=0)],
            },
            "gaussianCount": int(cell.sum()),
            "score": float(bad_count / int(cell.sum())),
            "badCount": bad_count,
            "breakdown": {
                "floaters": int((is_floater & cell).sum()),
                "outliers": int((is_outlier & cell).sum()),
                "needles": int((is_needle & cell).sum()),
                "oversized": int((is_oversized & cell).sum()),
            },
        })

    # Rank by absolute problem count, then by fraction.
    regions.sort(key=lambda r: (r["badCount"], r["score"]), reverse=True)
    return regions[:top_k]
