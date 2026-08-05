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
    """Expand the core box per-axis. A tight core box clips the subject's own
    outer shell; without padding that shell shows up as 'junk'."""
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


def cell_index(label: str, grid: int = 4) -> int:
    """'B3' -> row*grid+col. Columns A.. left->right, rows 1.. top->bottom."""
    if not isinstance(label, str) or len(label) < 2:
        raise ValueError(f"bad cell label: {label!r}")
    col = _LABELS.find(label[0].upper())
    try:
        row = int(label[1:]) - 1
    except ValueError:
        raise ValueError(f"bad cell label: {label!r}") from None
    if not (0 <= col < grid and 0 <= row < grid):
        raise ValueError(f"cell label out of range: {label!r}")
    return row * grid + col


def project_to_cells(means: np.ndarray, pose: dict, grid: int = 4) -> np.ndarray:
    """Project backend-space means through a render-space camera pose into
    grid-cell indices (-1 = behind camera / off screen).

    Backend coords are COLMAP Y-down; the viewer applies mesh.rotation.x = pi,
    so render = (x, -y, -z). The pose (position/target/fov/aspect) arrives in
    render space exactly as the frontend's survey_capture reports it.
    """
    pts = np.asarray(means, dtype=np.float64) * np.array([1.0, -1.0, -1.0])
    pos = np.asarray(pose["position"], dtype=np.float64)
    tgt = np.asarray(pose["target"], dtype=np.float64)
    fwd = tgt - pos
    n = np.linalg.norm(fwd)
    if n < 1e-9:
        return np.full(len(pts), -1, dtype=np.int64)
    fwd /= n
    up = np.array([0.0, 1.0, 0.0])
    if abs(float(fwd @ up)) > 0.99:          # top-down pose: pick a stable up
        up = np.array([0.0, 0.0, -1.0])
    right = np.cross(fwd, up)
    right /= np.linalg.norm(right)
    upv = np.cross(right, fwd)

    d = pts - pos
    x_c = d @ right
    y_c = d @ upv
    z_c = d @ fwd
    t = np.tan(np.radians(float(pose["fov"])) / 2.0)
    aspect = float(pose.get("aspect", 1.0)) or 1.0
    out = np.full(len(pts), -1, dtype=np.int64)
    vis = z_c > 1e-6
    with np.errstate(divide="ignore", invalid="ignore"):
        u = (x_c / (z_c * t * aspect) + 1.0) / 2.0
        v = (1.0 - y_c / (z_c * t)) / 2.0
    on = vis & (u >= 0) & (u < 1) & (v >= 0) & (v < 1)
    col = np.clip((u[on] * grid).astype(np.int64), 0, grid - 1)
    row = np.clip((v[on] * grid).astype(np.int64), 0, grid - 1)
    out[on] = row * grid + col
    return out


def resolve_marks(
    means: np.ndarray,
    opacity: np.ndarray,
    ids: np.ndarray,
    marks: list[dict],
    clusters: list[Cluster],
    core_min: np.ndarray,
    core_max: np.ndarray,
    *,
    grid: int = 4,
    min_splats: int = 30,
) -> list[Cluster]:
    """Merge model grid-marks with statistical clusters (spec §3 phase 3)."""
    off_core = _outside(means, core_min, core_max)
    ids_arr = np.asarray(ids)
    id_to_cluster: dict[int, Cluster] = {}
    for c in clusters:
        for i in c.ids:
            id_to_cluster[int(i)] = c

    spawned_ids: list[np.ndarray] = []
    for mark in marks:
        pose = mark.get("pose")
        cells = mark.get("cells") or []
        if not pose or not cells:
            continue
        cell_of = project_to_cells(means, pose, grid)
        for label in cells:
            try:
                target = cell_index(label, grid)
            except ValueError:
                continue                      # invalid label: dropped (spec §3 ph.2)
            in_cell = (cell_of == target) & off_core
            if not in_cell.any():
                continue                      # unresolved mark: costs nothing
            hit_ids = ids_arr[in_cell]
            hit_clusters = {id(c): c for i in hit_ids
                            if (c := id_to_cluster.get(int(i))) is not None}
            if hit_clusters:
                for c in hit_clusters.values():
                    c.mark_votes += 1
                    c.provenance = "both"
            elif len(hit_ids) >= min_splats:
                spawned_ids.append(np.sort(hit_ids))

    merged = list(clusters)
    core_center = (np.asarray(core_min) + np.asarray(core_max)) / 2.0
    pos_of = {int(i): k for k, i in enumerate(ids_arr)}
    for sid in spawned_ids:
        rows = np.asarray([pos_of[int(i)] for i in sid], dtype=np.int64)
        # dedup against clusters already spawned this pass
        if any(np.intersect1d(sid, m.ids).size > sid.size * 0.5 for m in merged):
            continue
        p = np.asarray(means)[rows]
        bmin, bmax = p.min(axis=0), p.max(axis=0)
        merged.append(Cluster(
            label="?", ids=sid,
            bbox_min=[float(v) for v in bmin], bbox_max=[float(v) for v in bmax],
            count=int(len(sid)),
            mean_opacity=float(np.asarray(opacity)[rows].mean()),
            extent=float(np.linalg.norm(bmax - bmin)),
            dist_from_core=float(np.linalg.norm(p.mean(axis=0) - core_center)),
            provenance="model", mark_votes=1,
        ))

    merged.sort(key=lambda c: c.count, reverse=True)
    for n, c in enumerate(merged):
        c.label = _LABELS[n % len(_LABELS)]
    return merged
