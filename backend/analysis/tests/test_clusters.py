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
