"""Junk-cluster detection + grid-mark resolution for the judgment-tour
cleanup (spec 2026-08-04-judgment-tour-cleanup-design.md).

Pure numpy over plain arrays: `means` are backend-space (COLMAP Y-down)
positions of ALIVE splats, `ids` the matching original splat ids (the
stable ID space shared with the frontend). No model, no torch, no scipy
imports beyond numpy — headlessly testable.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np

_LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


@dataclass
class Cluster:
    label: str
    ids: np.ndarray                      # original splat ids (int64)
    bbox_min: list[float]
    bbox_max: list[float]
    count: int
    mean_opacity: float
    extent: float                        # bbox diagonal length
    dist_from_core: float                # centroid distance to core-box center
    provenance: str = "stats"            # "stats" | "model" | "both"
    # transient: cell votes accumulated during mark resolution
    mark_votes: int = field(default=0, compare=False)


def core_box(means: np.ndarray, k: float = 6.0) -> tuple[np.ndarray, np.ndarray]:
    """Robust per-axis core: median ± k·MAD.

    A percentile box fails when junk is heavy along one axis (a long floater
    trail drags the 95th percentile INTO the junk); median/MAD stays anchored
    to the dense subject for up to ~50% contamination per axis.
    """
    med = np.median(means, axis=0)
    mad = np.median(np.abs(means - med), axis=0)
    half = np.maximum(k * mad, 1e-6)
    return (med - half).astype(np.float64), (med + half).astype(np.float64)


def _padded(core_min: np.ndarray, core_max: np.ndarray, pad_frac: float) -> tuple[np.ndarray, np.ndarray]:
    """Expand the core box per-axis. The percentile box clips the subject's own
    outer shell (5% per tail); without padding that shell shows up as 'junk'."""
    pad = (np.asarray(core_max) - np.asarray(core_min)) * pad_frac
    return np.asarray(core_min) - pad, np.asarray(core_max) + pad


def _outside(
    means: np.ndarray,
    core_min: np.ndarray,
    core_max: np.ndarray,
    pad_frac: float = 0.25,
) -> np.ndarray:
    mn, mx = _padded(core_min, core_max, pad_frac)
    inside = ((means >= mn) & (means <= mx)).all(axis=1)
    return ~inside


def find_clusters(
    means: np.ndarray,
    opacity: np.ndarray,
    ids: np.ndarray,
    core_min: np.ndarray,
    core_max: np.ndarray,
    *,
    cell_frac: float = 0.03,
    min_splats: int = 30,
    max_clusters: int = 12,
) -> list[Cluster]:
    """Voxel-grid connected components (26-connectivity) over off-core splats."""
    mask = _outside(means, core_min, core_max)
    if not mask.any():
        return []
    pts = means[mask]
    sub_opacity = opacity[mask]
    sub_ids = np.asarray(ids)[mask]

    scene_radius = float(np.linalg.norm(means.max(axis=0) - means.min(axis=0))) / 2.0
    cell = max(scene_radius * cell_frac, 1e-6)
    keys = np.floor(pts / cell).astype(np.int64)

    # voxel -> point indices
    buckets: dict[tuple[int, int, int], list[int]] = {}
    for i, k in enumerate(map(tuple, keys)):
        buckets.setdefault(k, []).append(i)

    # BFS over occupied voxels, 26-connected
    offsets = [
        (dx, dy, dz)
        for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)
        if (dx, dy, dz) != (0, 0, 0)
    ]
    seen: set[tuple[int, int, int]] = set()
    components: list[list[int]] = []
    for start in buckets:
        if start in seen:
            continue
        comp: list[int] = []
        q: deque[tuple[int, int, int]] = deque([start])
        seen.add(start)
        while q:
            v = q.popleft()
            comp.extend(buckets[v])
            for off in offsets:
                nb = (v[0] + off[0], v[1] + off[1], v[2] + off[2])
                if nb in buckets and nb not in seen:
                    seen.add(nb)
                    q.append(nb)
        if len(comp) >= min_splats:
            components.append(comp)

    components.sort(key=len, reverse=True)
    components = components[:max_clusters]

    core_center = (core_min + core_max) / 2.0
    out: list[Cluster] = []
    for n, comp in enumerate(components):
        idx = np.asarray(comp, dtype=np.int64)
        p = pts[idx]
        bmin, bmax = p.min(axis=0), p.max(axis=0)
        out.append(Cluster(
            label=_LABELS[n],
            ids=np.sort(sub_ids[idx]),
            bbox_min=[float(v) for v in bmin],
            bbox_max=[float(v) for v in bmax],
            count=int(len(idx)),
            mean_opacity=float(sub_opacity[idx].mean()),
            extent=float(np.linalg.norm(bmax - bmin)),
            dist_from_core=float(np.linalg.norm(p.mean(axis=0) - core_center)),
        ))
    return out
