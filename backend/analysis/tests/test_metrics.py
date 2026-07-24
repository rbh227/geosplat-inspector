"""Metrics-engine acceptance tests (ARCHITECTURE.md §6.4, R3)."""

from __future__ import annotations

import numpy as np

from backend.analysis.metrics import (
    compute_metrics,
    list_problem_regions,
    outlier_indices,
    outlier_mask,
)


def test_schema_complete(messy_model):
    m = compute_metrics(messy_model)
    assert set(m) == {
        "gaussianCount", "opacity", "scale", "spatial",
        "bounds", "color", "computedAt", "region",
    }
    assert set(m["opacity"]) == {"histogram", "nearTransparentFraction", "mean", "median"}
    assert set(m["scale"]) == {"histogram", "oversizedFraction", "axisRatio"}
    assert set(m["scale"]["axisRatio"]) == {"histogram", "needleFraction"}
    assert set(m["spatial"]) == {"nnDistance", "outlierFraction", "density"}
    assert set(m["spatial"]["nnDistance"]) == {"mean", "std", "histogram"}
    assert len(m["opacity"]["histogram"]) == 50
    assert len(m["bounds"]["min"]) == 3 and len(m["color"]["dcMean"]) == 3


def test_fractions_elevated_vs_clean(clean_model, messy_model):
    """nearTransparent / outlier / needle fractions are clearly elevated in messy."""
    c = compute_metrics(clean_model)
    d = compute_metrics(messy_model)

    # Clean is well-behaved on the absolute-threshold metrics: ~0.
    assert c["opacity"]["nearTransparentFraction"] < 0.01
    assert c["scale"]["axisRatio"]["needleFraction"] < 0.01
    # outlierFraction uses a statistical mean+2*std cutoff, so a uniform scene still
    # has a small (~2-3%) tail baseline — it is never exactly 0.
    assert c["spatial"]["outlierFraction"] < 0.05

    # messy is clearly elevated (80 floaters / 60 outliers / 60 needles of 1200)
    assert d["opacity"]["nearTransparentFraction"] > 0.03
    assert d["spatial"]["outlierFraction"] > 0.03
    assert d["scale"]["axisRatio"]["needleFraction"] > 0.03

    # and clearly higher than clean on each axis (outliers need a real margin over
    # the statistical baseline, not just any epsilon).
    assert d["opacity"]["nearTransparentFraction"] > c["opacity"]["nearTransparentFraction"] + 0.03
    assert d["spatial"]["outlierFraction"] > c["spatial"]["outlierFraction"] + 0.03
    assert d["scale"]["axisRatio"]["needleFraction"] > c["scale"]["axisRatio"]["needleFraction"] + 0.03


def test_outlier_predicate_matches_metric_count(messy_model):
    """The exported predicate returns exactly the set the metric counts (R3)."""
    m = compute_metrics(messy_model)
    frac = m["spatial"]["outlierFraction"]
    count = m["gaussianCount"]
    metric_count = round(frac * count)

    idx = outlier_indices(messy_model)
    assert len(idx) == metric_count

    # mask fraction and metric fraction agree exactly (same function, same params)
    mask = outlier_mask(messy_model)
    assert abs(mask.mean() - frac) < 1e-9


def test_problem_regions_ranked(messy_model):
    regions = list_problem_regions(messy_model)
    assert len(regions) > 0
    # sorted by absolute problem count, descending
    counts = [r["badCount"] for r in regions]
    assert counts == sorted(counts, reverse=True)
    for r in regions:
        assert set(r["bbox"]) == {"min", "max"}
        bd = r["breakdown"]
        assert r["badCount"] <= bd["floaters"] + bd["outliers"] + bd["needles"] + bd["oversized"]
        assert 0.0 <= r["score"] <= 1.0


def test_region_restriction_shrinks_count(messy_model):
    full = compute_metrics(messy_model)
    mn, mx = messy_model.bounds()
    mid = (np.asarray(mn) + np.asarray(mx)) / 2
    region = {"min": [float(x) for x in mn], "max": [float(x) for x in mid]}
    sub = compute_metrics(messy_model, region=region)
    assert sub["region"] == region
    assert sub["gaussianCount"] < full["gaussianCount"]


# --------------------------------------------------------------------------
# Oversize normalisation must survive far-flung outliers (v0.6)
# --------------------------------------------------------------------------


def test_robust_scene_diag_ignores_far_outliers():
    """A few distant Gaussians must not inflate the oversize basis.

    Real failure: public/demos/iona_park.ply has a raw bounding-box diagonal of
    284,977 world units around a ~10-unit subject, so
    OVERSIZED_SCENE_FRAC * diag = 14,248 and prune_oversized matched nothing
    while the render was full of 20-unit streaks.
    """
    import numpy as np
    import pytest

    from backend.analysis.metrics import robust_scene_diag

    bulk = np.random.default_rng(0).uniform(-1, 1, size=(1000, 3))
    tight = robust_scene_diag(bulk)

    strays = np.concatenate([bulk, np.array([[1e5, 1e5, 1e5], [-1e5, -1e5, -1e5]])])
    assert robust_scene_diag(strays) == pytest.approx(tight, rel=0.05), (
        "two distant splats moved the scene scale"
    )
    raw = float(np.linalg.norm(strays.max(axis=0) - strays.min(axis=0)))
    assert raw > 1000 * tight, "raw diagonal should be the badly-behaved one"


def test_robust_scene_diag_empty():
    import numpy as np

    from backend.analysis.metrics import robust_scene_diag

    assert robust_scene_diag(np.zeros((0, 3))) == 0.0


def test_oversized_fraction_survives_a_far_outlier(clean_model):
    """oversizedFraction stays meaningful when one Gaussian sits far away."""
    import numpy as np

    base = compute_metrics(clean_model)["scale"]["oversizedFraction"]
    clean_model.means[0] = np.array([5e4, 5e4, 5e4], dtype=clean_model.means.dtype)
    after = compute_metrics(clean_model)["scale"]["oversizedFraction"]
    # One relocated splat must not collapse the metric to a flat zero.
    assert after >= base
