# Judgment-Tour Cleanup Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the freeform Clean-stage `cleanup_scene` run with an app-owned `CleanupController` (crop → survey & mark → lock-in → judgment tour → one batch proposal → scripted summary) whose only model interactions are single forced-choice calls a weak local VLM can answer.

**Architecture:** A Python phase controller (`backend/agent/cleanup_controller.py`) drives the existing `ToolDispatcher`/`WSChannel`/executor plumbing directly — the model never picks tools, sequences steps, or emits coordinates. New pure-numpy analysis (`backend/analysis/clusters.py`) finds junk clusters and resolves grid-cell marks into 3D candidates. The spec is `docs/superpowers/specs/2026-08-04-judgment-tour-cleanup-design.md`.

**Tech Stack:** Python 3.12 (FastAPI backend, numpy), TypeScript/React frontend (Vite), pytest, vitest.

## Global Constraints

- Backend needs Python 3.12 (`.venv-api`); run backend tests with `pytest` from repo root.
- Frontend type-check is `npx tsc -b` (NEVER `tsc --noEmit` — solution-style tsconfig makes it a no-op); lint with `npm run lint`; contract drift guard is `frontend/src/agent/contracts.test.ts` (vitest) + `backend/contracts/tests/test_tools.py`.
- Contract rule: `backend/contracts/tools.py` and `frontend/src/contracts.ts` change TOGETHER, additions only, with a version-note comment bump (this plan is the v0.7 addition set).
- Caps (spec §6, copy verbatim): 6 survey frames, 4×4 grid, 12 toured candidates, 1 `look_closer` per candidate, 1 retry per model call, 45 s per-call timeout, 3 adjust rounds per proposal.
- Safe defaults: any model failure → `unsure` → treated as KEEP; the run must always reach the batch card and the summary.
- Cell-label convention (both sides MUST match): 4×4 grid, columns `A–D` left→right, rows `1–4` top→bottom, label = column letter + row number (e.g. `B3`); `u∈[0,1)` left→right, `v∈[0,1)` top→bottom, `col = floor(u*4)`, `row = floor(v*4)`.
- Every destructive engine call in the controller: `snapshot()` first, `get_metrics` before/after, `silhouette_intact(before, after, approved=True)`, `undo()` on failure.
- Commit after every task with a conventional-commit message ending in the standard co-author trailer used in this repo.

---

### Task 1: Cluster detection (`clusters.py` — core box, voxel clusters, stats)

**Files:**
- Create: `backend/analysis/clusters.py`
- Create: `backend/analysis/tests/test_clusters.py`
- Modify: `backend/analysis/__init__.py` (export the new functions)

**Interfaces:**
- Consumes: `backend.splat.GaussianSplatModel` fields only indirectly — all functions take plain numpy arrays so tests never need a real model.
- Produces (later tasks rely on these exact signatures):
  - `@dataclass Cluster: label:str, ids:np.ndarray (original splat ids, int64), bbox_min:list[float], bbox_max:list[float], count:int, mean_opacity:float, extent:float, dist_from_core:float, provenance:str` (`"stats" | "model" | "both"`)
  - `core_box(means: np.ndarray, lo_pct: float = 5.0, hi_pct: float = 95.0) -> tuple[np.ndarray, np.ndarray]`
  - `find_clusters(means, opacity, ids, core_min, core_max, *, cell_frac: float = 0.03, min_splats: int = 30, max_clusters: int = 12) -> list[Cluster]`

- [ ] **Step 1: Write the failing tests**

```python
# backend/analysis/tests/test_clusters.py
"""Cluster detection for the judgment-tour cleanup (spec 2026-08-04).

Pure-array API: no GaussianSplatModel needed. Layout used throughout:
a dense unit-cube "building" at the origin plus small far-away blobs.
"""
from __future__ import annotations

import numpy as np

from backend.analysis.clusters import Cluster, core_box, find_clusters


def _building(n=2000, seed=0):
    rng = np.random.default_rng(seed)
    return rng.uniform(-0.5, 0.5, size=(n, 3))


def _blob(center, n=60, spread=0.05, seed=1):
    rng = np.random.default_rng(seed)
    return np.asarray(center) + rng.normal(0, spread, size=(n, 3))


def _scene(blobs):
    parts = [_building()] + list(blobs)
    means = np.vstack(parts)
    opacity = np.full(len(means), 0.8)
    ids = np.arange(len(means), dtype=np.int64)
    return means, opacity, ids


def test_core_box_covers_the_dense_building():
    means, _, _ = _scene([_blob([10, 0, 0])])
    mn, mx = core_box(means)
    # the 5th-95th pct box hugs the building, not the far blob
    assert mx[0] < 2.0
    assert mn[0] > -2.0


def test_find_clusters_finds_far_blobs_and_skips_core():
    means, opacity, ids = _scene([_blob([10, 0, 0], n=80, seed=1),
                                  _blob([0, 12, 0], n=50, seed=2)])
    mn, mx = core_box(means)
    clusters = find_clusters(means, opacity, ids, mn, mx)
    assert len(clusters) == 2
    # labels are A, B ... ordered by splat count desc
    assert [c.label for c in clusters] == ["A", "B"]
    assert clusters[0].count >= clusters[1].count
    # ids are original splat ids outside the core
    building_n = 2000
    for c in clusters:
        assert (c.ids >= building_n).all()
    assert all(c.provenance == "stats" for c in clusters)


def test_min_splats_floor_drops_dust():
    means, opacity, ids = _scene([_blob([10, 0, 0], n=5, seed=3)])
    mn, mx = core_box(means)
    assert find_clusters(means, opacity, ids, mn, mx, min_splats=30) == []


def test_max_clusters_cap_keeps_biggest():
    blobs = [_blob([8 + 3 * i, 0, 0], n=40 + i, seed=10 + i) for i in range(15)]
    means, opacity, ids = _scene(blobs)
    mn, mx = core_box(means)
    clusters = find_clusters(means, opacity, ids, mn, mx, max_clusters=12)
    assert len(clusters) == 12
    counts = [c.count for c in clusters]
    assert counts == sorted(counts, reverse=True)


def test_cluster_stats_populated():
    means, opacity, ids = _scene([_blob([10, 0, 0])])
    mn, mx = core_box(means)
    (c,) = find_clusters(means, opacity, ids, mn, mx)
    assert c.count == len(c.ids)
    assert 0.0 < c.mean_opacity <= 1.0
    assert c.extent > 0
    assert c.dist_from_core > 5.0
    assert len(c.bbox_min) == 3 and len(c.bbox_max) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/analysis/tests/test_clusters.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.analysis.clusters'`

- [ ] **Step 3: Implement `clusters.py` (detection half)**

```python
# backend/analysis/clusters.py
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
    # transient: cell votes accumulated during mark resolution (Task 2)
    mark_votes: int = field(default=0, compare=False)


def core_box(
    means: np.ndarray, lo_pct: float = 5.0, hi_pct: float = 95.0
) -> tuple[np.ndarray, np.ndarray]:
    """Robust per-axis percentile box — the dense subject, floaters excluded."""
    mn = np.percentile(means, lo_pct, axis=0)
    mx = np.percentile(means, hi_pct, axis=0)
    return np.asarray(mn, dtype=np.float64), np.asarray(mx, dtype=np.float64)


def _outside(means: np.ndarray, core_min: np.ndarray, core_max: np.ndarray) -> np.ndarray:
    inside = ((means >= core_min) & (means <= core_max)).all(axis=1)
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
```

- [ ] **Step 4: Export from `backend/analysis/__init__.py`**

Add to the existing exports (match the file's current style):

```python
from .clusters import Cluster, core_box, find_clusters
```

and extend `__all__` with `"Cluster", "core_box", "find_clusters"`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest backend/analysis/tests/test_clusters.py -v`
Expected: 5 PASS

- [ ] **Step 6: Run the full analysis suite (no regressions)**

Run: `pytest backend/analysis/ -q`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add backend/analysis/clusters.py backend/analysis/tests/test_clusters.py backend/analysis/__init__.py
git commit -m "feat(analysis): junk-cluster detection for judgment-tour cleanup"
```

---

### Task 2: Camera projection + mark resolution (`clusters.py` part 2)

**Files:**
- Modify: `backend/analysis/clusters.py`
- Modify: `backend/analysis/tests/test_clusters.py`
- Modify: `backend/analysis/__init__.py`

**Interfaces:**
- Consumes: `Cluster`, `core_box`, `find_clusters` from Task 1.
- Produces:
  - `project_to_cells(means: np.ndarray, pose: dict, grid: int = 4) -> np.ndarray` — per-splat cell index in `[0, grid*grid)` or `-1` when off-screen/behind. `pose = {"position":[x,y,z], "target":[x,y,z], "fov": degrees_vertical, "aspect": w/h}` in **render space** (Three.js Y-up; backend means are converted internally via `(x,-y,-z)`).
  - `cell_index(label: str, grid: int = 4) -> int` — `"B3"` → `row*grid+col` = `2*4+1 = 9`; raises `ValueError` on bad labels.
  - `resolve_marks(means, opacity, ids, marks: list[dict], clusters: list[Cluster], core_min, core_max, *, grid: int = 4, min_splats: int = 30) -> list[Cluster]` — `marks = [{"cells": ["B3", ...], "pose": {...}}, ...]` (one entry per survey frame). Returns the merged candidate list: statistical clusters get `provenance="both"` and `mark_votes` when hit; unmatched marks that resolve to ≥`min_splats` off-core splats spawn new `provenance="model"` clusters; ordering count-desc, relabeled `A, B, C…`, still capped at 12 by the caller (controller).

- [ ] **Step 1: Write the failing tests (append to test_clusters.py)**

```python
from backend.analysis.clusters import cell_index, project_to_cells, resolve_marks


def _pose_looking_at_origin(position=(0, 0, 10)):
    return {"position": list(position), "target": [0, 0, 0], "fov": 60.0, "aspect": 1.0}


def test_cell_index_convention():
    assert cell_index("A1") == 0          # top-left
    assert cell_index("D1") == 3          # top-right
    assert cell_index("A4") == 12         # bottom-left
    assert cell_index("B3") == 9          # row 3 (index 2) * 4 + col B (index 1)
    import pytest
    with pytest.raises(ValueError):
        cell_index("E1")
    with pytest.raises(ValueError):
        cell_index("A9")


def test_project_center_point_lands_in_middle_cells():
    # backend point at origin, camera on render +Z axis looking at origin:
    # backend (0,0,0) -> render (0,0,0) -> screen center -> cell B2 or C2/B3/C3 edge.
    means = np.array([[0.0, 0.0, 0.0]])
    cells = project_to_cells(means, _pose_looking_at_origin(), grid=4)
    assert cells[0] in (cell_index("B2"), cell_index("C2"), cell_index("B3"), cell_index("C3"))


def test_project_behind_camera_is_minus_one():
    means = np.array([[0.0, 0.0, 0.0]])
    pose = {"position": [0, 0, -10], "target": [0, 0, -20], "fov": 60.0, "aspect": 1.0}
    assert project_to_cells(means, pose)[0] == -1


def test_render_space_flip_is_applied():
    # backend Y-down: backend (0, -1, 0) is render (0, +1, 0) = UPPER half of the
    # screen for a camera at render +Z looking at origin -> row 1 or 2, not 3/4.
    means = np.array([[0.0, -3.0, 0.0]])
    cells = project_to_cells(means, _pose_looking_at_origin(), grid=4)
    assert cells[0] != -1
    assert cells[0] // 4 <= 1   # top half


def test_resolve_marks_boosts_hit_cluster_and_spawns_model_cluster():
    # scene: building + one far blob (statistical cluster) + one MIST patch that
    # voxel clustering missed (too sparse) but the model marks.
    mist = _blob([0, 0, 6], n=40, spread=1.2, seed=7)   # sparse -> no stats cluster
    far = _blob([10, 0, 0], n=80, seed=8)
    means, opacity, ids = _scene([far, mist])
    mn, mx = core_box(means)
    stats = find_clusters(means, opacity, ids, mn, mx, min_splats=50)
    assert len(stats) == 1                               # only the far blob

    # camera that sees the far blob: at render-space (10, 0, 8) looking at it.
    pose_far = {"position": [10, 0, 8], "target": [10, 0, 0], "fov": 60.0, "aspect": 1.0}
    far_cells = project_to_cells(means, pose_far)
    far_mask = np.zeros(len(means), bool)
    far_mask[2000:2080] = True                           # the far blob rows
    hit_cell = np.bincount(far_cells[far_mask][far_cells[far_mask] >= 0]).argmax()
    col, row = int(hit_cell % 4), int(hit_cell // 4)
    far_label = "ABCD"[col] + str(row + 1)

    # camera that sees the mist: mist sits at backend (0,0,6) = render (0,0,-6).
    pose_mist = {"position": [0, 0, -12], "target": [0, 0, -6], "fov": 60.0, "aspect": 1.0}
    mist_cells = project_to_cells(means, pose_mist)
    mist_mask = np.zeros(len(means), bool)
    mist_mask[2080:2120] = True
    mc = np.bincount(mist_cells[mist_mask][mist_cells[mist_mask] >= 0]).argmax()
    mist_label = "ABCD"[int(mc % 4)] + str(int(mc // 4) + 1)

    merged = resolve_marks(
        means, opacity, ids,
        [{"cells": [far_label], "pose": pose_far},
         {"cells": [mist_label], "pose": pose_mist}],
        stats, mn, mx, min_splats=20,
    )
    provs = sorted(c.provenance for c in merged)
    assert provs == ["both", "model"]
    # relabeled alphabetically by size desc
    assert [c.label for c in merged] == ["A", "B"]


def test_resolve_marks_ignores_unresolvable_cells():
    means, opacity, ids = _scene([_blob([10, 0, 0], n=80, seed=9)])
    mn, mx = core_box(means)
    stats = find_clusters(means, opacity, ids, mn, mx)
    # A1 with a camera staring at empty sky resolves to nothing.
    pose = {"position": [0, 50, 200], "target": [0, 50, 199], "fov": 60.0, "aspect": 1.0}
    merged = resolve_marks(means, opacity, ids, [{"cells": ["A1"], "pose": pose}],
                           stats, mn, mx)
    assert len(merged) == len(stats)
    assert merged[0].provenance == "stats"
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `pytest backend/analysis/tests/test_clusters.py -v -k "cell or project or resolve"`
Expected: FAIL with `ImportError: cannot import name 'cell_index'`

- [ ] **Step 3: Implement projection + resolution (append to clusters.py)**

```python
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
            hit_clusters = {id_to_cluster[int(i)] for i in hit_ids if int(i) in id_to_cluster}
            if hit_clusters:
                for c in hit_clusters:
                    c.mark_votes += 1
                    c.provenance = "both"
            elif len(hit_ids) >= min_splats:
                spawned_ids.append(np.sort(hit_ids))

    merged = list(clusters)
    core_center = (core_min + core_max) / 2.0
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
```

- [ ] **Step 4: Export the new names**

In `backend/analysis/__init__.py` extend the clusters import/`__all__` with `cell_index, project_to_cells, resolve_marks`.

- [ ] **Step 5: Run the full test file**

Run: `pytest backend/analysis/tests/test_clusters.py -v`
Expected: all PASS (Task 1's five + the six new ones)

- [ ] **Step 6: Commit**

```bash
git add backend/analysis/clusters.py backend/analysis/tests/test_clusters.py backend/analysis/__init__.py
git commit -m "feat(analysis): grid-cell projection and mark resolution for cleanup tour"
```

---

### Task 3: Contracts v0.7 additions (both mirrors + drift guards)

**Files:**
- Modify: `backend/contracts/tools.py`
- Modify: `frontend/src/contracts.ts`
- Modify: `backend/contracts/tests/test_tools.py`
- Modify: `frontend/src/agent/contracts.test.ts`

**Interfaces:**
- Produces:
  - New `ToolEntry("select_by_ids", "frontend", …)` — tint/select exact stable ids (controller-dispatched; routed as `selection_tool`).
  - `propose_decision` kinds enum gains `"delete_clusters"`; params gain optional `clusters` array (rows `{label, count, verdict, reason, provenance}`).
  - `CONTROLLER_CHOICE_SPECS: dict[str, dict]` — the two forced-choice tool schemas (`mark_noise`, `judge_candidate`) the controller offers the model. They are NOT registry entries (never dispatched).
  - TS mirror: `CLUSTER_ROW_FIELDS`, `ClusterRow` type, same kinds enum addition.

- [ ] **Step 1: Extend the failing drift tests first**

In `backend/contracts/tests/test_tools.py` add:

```python
def test_v07_select_by_ids_registered():
    from backend.contracts.tools import TOOL_BY_NAME
    entry = TOOL_BY_NAME["select_by_ids"]
    assert entry.runs_on == "frontend"
    props = entry.params["properties"]
    assert props["ids"]["type"] == "array"
    assert set(entry.params["required"]) == {"ids"}


def test_v07_delete_clusters_kind():
    from backend.contracts.tools import TOOL_BY_NAME
    kinds = TOOL_BY_NAME["propose_decision"].params["properties"]["kind"]["enum"]
    assert "delete_clusters" in kinds
    props = TOOL_BY_NAME["propose_decision"].params["properties"]
    assert "clusters" in props


def test_v07_controller_choice_specs():
    from backend.contracts.tools import CONTROLLER_CHOICE_SPECS
    mark = CONTROLLER_CHOICE_SPECS["mark_noise"]
    judge = CONTROLLER_CHOICE_SPECS["judge_candidate"]
    assert mark["parameters"]["properties"]["cells"]["items"]["type"] == "string"
    verdicts = judge["parameters"]["properties"]["verdict"]["enum"]
    assert verdicts == ["junk", "structure", "look_closer"]
```

In `frontend/src/agent/contracts.test.ts` add (match the file's existing style of asserting names/enums):

```typescript
it('v0.7: select_by_ids + delete_clusters kind + cluster row fields', () => {
  expect(FRONTEND_TOOLS).toContain('select_by_ids')
  expect(PROPOSAL_KINDS).toContain('delete_clusters')
  expect(CLUSTER_ROW_FIELDS).toEqual(['label', 'count', 'verdict', 'reason', 'provenance'])
})
```

(If `PROPOSAL_KINDS` does not yet exist as an exported constant in `contracts.ts`, add it in Step 3 and mirror a `PROPOSAL_KINDS` tuple in `tools.py`; keep both drift tests asserting the same list.)

- [ ] **Step 2: Run both to verify failure**

Run: `pytest backend/contracts/tests/test_tools.py -q` → FAIL (KeyError `select_by_ids`)
Run: `cd frontend && npx vitest run src/agent/contracts.test.ts` → FAIL

- [ ] **Step 3: Apply the backend contract changes**

In `backend/contracts/tools.py`:

1. Docstring version note: append `v0.7 adds select_by_ids (controller tint), the delete_clusters proposal kind + clusters payload, and CONTROLLER_CHOICE_SPECS (forced-choice schemas for the judgment-tour cleanup controller — never dispatched).`
2. After the `get_selection_state` entry add:

```python
    # v0.7 — controller tint: select EXACT stable ids (judgment-tour cleanup).
    # Dispatched by the CleanupController only; never offered to the model.
    ToolEntry("select_by_ids", "frontend", {
        "type": "object",
        "properties": {
            "ids": {"type": "array", "items": {"type": "integer"},
                    "description": "Stable splat ids to select"},
            "mode": {"type": "string", "enum": ["add", "remove", "replace"]},
        },
        "required": ["ids"],
    }, "{count, bbox}"),
```

3. In the `propose_decision` entry: add `"delete_clusters"` to the `kind` enum, and add to `properties`:

```python
            "clusters": {
                "type": "array",
                "description": "delete_clusters only: the reviewed rows",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "count": {"type": "integer"},
                        "verdict": {"type": "string",
                                    "enum": ["junk", "structure", "unsure"]},
                        "reason": {"type": "string"},
                        "provenance": {"type": "string",
                                       "enum": ["stats", "model", "both"]},
                    },
                    "required": ["label", "count", "verdict"],
                },
            },
```

4. Near `PROPOSAL_DECISION_FIELDS` add:

```python
# v0.7 — forced-choice schemas for the CleanupController. These are provider
# ToolSpec dicts (name/description/parameters), NOT registry entries: the
# controller offers exactly one of them per model call and dispatches nothing.
CONTROLLER_CHOICE_SPECS: dict[str, dict] = {
    "mark_noise": {
        "name": "mark_noise",
        "description": "Mark grid cells that contain floating junk, debris "
                       "mist, or disconnected fragments. Empty list if none.",
        "parameters": {
            "type": "object",
            "properties": {
                "cells": {"type": "array", "items": {"type": "string"},
                          "description": "Cell labels like B3 (columns A-D, rows 1-4)"},
                "note": {"type": "string"},
            },
            "required": ["cells"],
        },
    },
    "judge_candidate": {
        "name": "judge_candidate",
        "description": "Judge the highlighted cluster.",
        "parameters": {
            "type": "object",
            "properties": {
                "verdict": {"type": "string",
                            "enum": ["junk", "structure", "look_closer"]},
                "reason": {"type": "string", "description": "One short sentence"},
            },
            "required": ["verdict", "reason"],
        },
    },
}
```

5. Export `CONTROLLER_CHOICE_SPECS` in `__all__` (and `PROPOSAL_KINDS` if introduced — a tuple sourced from the enum so the two can't drift).

- [ ] **Step 4: Mirror in `frontend/src/contracts.ts`**

Follow the file's existing structure (read it first; it mirrors names/enums, not JSON Schema). Add: `'select_by_ids'` to the frontend tool name list, `'delete_clusters'` to the proposal kinds, and:

```typescript
/** v0.7 — judgment-tour batch proposal rows (mirror: tools.py clusters items). */
export const CLUSTER_ROW_FIELDS = ['label', 'count', 'verdict', 'reason', 'provenance'] as const
export interface ClusterRow {
  label: string
  count: number
  verdict: 'junk' | 'structure' | 'unsure'
  reason?: string
  provenance?: 'stats' | 'model' | 'both'
}
```

- [ ] **Step 5: Run both drift guards**

Run: `pytest backend/contracts/tests/ -q` → PASS
Run: `cd frontend && npx vitest run src/agent/contracts.test.ts` → PASS
Run: `npx tsc -b` (from repo root or frontend per repo setup) → clean

- [ ] **Step 6: Commit**

```bash
git add backend/contracts/tools.py frontend/src/contracts.ts backend/contracts/tests/test_tools.py frontend/src/agent/contracts.test.ts
git commit -m "feat(contracts): v0.7 judgment-tour additions (select_by_ids, delete_clusters, choice specs)"
```

---

### Task 4: Frontend executors — `select_by_ids`, survey poses, grid overlay

**Files:**
- Modify: `frontend/src/agent/executors.ts`
- Modify: `frontend/src/agent/capture.ts`
- Test: `frontend/src/agent/capture.test.ts` (create if absent; the repo already runs vitest for `contracts.test.ts`)

**Interfaces:**
- Consumes: `RendererBridge.updateSelection(ids, mode)`, `bridge.clearSelection()`, `bridge.getSelectionSummary()`, `capturePNG`, `surveyPoses`, `animateTo` (all existing).
- Produces:
  - `runSelectionTool('select_by_ids', {ids, mode})` → `{ok, count, bbox}`; `mode:'replace'` = clear then add.
  - `survey_capture` reply gains `poses: Array<{position:[number,number,number], target:[…], fov:number, aspect:number}>` (render space, one per frame, index-aligned with `frames_base64`) and accepts `args.grid?: boolean` to burn the 4×4 labeled grid into each frame.
  - `capture.ts`: `export function drawGridOverlay(canvas: HTMLCanvasElement, grid = 4): void` and `capturePNG(bridge, opts?: {grid?: boolean})`.

- [ ] **Step 1: Write the failing test for the overlay + cell convention**

```typescript
// frontend/src/agent/capture.test.ts
import { describe, expect, it } from 'vitest'
import { drawGridOverlay } from './capture.ts'

describe('drawGridOverlay', () => {
  it('draws 4x4 labels A1..D4 with column letters left-to-right, rows top-to-bottom', () => {
    const canvas = document.createElement('canvas')
    canvas.width = 400
    canvas.height = 400
    const drawn: Array<{ text: string; x: number; y: number }> = []
    const ctx = canvas.getContext('2d')!
    const orig = ctx.fillText.bind(ctx)
    ctx.fillText = (text: string, x: number, y: number) => { drawn.push({ text, x, y }); orig(text, x, y) }
    drawGridOverlay(canvas)
    expect(drawn).toHaveLength(16)
    const a1 = drawn.find(d => d.text === 'A1')!
    const d4 = drawn.find(d => d.text === 'D4')!
    expect(a1.x).toBeLessThan(100)   // col A = leftmost quarter
    expect(a1.y).toBeLessThan(100)   // row 1 = top quarter
    expect(d4.x).toBeGreaterThan(300)
    expect(d4.y).toBeGreaterThan(300)
  })
})
```

(vitest here needs a DOM: if the config doesn't already use jsdom/happy-dom for this folder, add `// @vitest-environment jsdom` as the first line of the test file.)

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/agent/capture.test.ts`
Expected: FAIL — `drawGridOverlay` is not exported

- [ ] **Step 3: Implement**

In `capture.ts` add (and thread an optional `opts` through `capturePNG` so the overlay draws onto the captured canvas before `toBlob`; follow the existing capture pipeline — overlay must apply to the copy being encoded, never the live renderer canvas):

```typescript
/** Burn a labeled grid into a capture (cells A1..D4; cols A-D left→right,
 *  rows 1-4 top→bottom — MUST match backend/analysis/clusters.cell_index). */
export function drawGridOverlay(canvas: HTMLCanvasElement, grid = 4): void {
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  const w = canvas.width, h = canvas.height
  ctx.save()
  ctx.strokeStyle = 'rgba(255,255,255,0.7)'
  ctx.lineWidth = Math.max(1, Math.round(w / 500))
  ctx.font = `bold ${Math.round(h / 24)}px sans-serif`
  ctx.fillStyle = 'rgba(255,220,0,0.9)'
  for (let i = 1; i < grid; i++) {
    ctx.beginPath(); ctx.moveTo((w * i) / grid, 0); ctx.lineTo((w * i) / grid, h); ctx.stroke()
    ctx.beginPath(); ctx.moveTo(0, (h * i) / grid); ctx.lineTo(w, (h * i) / grid); ctx.stroke()
  }
  for (let row = 0; row < grid; row++) {
    for (let col = 0; col < grid; col++) {
      const label = String.fromCharCode(65 + col) + String(row + 1)
      ctx.fillText(label, (w * col) / grid + w / (grid * 12), (h * row) / grid + h / (grid * 7))
    }
  }
  ctx.restore()
}
```

In `executors.ts`:

1. In `runSelectionTool`, before the volume-tool branch, add:

```typescript
    // v0.7 — controller tint: exact stable ids (never model-called)
    if (tool === 'select_by_ids') {
      const ids = args.ids as number[]
      if (!Array.isArray(ids)) return { ok: false, error: 'ids must be an array' }
      if (args.mode === 'replace') this.bridge.clearSelection()
      this.bridge.updateSelection(ids, args.mode === 'remove' ? 'remove' : 'add')
      const summary = this.bridge.getSelectionSummary()
      return { ok: true, count: summary.count, bbox: summary.bbox }
    }
```

2. In `survey_capture`: accept `args: { if_revision_not?: number; grid?: boolean }`; collect a pose per captured frame and pass the grid flag to `capturePNG`:

```typescript
    const poses: Array<{ position: number[]; target: number[]; fov: number; aspect: number }> = []
    const snapPose = () => {
      const { position, target } = this.bridge.getCameraPose()
      const cam = this.bridge.getCamera()
      const el = this.bridge.getRenderer().domElement
      poses.push({
        position: [position.x, position.y, position.z],
        target: [target.x, target.y, target.z],
        fov: cam.fov,
        aspect: (el.clientWidth || el.width) / (el.clientHeight || el.height),
      })
    }
```

Call `snapPose()` immediately after each `capturePNG(this.bridge, { grid: args.grid })` (operator view and each survey pose), and return `{ frames_base64, labels, poses, revision }`.

- [ ] **Step 4: Run tests + type-check**

Run: `cd frontend && npx vitest run src/agent && npx tsc -b`
Expected: PASS / clean. Also `npm run lint`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/agent/executors.ts frontend/src/agent/capture.ts frontend/src/agent/capture.test.ts
git commit -m "feat(agent-fe): select_by_ids tint, survey poses, grid overlay capture"
```

---

### Task 5: Forced-choice model call helper

**Files:**
- Create: `backend/agent/forced_choice.py`
- Create: `backend/agent/tests/test_forced_choice.py`

**Interfaces:**
- Consumes: `ModelProvider.generate(messages, tools, images)` (sync, threaded), `ToolSpec`/`ModelResponse`/`ToolCall` from contracts.
- Produces: `async def ask_forced(provider, instruction: str, tool_spec: dict, image: bytes | None = None, *, timeout_s: float = 45.0, retries: int = 1) -> dict | None` — returns the tool call's args on success, `None` on any failure (wrong tool name, no tool call, timeout, exception). `tool_spec` is a `CONTROLLER_CHOICE_SPECS`-shaped dict.

- [ ] **Step 1: Write the failing tests**

```python
# backend/agent/tests/test_forced_choice.py
"""ask_forced: one tiny context, one tool, safe-None on every failure mode."""
from __future__ import annotations

import asyncio
import time

from backend.agent.forced_choice import ask_forced
from backend.contracts import ModelResponse, ToolCall

SPEC = {
    "name": "judge_candidate",
    "description": "Judge the highlighted cluster.",
    "parameters": {"type": "object", "properties": {
        "verdict": {"type": "string", "enum": ["junk", "structure", "look_closer"]},
        "reason": {"type": "string"}}, "required": ["verdict", "reason"]},
}


class OneShotProvider:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def generate(self, messages, tools, images=None):
        self.calls.append({"messages": messages, "tools": tools, "images": images})
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def test_happy_path_returns_args_and_sends_one_tool():
    p = OneShotProvider([ModelResponse(text=None, tool_calls=[
        ToolCall("judge_candidate", {"verdict": "junk", "reason": "floating blob"})])])
    args = _run(ask_forced(p, "Is the highlighted cluster junk?", SPEC, image=b"png"))
    assert args == {"verdict": "junk", "reason": "floating blob"}
    call = p.calls[0]
    assert len(call["tools"]) == 1 and call["tools"][0].name == "judge_candidate"
    assert call["images"] == [b"png"]
    assert len(call["messages"]) == 1 and call["messages"][0]["role"] == "user"


def test_wrong_tool_name_retries_then_none():
    bad = ModelResponse(text=None, tool_calls=[ToolCall("answer", {"text": "hi"})])
    p = OneShotProvider([bad, bad])
    assert _run(ask_forced(p, "q", SPEC, retries=1)) is None
    assert len(p.calls) == 2


def test_prose_only_retries_then_none():
    prose = ModelResponse(text="it looks fine", tool_calls=[])
    p = OneShotProvider([prose, prose])
    assert _run(ask_forced(p, "q", SPEC, retries=1)) is None


def test_exception_returns_none():
    p = OneShotProvider([RuntimeError("boom"), RuntimeError("boom")])
    assert _run(ask_forced(p, "q", SPEC, retries=1)) is None


def test_timeout_returns_none():
    class SlowProvider:
        def generate(self, messages, tools, images=None):
            time.sleep(0.5)
            return ModelResponse(text=None, tool_calls=[ToolCall("judge_candidate", {"verdict": "junk", "reason": "x"})])
    assert _run(ask_forced(SlowProvider(), "q", SPEC, timeout_s=0.05, retries=0)) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest backend/agent/tests/test_forced_choice.py -v`
Expected: FAIL — module missing

- [ ] **Step 3: Implement**

```python
# backend/agent/forced_choice.py
"""Single forced-choice model calls for the CleanupController (spec §4).

Every call: fresh context — one short user instruction, one image, exactly one
tool schema. Bounded retries, then None; the caller substitutes a safe default
('unsure'). The run can therefore never stall on the model.
"""
from __future__ import annotations

import asyncio
from typing import Any

from backend.contracts import ModelProvider, ToolSpec


async def ask_forced(
    provider: ModelProvider,
    instruction: str,
    tool_spec: dict,
    image: bytes | None = None,
    *,
    timeout_s: float = 45.0,
    retries: int = 1,
) -> dict[str, Any] | None:
    spec = ToolSpec(
        name=tool_spec["name"],
        description=tool_spec.get("description", ""),
        parameters=tool_spec["parameters"],
    )
    messages = [{"role": "user", "content": instruction}]
    images = [image] if image else None
    for _ in range(retries + 1):
        try:
            resp = await asyncio.wait_for(
                asyncio.to_thread(provider.generate, messages, [spec], images),
                timeout=timeout_s,
            )
        except Exception:  # noqa: BLE001 — timeout, provider error: safe None
            continue
        for call in resp.tool_calls or []:
            if call.name == spec.name and isinstance(call.args, dict):
                return call.args
    return None
```

- [ ] **Step 4: Run tests**

Run: `pytest backend/agent/tests/test_forced_choice.py -v` → 5 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/agent/forced_choice.py backend/agent/tests/test_forced_choice.py
git commit -m "feat(agent): forced-choice model call helper (safe-None on all failures)"
```

---

### Task 6: CleanupController — phases 1–3 (crop, survey & mark, lock-in)

**Files:**
- Create: `backend/agent/cleanup_controller.py`
- Create: `backend/agent/tests/test_cleanup_controller.py`

**Interfaces:**
- Consumes: `ToolDispatcher.dispatch(ToolCall)`, `FrontendChannel` (send_command/emit_event/interrupted/paused/wait_resume), `ask_forced` (Task 5), `clusters` functions (Tasks 1–2), `CONTROLLER_CHOICE_SPECS` (Task 3), `ev_narrate/ev_tool_call/ev_tool_result/ev_complete` from `backend.agent.types`, `verify.silhouette_intact`.
- Produces (Task 7 and the runner depend on these):
  - `@dataclass CleanupConfig: max_survey_frames=6, grid=4, max_candidates=12, max_look_closer=1, call_timeout_s=45.0, call_retries=1, max_adjust_rounds=3, min_cluster_splats=30, cell_frac=0.03`
  - `class CleanupController: __init__(self, provider, dispatcher, channel, executor, splat_arrays: Callable[[], dict], config=None)` where `splat_arrays()` returns `{"means": np.ndarray, "opacity": np.ndarray, "ids": np.ndarray}` for ALIVE splats (the runner adapts `scene.model`; tests pass synthetic arrays).
  - `async def run(self, prompt: str) -> LoopResult` (phases 1–3 in this task; 4–6 in Task 7).
  - Internal state after phase 3: `self.candidates: list[Cluster]`, `self.marks: list[dict]`, `self.unresolved_marks: int`, `self.crop_result: dict | None`.

- [ ] **Step 1: Write the failing tests (scripted everything)**

```python
# backend/agent/tests/test_cleanup_controller.py
"""CleanupController phases 1-3: crop proposal, gridded survey + marks,
lock-in. Scaffolding mirrors test_proposals.py: scripted provider + channel,
recording executor. No model freedom anywhere: we assert the exact command
stream."""
from __future__ import annotations

import asyncio
import base64

import numpy as np

from backend.agent.cleanup_controller import CleanupConfig, CleanupController
from backend.agent.dispatch import ToolDispatcher
from backend.agent.tests.test_proposals import ProposalChannel, RecordingExecutor
from backend.contracts import ModelResponse, ToolCall


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def _scene_arrays():
    rng = np.random.default_rng(0)
    building = rng.uniform(-0.5, 0.5, size=(2000, 3))
    blob = np.array([10.0, 0.0, 0.0]) + rng.normal(0, 0.05, size=(80, 3))
    means = np.vstack([building, blob])
    return {
        "means": means,
        "opacity": np.full(len(means), 0.8),
        "ids": np.arange(len(means), dtype=np.int64),
    }


class ChoiceProvider:
    """Scripted forced-choice responses, in call order."""

    def __init__(self, script: list[ModelResponse | Exception]):
        self.script = list(script)
        self.calls: list[dict] = []

    def generate(self, messages, tools, images=None):
        self.calls.append({"messages": messages, "tools": [t.name for t in tools]})
        if not self.script:
            return ModelResponse(text=None, tool_calls=[])
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class TourChannel(ProposalChannel):
    """ProposalChannel + a survey_capture reply carrying frames AND poses."""

    def __init__(self, n_frames=3, **kw):
        super().__init__(**kw)
        png = base64.b64encode(b"fakepng").decode()
        self.survey_reply = {
            "frames_base64": [png] * n_frames,
            "labels": ["operator's view"] + [f"pose{i}" for i in range(1, n_frames)],
            "poses": [
                {"position": [10, 0, 8], "target": [10, 0, 0], "fov": 60.0, "aspect": 1.0}
            ] * n_frames,
            "revision": 1,
        }

    async def send_command(self, cmd):
        if cmd.get("type") == "capture_request" and cmd.get("tool") == "survey_capture":
            self.commands.append(cmd)
            return dict(self.survey_reply)
        return await super().send_command(cmd)


def _mark(cells):
    return ModelResponse(text=None, tool_calls=[ToolCall("mark_noise", {"cells": cells})])


def _controller(provider, channel, executor, **cfg):
    dispatcher = ToolDispatcher(executor, channel)
    config = CleanupConfig(call_timeout_s=5.0, **cfg)
    return CleanupController(provider, dispatcher, channel, executor, _scene_arrays, config)


def test_phase1_crop_proposed_and_executed_on_approval():
    channel = TourChannel(verdicts=[{"verdict": "approved"}])
    executor = RecordingExecutor()
    provider = ChoiceProvider([_mark([]), _mark([]), _mark([])])
    c = _controller(provider, channel, executor)
    result = _run(c.run("cleanup_scene"))
    assert "crop_bbox" in executor.edit_calls
    # crop bounds are the app's core box, not anything model-authored
    assert executor.last_crop is not None
    # proposal was raised exactly once for the crop in phases 1-3
    crop_proposals = [
        cmd for cmd in channel.commands
        if cmd.get("type") == "proposal" and cmd["args"]["kind"] == "crop_outside_box"
    ]
    assert len(crop_proposals) == 1
    assert result.status in ("answered", "max_steps")  # phases 4-6 complete in Task 7


def test_phase1_crop_rejected_skips_crop_but_run_continues():
    channel = TourChannel(verdicts=[{"verdict": "rejected"}])
    executor = RecordingExecutor()
    provider = ChoiceProvider([_mark([]), _mark([]), _mark([])])
    c = _controller(provider, channel, executor)
    _run(c.run("cleanup_scene"))
    assert "crop_bbox" not in executor.edit_calls
    # survey still ran
    assert any(cmd.get("tool") == "survey_capture" for cmd in channel.commands)


def test_phase2_one_mark_call_per_frame_with_gridded_survey():
    channel = TourChannel(n_frames=3, verdicts=[{"verdict": "approved"}])
    executor = RecordingExecutor()
    provider = ChoiceProvider([_mark(["B3"]), _mark([]), _mark([])])
    c = _controller(provider, channel, executor)
    _run(c.run("cleanup_scene"))
    mark_calls = [k for k in provider.calls if k["tools"] == ["mark_noise"]]
    assert len(mark_calls) == 3
    survey_cmd = next(cmd for cmd in channel.commands if cmd.get("tool") == "survey_capture")
    assert survey_cmd["args"].get("grid") is True


def test_phase3_stats_cluster_survives_model_silence():
    # all mark calls fail -> candidates come from statistics alone (spec §8)
    channel = TourChannel(verdicts=[{"verdict": "approved"}])
    executor = RecordingExecutor()
    provider = ChoiceProvider([RuntimeError("down")] * 8)
    c = _controller(provider, channel, executor)
    _run(c.run("cleanup_scene"))
    assert len(c.candidates) == 1          # the far blob
    assert c.candidates[0].provenance == "stats"


def test_interrupt_during_survey_completes_with_interrupted_status():
    channel = TourChannel(verdicts=[{"verdict": "approved"}])
    channel.interrupt_after = 1            # ProposalChannel counts send_commands
    executor = RecordingExecutor()
    provider = ChoiceProvider([_mark([])] * 3)
    c = _controller(provider, channel, executor)
    result = _run(c.run("cleanup_scene"))
    assert result.status == "interrupted"
```

Note: `ProposalChannel` in `test_proposals.py` may not implement `interrupt_after`; check it — if its `MockFrontendChannel` base exposes `interrupted` as a settable flag, implement the count-based interrupt in `TourChannel` instead:

```python
    # in TourChannel.__init__: self.interrupt_after = None; self._sends = 0
    # in send_command, before returning: self._sends += 1
    # and override:  @property
    #                def interrupted(self): return self.interrupt_after is not None and self._sends > self.interrupt_after
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest backend/agent/tests/test_cleanup_controller.py -v`
Expected: FAIL — `cleanup_controller` missing

- [ ] **Step 3: Implement phases 1–3**

```python
# backend/agent/cleanup_controller.py
"""App-owned judgment-tour cleanup (spec 2026-08-04-judgment-tour-cleanup).

A Python phase machine replaces the freeform loop for cleanup runs. The model
is consulted ONLY through ask_forced(): grid marks in phase 2, verdicts in
phase 4, feedback flips in phase 5. Everything spatial and procedural is code.

Phases: 1 crop -> 2 survey & mark -> 3 lock-in -> 4 tour -> 5 batch proposal
-> 6 summary. Every phase boundary checks interrupt/pause.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from backend.analysis.clusters import (
    Cluster, core_box, find_clusters, resolve_marks,
)
from backend.contracts import FrontendChannel, ModelProvider, ToolCall
from backend.contracts.tools import CONTROLLER_CHOICE_SPECS

from .dispatch import ToolDispatcher
from .forced_choice import ask_forced
from .types import LoopResult, ev_complete, ev_narrate, ev_tool_call, ev_tool_result
from .verify import silhouette_intact


@dataclass
class CleanupConfig:
    max_survey_frames: int = 6
    grid: int = 4
    max_candidates: int = 12
    max_look_closer: int = 1
    call_timeout_s: float = 45.0
    call_retries: int = 1
    max_adjust_rounds: int = 3
    min_cluster_splats: int = 30
    cell_frac: float = 0.03


_MARK_INSTRUCTION = (
    "This is one view of a 3D-scanned scene with a {grid}x{grid} labeled grid "
    "(columns A-D left to right, rows 1-4 top to bottom). Call mark_noise with "
    "the cells that contain floating junk, debris mist, or fragments "
    "disconnected from the main structure. Use [] if this view looks clean."
)


class RunInterrupted(Exception):
    pass


class CleanupController:
    def __init__(
        self,
        provider: ModelProvider,
        dispatcher: ToolDispatcher,
        channel: FrontendChannel,
        executor: Any,
        splat_arrays: Callable[[], dict],
        config: CleanupConfig | None = None,
    ) -> None:
        self.provider = provider
        self.dispatcher = dispatcher
        self.channel = channel
        self.executor = executor
        self.splat_arrays = splat_arrays
        self.config = config or CleanupConfig()
        self._step = 0
        # phase-3 outputs
        self.candidates: list[Cluster] = []
        self.marks: list[dict] = []
        self.unresolved_marks = 0
        self.crop_result: dict | None = None

    # ---- plumbing -------------------------------------------------------- #
    async def _emit(self, event: dict) -> None:
        await self.channel.emit_event(event)

    async def _say(self, text: str) -> None:
        await self._emit(ev_narrate(text))

    async def _checkpoint(self) -> None:
        """Interrupt/pause gate — called at every phase boundary and tour stop."""
        if self.channel.interrupted:
            raise RunInterrupted
        if self.channel.paused:
            await self._say("Paused — resume to continue the cleanup.")
            await self.channel.wait_resume()

    async def _dispatch(self, name: str, args: dict) -> dict:
        self._step += 1
        await self._emit(ev_tool_call(name, args, self._step))
        result = await self.dispatcher.dispatch(ToolCall(name, dict(args)))
        await self._emit(ev_tool_result(name, {k: v for k, v in result.items() if k != "frames"}, self._step))
        return result

    async def _ask(self, instruction: str, spec_name: str, image: bytes | None) -> dict | None:
        return await ask_forced(
            self.provider, instruction, CONTROLLER_CHOICE_SPECS[spec_name], image,
            timeout_s=self.config.call_timeout_s, retries=self.config.call_retries,
        )

    def _arrays(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        a = self.splat_arrays()
        return np.asarray(a["means"]), np.asarray(a["opacity"]), np.asarray(a["ids"])

    # ---- destructive edit with the standard guard ------------------------ #
    async def _guarded_edit(self, fn_name: str, *args) -> dict:
        before = await asyncio.to_thread(self.executor.get_metrics)
        await asyncio.to_thread(self.executor.snapshot)
        result = await asyncio.to_thread(getattr(self.executor, fn_name), *args)
        after = await asyncio.to_thread(self.executor.get_metrics)
        if not silhouette_intact(before, after, approved=True):
            await asyncio.to_thread(self.executor.undo)
            await self._say(f"Reverted {fn_name}: it would have destroyed the subject's core.")
            return {"ok": False, "reverted": True, "result": result}
        return {"ok": True, "result": result, "before": before, "after": after}

    # ---- run ------------------------------------------------------------- #
    async def run(self, prompt: str) -> LoopResult:
        result = LoopResult(status="answered")
        try:
            await self._phase1_crop()
            await self._checkpoint()
            frames, poses = await self._phase2_survey_and_mark()
            await self._checkpoint()
            self._phase3_lock_in()
            await self._say(self._lock_in_summary())
            await self._checkpoint()
            # Phases 4-6 land in the next task:
            answer = await self._phases_4_to_6()
            result.answer = answer
            await self._emit(ev_complete("answered", answer=answer, scene_changed=True))
        except RunInterrupted:
            result.status = "interrupted"
            await self._emit(ev_complete("interrupted"))
        except Exception as exc:  # noqa: BLE001 — a controller bug must still end the run
            result.status = "error"
            result.error = str(exc)
            await self._emit(ev_complete("error", error=str(exc)))
        result.steps = self._step
        return result

    # ---- phase 1: crop ---------------------------------------------------- #
    async def _phase1_crop(self) -> None:
        means, _, _ = self._arrays()
        mn, mx = core_box(means)
        box_min = [float(v) for v in mn]
        box_max = [float(v) for v in mx]
        await self._say("Proposing a crop to the dense core — adjust the box or reject to skip cropping.")
        await self._dispatch("show_box_preview", {"min": box_min, "max": box_max})
        reply = await self._dispatch("propose_decision", {
            "kind": "crop_outside_box",
            "summary": "Crop away everything outside the highlighted core box. "
                       "Drag the box to adjust before approving.",
        })
        verdict = (reply.get("result") or {}) if reply.get("ok") else {}
        if verdict.get("verdict") == "approved":
            box = verdict.get("box") or {"min": box_min, "max": box_max}
            out = await self._guarded_edit("crop_bbox", box["min"], box["max"])
            if out["ok"]:
                self.crop_result = out["result"]
                await self._say("Crop applied.")
        else:
            await self._say("Crop skipped — moving on to the noise survey.")

    # ---- phase 2: survey & mark ------------------------------------------ #
    async def _phase2_survey_and_mark(self) -> tuple[list[bytes], list[dict]]:
        await self._say("Surveying the scene — the model will mark where it sees noise.")
        res = await self._dispatch("survey_capture", {"grid": True})
        payload = res.get("result") or {}
        frames: list[bytes] = list(res.get("frames") or [])[: self.config.max_survey_frames]
        poses: list[dict] = list(payload.get("poses") or [])[: len(frames)]
        self.marks = []
        for i, (frame, pose) in enumerate(zip(frames, poses)):
            await self._checkpoint()
            args = await self._ask(
                _MARK_INSTRUCTION.format(grid=self.config.grid), "mark_noise", frame,
            )
            cells = [c for c in (args or {}).get("cells", []) if isinstance(c, str)]
            if args is None:
                await self._say(f"View {i + 1}: model unavailable — marked unsure.")
            elif cells:
                await self._say(f"View {i + 1}: model marked {', '.join(cells)}.")
            self.marks.append({"cells": cells, "pose": pose})
        return frames, poses

    # ---- phase 3: lock-in -------------------------------------------------- #
    def _phase3_lock_in(self) -> None:
        means, opacity, ids = self._arrays()
        mn, mx = core_box(means)
        stats = find_clusters(
            means, opacity, ids, mn, mx,
            cell_frac=self.config.cell_frac,
            min_splats=self.config.min_cluster_splats,
            max_clusters=self.config.max_candidates,
        )
        n_marked = sum(1 for m in self.marks if m["cells"])
        merged = resolve_marks(
            means, opacity, ids, self.marks, stats, mn, mx,
            grid=self.config.grid, min_splats=self.config.min_cluster_splats,
        ) if n_marked else stats
        self.unresolved_marks = max(
            0, sum(len(m["cells"]) for m in self.marks)
            - sum(c.mark_votes for c in merged),
        )
        self.candidates = merged[: self.config.max_candidates]

    def _lock_in_summary(self) -> str:
        n = len(self.candidates)
        from_model = sum(1 for c in self.candidates if c.provenance == "model")
        both = sum(1 for c in self.candidates if c.provenance == "both")
        return (
            f"Found {n} junk candidate{'s' if n != 1 else ''} "
            f"({both} confirmed by both statistics and the model, "
            f"{from_model} spotted only by the model). Starting the judgment tour."
        )

    # ---- phases 4-6 (Task 7) ----------------------------------------------- #
    async def _phases_4_to_6(self) -> str:
        raise NotImplementedError  # implemented in Task 7
```

For this task only, make the tests pass by having `_phases_4_to_6` return a stub summary instead of raising:

```python
    async def _phases_4_to_6(self) -> str:
        return f"Cleanup survey complete: {len(self.candidates)} candidates."
```

(Task 7 replaces the stub; the tests in this task assert phases 1–3 behavior only.)

- [ ] **Step 4: Run tests**

Run: `pytest backend/agent/tests/test_cleanup_controller.py -v`
Expected: 5 PASS. Fix the `interrupt_after` scaffolding per the note in Step 1 if `ProposalChannel` lacks it.

- [ ] **Step 5: Run the whole agent suite (no regressions)**

Run: `pytest backend/agent/ -q` → all pass

- [ ] **Step 6: Commit**

```bash
git add backend/agent/cleanup_controller.py backend/agent/tests/test_cleanup_controller.py
git commit -m "feat(agent): CleanupController phases 1-3 (crop, gridded survey, lock-in)"
```

---

### Task 7: CleanupController — phases 4–6 (tour, batch proposal, execution, summary)

**Files:**
- Modify: `backend/agent/cleanup_controller.py`
- Modify: `backend/agent/tests/test_cleanup_controller.py`

**Interfaces:**
- Consumes: everything from Task 6; `judge_candidate` spec; `select_by_ids`/`frame_object`/`orbit`/`capture_frame`/`clear_selection` dispatches; `propose_decision` with `kind="delete_clusters"`.
- Produces: complete `run()`; verdict records `self.verdicts: dict[str, str]` (label → `"junk"|"structure"|"unsure"`), reasons `self.reasons: dict[str, str]`; final `answer` string summarizing the run.

- [ ] **Step 1: Write the failing tests (append)**

```python
def _judge(verdict, reason="because"):
    return ModelResponse(text=None, tool_calls=[ToolCall("judge_candidate", {"verdict": verdict, "reason": reason})])


def _two_blob_arrays():
    rng = np.random.default_rng(0)
    building = rng.uniform(-0.5, 0.5, size=(2000, 3))
    blob_a = np.array([10.0, 0.0, 0.0]) + rng.normal(0, 0.05, size=(80, 3))
    blob_b = np.array([0.0, 12.0, 0.0]) + rng.normal(0, 0.05, size=(50, 3))
    means = np.vstack([building, blob_a, blob_b])
    return lambda: {
        "means": means,
        "opacity": np.full(len(means), 0.8),
        "ids": np.arange(len(means), dtype=np.int64),
    }


class DeletingExecutor(RecordingExecutor):
    """Records delete_selection id payloads for binding assertions."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.deleted_batches: list[list[int]] = []

    def delete_selection(self, ids):
        self.deleted_batches.append(list(ids))
        return super().delete_selection(ids)


def _tour_controller(provider, channel, executor, arrays=None):
    dispatcher = ToolDispatcher(executor, channel)
    return CleanupController(
        provider, dispatcher, channel, executor,
        arrays or _two_blob_arrays(), CleanupConfig(call_timeout_s=5.0),
    )


def test_tour_judges_each_candidate_and_deletes_only_junk():
    channel = TourChannel(verdicts=[{"verdict": "approved"},   # crop
                                    {"verdict": "approved"}])  # batch
    executor = DeletingExecutor()
    provider = ChoiceProvider(
        [_mark([]), _mark([]), _mark([])] +        # 3 survey frames
        [_judge("junk"), _judge("structure")]      # 2 candidates, size order
    )
    c = _tour_controller(provider, channel, executor)
    result = _run(c.run("cleanup_scene"))
    assert result.status == "answered"
    assert c.verdicts == {"A": "junk", "B": "structure"}
    # only cluster A (the bigger blob, 80 splats) was deleted
    assert len(executor.deleted_batches) == 1
    assert len(executor.deleted_batches[0]) == 80
    # tour flew to each candidate and tinted it
    framed = [cmd for cmd in channel.commands if cmd.get("tool") == "frame_object"]
    tinted = [cmd for cmd in channel.commands if cmd.get("tool") == "select_by_ids"]
    assert len(framed) >= 2 and len(tinted) >= 2


def test_look_closer_gets_one_extra_view_then_must_commit():
    channel = TourChannel(verdicts=[{"verdict": "approved"}, {"verdict": "approved"}])
    executor = DeletingExecutor()
    provider = ChoiceProvider(
        [_mark([]), _mark([]), _mark([])] +
        [_judge("look_closer"), _judge("junk"),          # candidate A: 2 calls
         _judge("look_closer"), _judge("look_closer")]   # candidate B: coerced
    )
    c = _tour_controller(provider, channel, executor)
    _run(c.run("cleanup_scene"))
    assert c.verdicts["A"] == "junk"
    assert c.verdicts["B"] == "structure"     # second look_closer coerces to keep


def test_model_failure_during_tour_is_unsure_kept():
    channel = TourChannel(verdicts=[{"verdict": "approved"}, {"verdict": "approved"}])
    executor = DeletingExecutor()
    provider = ChoiceProvider([_mark([]), _mark([]), _mark([]),
                               RuntimeError("x"), RuntimeError("x"),   # A: retry then None
                               _judge("junk")])                        # B
    c = _tour_controller(provider, channel, executor)
    _run(c.run("cleanup_scene"))
    assert c.verdicts["A"] == "unsure"
    # unsure is NOT deleted
    assert all(len(b) != 80 for b in executor.deleted_batches)


def test_batch_card_carries_cluster_rows_and_binds_ids():
    channel = TourChannel(verdicts=[{"verdict": "approved"}, {"verdict": "approved"}])
    executor = DeletingExecutor()
    provider = ChoiceProvider([_mark([]), _mark([]), _mark([]),
                               _judge("junk"), _judge("junk")])
    c = _tour_controller(provider, channel, executor)
    _run(c.run("cleanup_scene"))
    batch = next(cmd for cmd in channel.commands
                 if cmd.get("type") == "proposal" and cmd["args"]["kind"] == "delete_clusters")
    rows = batch["args"]["clusters"]
    assert [r["label"] for r in rows] == ["A", "B"]
    assert all({"label", "count", "verdict"} <= set(r) for r in rows)
    assert len(executor.deleted_batches) == 2   # per-cluster sequential deletes


def test_batch_rejected_deletes_nothing_and_still_summarizes():
    channel = TourChannel(verdicts=[{"verdict": "approved"},   # crop
                                    {"verdict": "rejected"}])  # batch
    executor = DeletingExecutor()
    provider = ChoiceProvider([_mark([]), _mark([]), _mark([]),
                               _judge("junk"), _judge("junk")])
    c = _tour_controller(provider, channel, executor)
    result = _run(c.run("cleanup_scene"))
    assert executor.deleted_batches == []
    assert result.status == "answered"
    assert "kept" in (result.answer or "").lower() or "no clusters" in (result.answer or "").lower()


def test_adjust_flips_verdict_then_reproposes():
    channel = TourChannel(verdicts=[
        {"verdict": "approved"},                                   # crop
        {"verdict": "adjusted", "feedback": "keep A, it is a shed"},
        {"verdict": "approved"},                                   # re-proposed batch
    ])
    executor = DeletingExecutor()
    flip = ModelResponse(text=None, tool_calls=[ToolCall(
        "apply_feedback", {"flips": [{"label": "A", "to": "keep"}]})])
    provider = ChoiceProvider([_mark([]), _mark([]), _mark([]),
                               _judge("junk"), _judge("junk"),
                               flip])
    c = _tour_controller(provider, channel, executor)
    _run(c.run("cleanup_scene"))
    assert c.verdicts["A"] == "structure"
    assert len(executor.deleted_batches) == 1        # only B deleted
    assert len(executor.deleted_batches[0]) == 50


def test_no_candidates_short_circuits_to_clean_answer():
    rng = np.random.default_rng(0)
    clean = lambda: {  # noqa: E731
        "means": rng.uniform(-0.5, 0.5, size=(2000, 3)),
        "opacity": np.full(2000, 0.8),
        "ids": np.arange(2000, dtype=np.int64),
    }
    channel = TourChannel(verdicts=[{"verdict": "approved"}])
    executor = DeletingExecutor()
    provider = ChoiceProvider([_mark([]), _mark([]), _mark([])])
    c = _tour_controller(provider, channel, executor, arrays=clean)
    result = _run(c.run("cleanup_scene"))
    assert result.status == "answered"
    assert executor.deleted_batches == []
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `pytest backend/agent/tests/test_cleanup_controller.py -v -k "tour or look_closer or unsure or batch or adjust or no_candidates"`
Expected: FAIL (stub `_phases_4_to_6` produces no verdicts/proposal)

- [ ] **Step 3: Implement phases 4–6 (replace the stub)**

Add to `CONTROLLER_CHOICE_SPECS` usage a module-level constant in `cleanup_controller.py` (the feedback tool is controller-private, not a contract):

```python
_JUDGE_INSTRUCTION = (
    "The highlighted (tinted) cluster of points is candidate {label}: "
    "{count} splats, {dist:.1f} units from the main structure. Call "
    "judge_candidate: 'junk' if it is floating debris/noise to delete, "
    "'structure' if it is part of a real object to keep, or 'look_closer' "
    "for one more view if you truly cannot tell."
)

_FEEDBACK_SPEC = {
    "name": "apply_feedback",
    "description": "Translate the operator's feedback into per-cluster flips.",
    "parameters": {
        "type": "object",
        "properties": {
            "flips": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "to": {"type": "string", "enum": ["keep", "delete"]},
                    },
                    "required": ["label", "to"],
                },
            },
        },
        "required": ["flips"],
    },
}
```

Then the phase implementations (replace the stub method):

```python
    # ---- phase 4: judgment tour ------------------------------------------ #
    async def _phase4_tour(self) -> None:
        self.verdicts: dict[str, str] = {}
        self.reasons: dict[str, str] = {}
        for cand in self.candidates:
            await self._checkpoint()
            await self._say(f"Visiting candidate {cand.label} ({cand.count} splats, {cand.provenance}).")
            await self._frame_and_tint(cand)
            verdict, reason = await self._judge_once(cand)
            if verdict == "look_closer":
                looks = 0
                while verdict == "look_closer":
                    looks += 1
                    if looks > self.config.max_look_closer:
                        verdict, reason = "structure", "could not decide — keeping it (safe default)"
                        break
                    await self._dispatch("orbit", {
                        "center": [(a + b) / 2 for a, b in zip(cand.bbox_min, cand.bbox_max)],
                        "deg": 70, "axis": "y", "duration_ms": 800,
                    })
                    verdict, reason = await self._judge_once(cand)
                    if verdict == "look_closer" and looks >= self.config.max_look_closer:
                        verdict, reason = "structure", "could not decide — keeping it (safe default)"
            self.verdicts[cand.label] = verdict
            self.reasons[cand.label] = reason
            await self._say(f"Candidate {cand.label}: {verdict} — {reason}")
        await self._dispatch("clear_selection", {})

    async def _frame_and_tint(self, cand: Cluster) -> None:
        pad = max(cand.extent * 0.5, 0.25)
        bbox = {
            "min": [v - pad for v in cand.bbox_min],
            "max": [v + pad for v in cand.bbox_max],
        }
        await self._dispatch("frame_object", {"bbox": bbox, "duration_ms": 900})
        await self._dispatch("select_by_ids", {"ids": [int(i) for i in cand.ids], "mode": "replace"})

    async def _judge_once(self, cand: Cluster) -> tuple[str, str]:
        cap = await self._dispatch("capture_frame", {})
        frames = cap.get("frames") or []
        image = frames[0] if frames else None
        args = await self._ask(
            _JUDGE_INSTRUCTION.format(label=cand.label, count=cand.count, dist=cand.dist_from_core),
            "judge_candidate", image,
        )
        if args is None:
            return "unsure", "model unavailable — kept by default"
        verdict = args.get("verdict")
        if verdict not in ("junk", "structure", "look_closer"):
            return "unsure", "unusable model reply — kept by default"
        return verdict, str(args.get("reason", ""))[:120]

    # ---- phase 5: batch proposal + bound execution ------------------------- #
    def _rows(self) -> list[dict]:
        return [{
            "label": c.label, "count": c.count,
            "verdict": self.verdicts.get(c.label, "unsure"),
            "reason": self.reasons.get(c.label, ""),
            "provenance": c.provenance,
        } for c in self.candidates]

    async def _phase5_batch(self) -> tuple[int, int, int]:
        """Returns (clusters_deleted, splats_deleted, clusters_skipped)."""
        junk = [c for c in self.candidates if self.verdicts.get(c.label) == "junk"]
        if not junk:
            await self._say("No clusters judged junk — nothing to delete.")
            return 0, 0, 0
        rounds = 0
        while True:
            total = sum(c.count for c in junk)
            kept = len(self.candidates) - len(junk)
            reply = await self._dispatch("propose_decision", {
                "kind": "delete_clusters",
                "summary": f"Delete {len(junk)} cluster{'s' if len(junk) != 1 else ''} "
                           f"({total:,} splats). Keeping {kept} judged structure/unsure.",
                "clusters": self._rows(),
            })
            verdict = (reply.get("result") or {}) if reply.get("ok") else {}
            v = verdict.get("verdict")
            if v == "approved":
                return await self._execute_junk(junk)
            if v == "adjusted" and rounds < self.config.max_adjust_rounds:
                rounds += 1
                await self._apply_feedback(str(verdict.get("feedback", "")))
                junk = [c for c in self.candidates if self.verdicts.get(c.label) == "junk"]
                if not junk:
                    await self._say("After your adjustments nothing is marked junk.")
                    return 0, 0, 0
                continue
            await self._say("Batch rejected — keeping everything.")
            return 0, 0, 0

    async def _apply_feedback(self, feedback: str) -> None:
        labels = ", ".join(c.label for c in self.candidates)
        # _FEEDBACK_SPEC is controller-private (not a contract tool), so this
        # calls ask_forced directly rather than going through self._ask.
        args = await ask_forced(
            self.provider,
            f"Cluster labels: {labels}. Current verdicts: "
            + "; ".join(f"{k}={v}" for k, v in self.verdicts.items())
            + f". Operator feedback: \"{feedback}\". Call apply_feedback with the flips.",
            _FEEDBACK_SPEC, None,
            timeout_s=self.config.call_timeout_s, retries=self.config.call_retries,
        )
        if not args:
            await self._say("Couldn't parse that feedback — showing the card again unchanged.")
            return
        for flip in args.get("flips", []):
            label = str(flip.get("label", "")).upper()
            if label in self.verdicts:
                self.verdicts[label] = "structure" if flip.get("to") == "keep" else "junk"
                self.reasons[label] = f"operator: {feedback}"[:120]

    async def _execute_junk(self, junk: list[Cluster]) -> tuple[int, int, int]:
        means_ids = set(int(i) for i in self._arrays()[2])
        deleted = splats = skipped = 0
        for c in junk:
            await self._checkpoint()
            ids = [int(i) for i in c.ids]
            if not all(i in means_ids for i in ids):
                skipped += 1
                await self._say(f"Cluster {c.label} changed since review — skipped (approval void for it).")
                continue
            await self._dispatch("select_by_ids", {"ids": ids, "mode": "replace"})
            out = await self._guarded_edit("delete_selection", ids)
            if out["ok"]:
                deleted += 1
                splats += len(ids)
                means_ids.difference_update(ids)
                await self._say(f"Deleted cluster {c.label} ({len(ids):,} splats).")
            else:
                skipped += 1
        await self._dispatch("clear_selection", {})
        return deleted, splats, skipped

    # ---- phase 6: summary --------------------------------------------------- #
    async def _phases_4_to_6(self) -> str:
        if not self.candidates:
            answer = "Scene looks clean: no junk candidates found after the crop."
            await self._say(answer)
            return answer
        await self._phase4_tour()
        deleted, splats, skipped = await self._phase5_batch()
        kept = len(self.candidates) - deleted - skipped
        parts = [f"Cleanup done: {deleted} cluster{'s' if deleted != 1 else ''} deleted ({splats:,} splats)"]
        parts.append(f"{kept} kept")
        if skipped:
            parts.append(f"{skipped} skipped (changed or reverted)")
        if self.unresolved_marks:
            parts.append(f"{self.unresolved_marks} model mark(s) resolved to nothing")
        answer = ", ".join(parts) + "."
        await self._say(answer)
        return answer
```

Wire the crop-phase `delete_selection`-style guarded call: note `_guarded_edit("delete_selection", ids)` calls `executor.delete_selection(ids)` directly — the RecordingExecutor and RealBackendExecutor both accept `ids` positionally.

- [ ] **Step 4: Run the full controller test file**

Run: `pytest backend/agent/tests/test_cleanup_controller.py -v`
Expected: all 12 PASS

- [ ] **Step 5: Full backend suite**

Run: `pytest -q` → all pass

- [ ] **Step 6: Commit**

```bash
git add backend/agent/cleanup_controller.py backend/agent/tests/test_cleanup_controller.py
git commit -m "feat(agent): judgment tour, batch proposal, bound execution, summary"
```

---

### Task 8: Route cleanup runs to the controller (API + runner + frontend pill)

**Files:**
- Modify: `backend/api/routes.py` (`/agent/run`), `backend/api/engine.py` (AgentRunner protocol — check with `grep -n "def run" backend/api/engine.py`), `backend/api/real_engine.py` (`RealAgentRunner.run`), the `AgentRunRequest` model (find with `grep -rn "class AgentRunRequest" backend/api/`)
- Modify: `src/session/useSession.ts` (`runAgent`, ~line 600) and the pill click handler in `src/ui/ChatPanel.tsx` (find with `grep -n "runAgent\|skills" src/ui/ChatPanel.tsx`)
- Test: `backend/api/tests/test_cleanup_route.py` (create)

**Interfaces:**
- Consumes: `CleanupController` (Tasks 6–7), existing run-management in routes.
- Produces:
  - `AgentRunRequest` gains `mode: str | None = None` (`"cleanup"` routes to the controller; absent/other = freeform loop, unchanged).
  - `RealAgentRunner.run(self, prompt, scene, channel, stage="clean", mode=None)`.
  - Frontend: clicking the `cleanup_scene` pill sends `mode: "cleanup"`; typed prompts equal to `cleanup_scene` (trimmed) also route to it backend-side.

- [ ] **Step 1: Write the failing API test**

```python
# backend/api/tests/test_cleanup_route.py
"""POST /agent/run with mode='cleanup' (or the pill prompt) reaches the
CleanupController instead of the freeform loop. Mirrors the harness style of
backend/api/tests/test_proposal_ws.py — reuse its app/scene/ws fixtures."""
from __future__ import annotations

from unittest.mock import patch


def test_mode_cleanup_builds_controller(monkeypatch, app_with_scene):
    # app_with_scene: reuse/adapt the fixture from test_proposal_ws.py that
    # yields (client, scene_id, connected_ws). If it is module-local, copy it.
    client, scene_id = app_with_scene
    created = {}

    class FakeController:
        def __init__(self, *a, **k):
            created["yes"] = True

        async def run(self, prompt):
            from backend.agent.types import LoopResult
            return LoopResult(status="answered", answer="ok")

    with patch("backend.api.real_engine.CleanupController", FakeController, create=True):
        r = client.post("/agent/run", json={
            "scene_id": scene_id, "prompt": "cleanup_scene",
            "stage": "clean", "mode": "cleanup",
        })
    assert r.status_code == 200
    assert created.get("yes")


def test_prompt_cleanup_scene_routes_without_mode(app_with_scene):
    client, scene_id = app_with_scene
    # same patch pattern; prompt-only routing
    ...
```

Adapt fixture names to what `backend/api/tests/test_proposal_ws.py` actually provides (read it first; keep this test in its style — the intent asserted is exactly the two routing conditions).

- [ ] **Step 2: Run to verify failure**

Run: `pytest backend/api/tests/test_cleanup_route.py -v` → FAIL (unknown field `mode` / no routing)

- [ ] **Step 3: Implement backend routing**

1. `AgentRunRequest`: add `mode: str | None = None`.
2. `routes.py` `_drive()`: pass it through — `await runner.run(req.prompt, state.scene, channel, stage=req.stage, mode=req.mode)`. Update `engine.py`'s `AgentRunner` protocol signature to match (keyword with default so `MockAgentRunner`-style fakes stay valid; update any fakes the API tests use).
3. `real_engine.py` — inside `RealAgentRunner.run`, after resolving the stage:

```python
        wants_cleanup = resolved == "clean" and (
            mode == "cleanup" or prompt.strip() == "cleanup_scene"
        )
        if wants_cleanup:
            from backend.agent.cleanup_controller import CleanupController
            import numpy as np

            def splat_arrays() -> dict:
                m = scene.model
                alive = m.alive
                return {
                    "means": np.asarray(m.means[alive], dtype=np.float64),
                    "opacity": np.asarray(m.opacity(alive_only=True), dtype=np.float64),
                    "ids": np.asarray(m.alive_indices(), dtype=np.int64),
                }

            controller = CleanupController(provider, dispatcher, channel, executor, splat_arrays)
            await controller.run(prompt)
            return
```

Build `provider` for this path with a minimal `system_instruction` (`"You are a visual inspector for a 3D scan. Always answer by calling the provided tool."`) instead of the full clean prompt — build the provider AFTER the `wants_cleanup` decision so each path gets its own instruction.

4. Frontend: `useSession.runAgent(sceneId, text, stage, clientId)` gains an optional `mode?: string` forwarded in the POST body; the ChatPanel pill handler passes `mode: 'cleanup'` when the clicked pill is `cleanup_scene`. (Locate with the greps in **Files**; keep the change minimal — one optional param threaded through.)

- [ ] **Step 4: Run tests + type-check**

Run: `pytest backend/api/ -q` → all pass
Run: `cd frontend && npx tsc -b && npm run lint` → clean (repeat at repo root for `src/` if the root has its own tsconfig — check `ls tsconfig*.json`)

- [ ] **Step 5: Commit**

```bash
git add backend/api/ src/session/useSession.ts src/ui/ChatPanel.tsx
git commit -m "feat(api): route cleanup_scene runs to the CleanupController"
```

---

### Task 9: Batch ProposalCard (cluster rows) + ws-client passthrough

**Files:**
- Modify: `frontend/src/agent/ws-client.ts` (proposal case, lines ~164–219)
- Modify: `frontend/src/agent/panels.ts` (ProposalState)
- Modify: `src/ui/ProposalCard.tsx`, `src/ui/proposalTitle.ts`
- Test: extend `frontend/src/agent/contracts.test.ts` typing only (rows type already tested in Task 3); UI verified by `npx tsc -b` + existing component conventions (repo has no React component test harness — do not introduce one).

**Interfaces:**
- Consumes: `ClusterRow` from `contracts.ts` (Task 3).
- Produces: `ProposalState` gains `clusters?: ClusterRow[]`; the card renders a row table when present; `proposalTitle('delete_clusters')` → `"Delete junk clusters"`.

- [ ] **Step 1: Thread the payload**

In `ws-client.ts`'s `proposal` case, extend the destructured args with `clusters?: unknown` and pass a sanitized copy through:

```typescript
          const rawRows = (args as { clusters?: unknown }).clusters
          const clusters = Array.isArray(rawRows)
            ? rawRows.filter((r): r is ClusterRow =>
                !!r && typeof (r as ClusterRow).label === 'string'
                && typeof (r as ClusterRow).count === 'number')
            : undefined
```

and include `clusters` in the `setProposal({...})` object. Add `clusters?: ClusterRow[]` to the `ProposalState` type in `panels.ts` (import type from `../contracts.ts`).

- [ ] **Step 2: Render the rows**

In `ProposalCard.tsx`, after the summary paragraph:

```tsx
      {proposal.clusters && proposal.clusters.length > 0 && (
        <div className="text-xs font-mono bg-bg-elevated border border-border-subtle rounded-lg px-2 py-1.5 max-h-40 overflow-y-auto">
          {proposal.clusters.map((row) => (
            <div key={row.label} className="flex items-center gap-2 py-0.5">
              <span className="w-5 text-accent-amber font-semibold">{row.label}</span>
              <span className="w-16 text-right text-text-secondary">{row.count.toLocaleString()}</span>
              <span className={
                row.verdict === 'junk' ? 'w-16 text-red-400' :
                row.verdict === 'structure' ? 'w-16 text-green-400' : 'w-16 text-text-dim'
              }>
                {row.verdict === 'junk' ? 'delete' : row.verdict === 'structure' ? 'keep' : 'unsure'}
              </span>
              <span className="flex-1 truncate text-text-secondary">{row.reason ?? ''}</span>
            </div>
          ))}
        </div>
      )}
```

Add to `KIND_ICONS`: `delete_clusters: Eraser`. Add the title case to `proposalTitle.ts`: `delete_clusters: 'Delete junk clusters'` (match that file's existing structure). Update the adjust-input placeholder to also fit the batch case: `placeholder="Adjust it — e.g. keep B, it's a shed"`.

- [ ] **Step 3: Verify**

Run: `cd frontend && npx tsc -b && npm run lint && npx vitest run src/agent`
Expected: clean/pass. Also run the root-level `npx tsc -b` if `src/` builds separately (`npm run build` covers it).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/agent/ws-client.ts frontend/src/agent/panels.ts src/ui/ProposalCard.tsx src/ui/proposalTitle.ts
git commit -m "feat(ui): batch cluster rows on the ProposalCard"
```

---

### Task 10: Retire dead paths + prompt/docs alignment

**Files:**
- Delete: `backend/agent/closed_loops.py` (+ its tests if any: `grep -rn "closed_loops" backend/`)
- Modify: `backend/agent/system_prompt.py` (SKILLS `cleanup_scene` entry; `stage_tools` survey_capture exclusion)
- Modify: `backend/agent/tests/test_cleanup_prompt.py` (assertions track the new recipe)
- Modify: `CLAUDE.md` (What Works / Known Issues), `README.md` agent section one-liner if needed

**Interfaces:**
- Produces: Clean freeform model tool list no longer contains `survey_capture` (it was exposed by accident — `tools.py:75-76` says loop-dispatched only); `cleanup_scene` skill entry describes the app-run routine.

- [ ] **Step 1: Update the skill entry**

Replace the `cleanup_scene` SKILLS entry with:

```python
    {
        "name": "cleanup_scene",
        "stage": "clean",
        "description": "Full reviewed cleanup: app-computed crop, then a judgment tour of junk candidates you approve as one batch.",
        "recipe": "APP-RUN ROUTINE — the app drives this end to end (crop proposal, "
                  "gridded noise survey, cluster judgment tour, one batch approval). "
                  "If asked to clean the whole scene, tell the operator to click the "
                  "cleanup_scene pill; do not attempt the routine tool-by-tool.",
    },
```

- [ ] **Step 2: Exclude survey_capture from the freeform Clean tool list**

In `system_prompt.py`, find `stage_tools()` (lines ~49-54) and add `"survey_capture"` to the excluded set for BOTH stages' model-visible lists (it is loop/controller-dispatched only). Check `test_stage_gating.py` and update its expected tool lists/counts.

- [ ] **Step 3: Fix the prompt CI**

`backend/agent/tests/test_cleanup_prompt.py` asserts the old recipe (`get_core_bounds`, `propose_decision(kind='crop_outside_box')`, no `select_by_brush`). Update to assert the new recipe contains `"APP-RUN ROUTINE"` and does NOT contain `get_core_bounds` or `select_by_brush`.

- [ ] **Step 4: Delete `closed_loops.py`**

Run `grep -rn "closed_loops" backend/ frontend/ src/` — remove the file and every dangling import/test. If `capabilities.py` or `__init__.py` reference it, prune those references.

- [ ] **Step 5: Update docs**

- `CLAUDE.md` → "What Works": replace the cleanup bullet's description with the judgment-tour flow (one sentence: crop card → gridded survey & marks → cluster tour with forced verdicts → one batch card → verified deletions). Move "Cleanup-flow model behavior untuned" in Known Issues to say tuning now means grid size / tint / instruction phrasing on the live local model.
- `README.md` → in "The Cleaner (Clean stage)" section, adjust the prose to the tour flow (the diagram stays valid: propose → review → gated edit).

- [ ] **Step 6: Full suites + build**

Run: `pytest -q` → all pass
Run: `cd frontend && npx tsc -b && npm run lint && npx vitest run` → clean
Run: `npm run build` → clean

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "chore(agent): retire closed_loops + freeform cleanup recipe; docs to judgment-tour flow"
```

---

## Self-Review (performed while writing)

- **Spec coverage:** phase 1 (Task 6 `_phase1_crop`), phase 2 (Tasks 4+6), phase 3 (Tasks 1+2+6), phase 4 (Task 7 tour incl. look_closer cap + unsure default), phase 5 (Task 7 batch + adjust flips + void-on-change skip), phase 6 (Task 7 summary + narration via `_say` throughout), model-call contract (Task 5), contracts v0.3→landed as v0.7 additions (Task 3 — the spec's "v0.3" was a nominal number; the registry docstring is already at v0.6, so the additions land as v0.7), routing (Task 8), batch card (Task 9), closed_loops deletion + survey_capture exposure fix (Task 10), acceptance's worst-case-model path (Task 6 `test_phase3_stats_cluster_survives_model_silence`, Task 7 unsure tests).
- **Type consistency:** `Cluster` fields used by controller match Task 1's dataclass; `ask_forced` signature identical in Tasks 5/6/7; `splat_arrays()` dict keys consistent (Tasks 6/8); `ClusterRow` fields match the contract rows (Tasks 3/9); `CleanupConfig` values match Global Constraints caps.
- **Placeholders:** none — every step carries code or an exact command; the two "read the file first" notes (fixture reuse in Task 8, contracts.ts structure in Task 3) are deliberate adapt-to-local-style points with the intent pinned by tests.

## Execution note

Live-model tuning (grid size vs. 3×3, tint color visibility on drone scenes, instruction phrasing for the local Qwen-VL) is expected manual iteration AFTER this plan lands, per spec §7 — not part of any task's acceptance.
