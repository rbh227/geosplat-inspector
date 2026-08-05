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
    # the median±k·MAD box hugs the building, not the far blob
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


# ---------------------------------------------------------------------------
# Task 2: projection + mark resolution
# ---------------------------------------------------------------------------
import pytest

from backend.analysis.clusters import cell_index, project_to_cells, resolve_marks


def _pose_looking_at_origin(position=(0, 0, 10)):
    return {"position": list(position), "target": [0, 0, 0], "fov": 60.0, "aspect": 1.0}


def test_cell_index_convention():
    assert cell_index("A1") == 0          # top-left
    assert cell_index("D1") == 3          # top-right
    assert cell_index("A4") == 12         # bottom-left
    assert cell_index("B3") == 9          # row 3 (index 2) * 4 + col B (index 1)
    with pytest.raises(ValueError):
        cell_index("E1")
    with pytest.raises(ValueError):
        cell_index("A9")


def test_project_center_point_lands_in_middle_cells():
    # backend point at origin, camera on render +Z axis looking at origin:
    # backend (0,0,0) -> render (0,0,0) -> screen center -> a middle cell.
    means = np.array([[0.0, 0.0, 0.0]])
    cells = project_to_cells(means, _pose_looking_at_origin(), grid=4)
    assert cells[0] in (cell_index("B2"), cell_index("C2"), cell_index("B3"), cell_index("C3"))


def test_project_behind_camera_is_minus_one():
    means = np.array([[0.0, 0.0, 0.0]])
    pose = {"position": [0, 0, -10], "target": [0, 0, -20], "fov": 60.0, "aspect": 1.0}
    assert project_to_cells(means, pose)[0] == -1


def test_render_space_flip_is_applied():
    # backend Y-down: backend (0, -3, 0) is render (0, +3, 0) = UPPER half of the
    # screen for a camera at render +Z looking at origin -> row 1 or 2, not 3/4.
    means = np.array([[0.0, -3.0, 0.0]])
    cells = project_to_cells(means, _pose_looking_at_origin(), grid=4)
    assert cells[0] != -1
    assert cells[0] // 4 <= 1   # top half


def _modal_label(cells, mask):
    hit = cells[mask]
    hit = hit[hit >= 0]
    idx = int(np.bincount(hit).argmax())
    return "ABCD"[idx % 4] + str(idx // 4 + 1)


def test_resolve_marks_boosts_hit_cluster_and_spawns_model_cluster():
    # scene: building + one far blob (statistical cluster) + one MIST patch that
    # voxel clustering missed (too sparse) but the model marks.
    mist = _blob([0, 0, 6], n=40, spread=0.8, seed=7)    # sparse -> no stats cluster
    far = _blob([10, 0, 0], n=80, seed=8)
    means, opacity, ids = _scene([far, mist])
    mn, mx = core_box(means)
    stats = find_clusters(means, opacity, ids, mn, mx, min_splats=50)
    assert len(stats) == 1                               # only the far blob

    # camera that sees the far blob: at render-space (10, 0, 8) looking at it.
    pose_far = {"position": [10, 0, 8], "target": [10, 0, 0], "fov": 60.0, "aspect": 1.0}
    far_mask = np.zeros(len(means), bool)
    far_mask[2000:2080] = True                           # the far blob rows
    far_label = _modal_label(project_to_cells(means, pose_far), far_mask)

    # camera that sees the mist: mist sits at backend (0,0,6) = render (0,0,-6).
    pose_mist = {"position": [0, 0, -12], "target": [0, 0, -6], "fov": 60.0, "aspect": 1.0}
    mist_mask = np.zeros(len(means), bool)
    mist_mask[2080:2120] = True
    mist_label = _modal_label(project_to_cells(means, pose_mist), mist_mask)

    merged = resolve_marks(
        means, opacity, ids,
        [{"cells": [far_label], "pose": pose_far},
         {"cells": [mist_label], "pose": pose_mist}],
        stats, mn, mx, min_splats=10,
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


def test_resolve_marks_drops_invalid_labels():
    means, opacity, ids = _scene([_blob([10, 0, 0], n=80, seed=9)])
    mn, mx = core_box(means)
    stats = find_clusters(means, opacity, ids, mn, mx)
    merged = resolve_marks(
        means, opacity, ids,
        [{"cells": ["Z9", "", 42], "pose": _pose_looking_at_origin()}],
        stats, mn, mx,
    )
    assert len(merged) == len(stats)
