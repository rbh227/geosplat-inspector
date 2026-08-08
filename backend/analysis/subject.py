"""Subject lock-on for the cleanup run (subject-first cleanup, 2026-08-07).

Finds THE subject — the largest dense connected component of occupied
voxels — and returns nested keep-levels as strictness tiers: the tight end
cuts by voxel occupancy, the loose end dilates into surrounding occupied
voxels. Splats with extreme max-axis scale (streaks/needles) are excluded
from every level. Pure numpy, headless.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

from backend.analysis.clusters import core_box

_OFFSETS = [
    (dx, dy, dz)
    for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)
    if (dx, dy, dz) != (0, 0, 0)
]


@dataclass
class SubjectLevels:
    level_ids: list[np.ndarray]   # cumulative id sets, tight -> loose
    counts: list[int]
    default_level: int
    bbox_min: list[float]         # bbox of the default level (for framing)
    bbox_max: list[float]


def find_subject(
    means: np.ndarray,
    opacity: np.ndarray,
    ids: np.ndarray,
    *,
    cell_frac: float = 0.03,
    levels: int = 5,
    min_splats: int = 100,
    scales: np.ndarray | None = None,
    scale_cut_mult: float = 20.0,
) -> SubjectLevels | None:
    means = np.asarray(means, dtype=np.float64)
    ids = np.asarray(ids)
    if len(means) < min_splats:
        return None

    # Live-found (iona_park): streak/needle gaussians up to 2000x the median
    # scale sit with their CENTERS inside the dense core, so a center-only
    # test keeps them at every level and the slider can never remove them.
    # Splats with an extreme max-axis scale are excluded from the keep-set
    # outright (they land in the complement and die with the approval).
    if scales is not None:
        smax = np.asarray(scales, dtype=np.float64)
        if smax.ndim == 2:
            smax = smax.max(axis=1)
        ok = smax <= scale_cut_mult * float(np.median(smax))
        means, ids = means[ok], ids[ok]
        if len(means) < min_splats:
            return None

    # Live-found (iona_park, 2M splats): the raw bbox radius is inflated
    # ~1000x by a handful of far outliers, which makes the cell so large the
    # whole scene collapses into a few voxels and the "subject" swallows the
    # junk. Derive the scale from the median±MAD core box instead — the same
    # robust primitive find_clusters keys off.
    mn, mx = core_box(means)
    radius = float(np.linalg.norm(mx - mn)) / 2.0
    cell = max(radius * cell_frac, 1e-6)
    # A robust cell can undershoot sparse demo scenes (occupancy < 1
    # splat/voxel means NOTHING clears the dense threshold); grow it until
    # the dense core coheres. Bounded — a scene with no coherent core at any
    # of these scales genuinely has no subject.
    for _ in range(5):
        found = _subject_at_cell(means, ids, cell, levels=levels, min_splats=min_splats)
        if found is not None:
            return found
        cell *= 2.0
    return None


def _subject_at_cell(
    means: np.ndarray,
    ids: np.ndarray,
    cell: float,
    *,
    levels: int,
    min_splats: int,
) -> SubjectLevels | None:
    keys = np.floor(means / cell).astype(np.int64)

    buckets: dict[tuple[int, int, int], list[int]] = {}
    for i, k in enumerate(map(tuple, keys)):
        buckets.setdefault(k, []).append(i)

    # Dense = at least the mean occupancy (and >= 2): junk voxels are sparse.
    mean_occ = float(np.mean([len(v) for v in buckets.values()]))
    dense_min = max(2, int(round(mean_occ)))
    dense = {k for k, v in buckets.items() if len(v) >= dense_min}
    if not dense:
        return None

    # Largest dense connected component by SPLAT count (26-connectivity).
    seen: set[tuple[int, int, int]] = set()
    best: set[tuple[int, int, int]] = set()
    best_n = 0
    for start in dense:
        if start in seen:
            continue
        comp: set[tuple[int, int, int]] = set()
        q: deque[tuple[int, int, int]] = deque([start])
        seen.add(start)
        while q:
            v = q.popleft()
            comp.add(v)
            for off in _OFFSETS:
                nb = (v[0] + off[0], v[1] + off[1], v[2] + off[2])
                if nb in dense and nb not in seen:
                    seen.add(nb)
                    q.append(nb)
        n = sum(len(buckets[v]) for v in comp)
        if n > best_n:
            best, best_n = comp, n
    if best_n < min_splats:
        return None

    # Levels as STRICTNESS TIERS (live-found: dilation-only levels moved ~8%
    # of splats end to end on a real drone scene — an invisible slider).
    # The tight end cuts by voxel occupancy, the loose end grows by dilation:
    #   L0            = component voxels with occupancy >= 2x dense_min
    #   L1            = the component itself
    #   L2 (default)  = component dilated 2 steps into ANY occupied voxel —
    #                   identical to the previous default keep-set
    #   L3..Ln        = dilated 3, 4, ... steps
    hard = {v for v in best if len(buckets[v]) >= 2 * dense_min}
    if not hard:                     # uniformly-dense subject: no tighter cut
        hard = set(best)
    tiers: list[set[tuple[int, int, int]]] = [hard, set(best)]
    ring = set(best)
    for step in range(1, levels):
        grown = set(ring)
        for v in ring:
            for off in _OFFSETS:
                nb = (v[0] + off[0], v[1] + off[1], v[2] + off[2])
                if nb in buckets:
                    grown.add(nb)
        ring = grown
        if step >= 2:                # steps 2..levels-1 become the loose tiers
            tiers.append(set(ring))
    tiers = tiers[:levels]
    level_ids = [
        np.sort(ids[np.asarray(sorted(i for v in t for i in buckets[v]), dtype=np.int64)])
        for t in tiers
    ]

    default_level = levels // 2
    pos_of = {int(i): n for n, i in enumerate(ids)}
    rows = np.asarray([pos_of[int(i)] for i in level_ids[default_level]], dtype=np.int64)
    p = means[rows]
    return SubjectLevels(
        level_ids=level_ids,
        counts=[int(len(l)) for l in level_ids],
        default_level=default_level,
        bbox_min=[float(v) for v in p.min(axis=0)],
        bbox_max=[float(v) for v in p.max(axis=0)],
    )


__all__ = ["SubjectLevels", "find_subject"]
