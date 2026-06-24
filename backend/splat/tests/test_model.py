"""Tests for GaussianSplatModel — acceptance criteria from ARCHITECTURE.md."""

import os
import tempfile
import time

import numpy as np
import pytest
from scipy.spatial import cKDTree

from backend.splat.model import GaussianSplatModel

EXAMPLES = os.path.join(os.path.dirname(__file__), "..", "..", "..", "examples")
CLEAN_PLY = os.path.join(EXAMPLES, "clean.ply")
MESSY_PLY = os.path.join(EXAMPLES, "messy.ply")


# ── Load tests ──


class TestLoad:
    def test_load_clean(self):
        m = GaussianSplatModel.load(CLEAN_PLY)
        assert m.means.shape == (1000, 3)
        assert m.scales_raw.shape == (1000, 3)
        assert m.quats.shape == (1000, 4)
        assert m.opacity_raw.shape == (1000,)
        assert m.f_dc.shape == (1000, 3)
        assert m.f_rest.shape == (1000, 45)
        assert m.sh_degree == 3
        assert m.alive.all()

    def test_load_messy(self):
        m = GaussianSplatModel.load(MESSY_PLY)
        assert m.means.shape[0] == 1200
        assert m.sh_degree == 3

    def test_auto_detect_sh_degree(self):
        m = GaussianSplatModel.load(CLEAN_PLY)
        assert m.sh_degree == 3
        assert m.f_rest.shape[1] == 45


# ── Bit-faithful round-trip (R2) ──


class TestExportRoundTrip:
    def test_bit_faithful_roundtrip(self):
        """load→export→reload must produce identical arrays (R2)."""
        original = GaussianSplatModel.load(CLEAN_PLY)

        with tempfile.NamedTemporaryFile(suffix=".ply", delete=False) as f:
            tmp = f.name
        try:
            original.export(tmp)
            reloaded = GaussianSplatModel.load(tmp)

            np.testing.assert_array_equal(original.means, reloaded.means)
            np.testing.assert_array_equal(original.scales_raw, reloaded.scales_raw)
            np.testing.assert_array_equal(original.quats, reloaded.quats)
            np.testing.assert_array_equal(original.opacity_raw, reloaded.opacity_raw)
            np.testing.assert_array_equal(original.f_dc, reloaded.f_dc)
            np.testing.assert_array_equal(original.f_rest, reloaded.f_rest)
            assert original.sh_degree == reloaded.sh_degree
        finally:
            os.unlink(tmp)

    def test_bit_faithful_file_bytes(self):
        """Exported bytes match original file exactly."""
        original = GaussianSplatModel.load(CLEAN_PLY)

        with tempfile.NamedTemporaryFile(suffix=".ply", delete=False) as f:
            tmp = f.name
        try:
            original.export(tmp)
            with open(CLEAN_PLY, "rb") as a, open(tmp, "rb") as b:
                assert a.read() == b.read(), "Exported file bytes differ from original"
        finally:
            os.unlink(tmp)


# ── Soft-delete + export ──


class TestSoftDelete:
    def test_apply_mask_reduces_alive(self):
        m = GaussianSplatModel.load(CLEAN_PLY)
        assert m.alive.sum() == 1000

        keep = np.ones(1000, dtype=bool)
        keep[:100] = False
        m.apply_mask(keep)

        assert m.alive.sum() == 900
        assert m.alive_indices().shape[0] == 900

    def test_export_after_delete_drops_removed(self):
        m = GaussianSplatModel.load(CLEAN_PLY)
        keep = np.ones(1000, dtype=bool)
        keep[:200] = False
        m.apply_mask(keep)

        with tempfile.NamedTemporaryFile(suffix=".ply", delete=False) as f:
            tmp = f.name
        try:
            m.export(tmp)
            reloaded = GaussianSplatModel.load(tmp)
            assert reloaded.means.shape[0] == 800
            # Verify the remaining positions match
            np.testing.assert_array_equal(
                m.means[m.alive], reloaded.means
            )
        finally:
            os.unlink(tmp)

    def test_successive_masks_and(self):
        m = GaussianSplatModel.load(CLEAN_PLY)
        mask1 = np.ones(1000, dtype=bool)
        mask1[:500] = False
        m.apply_mask(mask1)
        assert m.alive.sum() == 500

        mask2 = np.ones(1000, dtype=bool)
        mask2[500:750] = False
        m.apply_mask(mask2)
        assert m.alive.sum() == 250


# ── Activated accessors ──


class TestAccessors:
    def test_opacity_sigmoid(self):
        m = GaussianSplatModel.load(CLEAN_PLY)
        op = m.opacity()
        assert op.shape[0] == 1000
        assert np.all(op > 0) and np.all(op < 1)

    def test_scale_exp(self):
        m = GaussianSplatModel.load(CLEAN_PLY)
        s = m.scale()
        assert s.shape == (1000, 3)
        assert np.all(s > 0)

    def test_color_range(self):
        m = GaussianSplatModel.load(CLEAN_PLY)
        c = m.color()
        assert c.shape == (1000, 3)
        assert np.all(c >= 0) and np.all(c <= 1)

    def test_alive_only_filtering(self):
        m = GaussianSplatModel.load(CLEAN_PLY)
        keep = np.ones(1000, dtype=bool)
        keep[:500] = False
        m.apply_mask(keep)

        assert m.opacity(alive_only=True).shape[0] == 500
        assert m.opacity(alive_only=False).shape[0] == 1000
        assert m.scale(alive_only=True).shape == (500, 3)
        assert m.color(alive_only=True).shape == (500, 3)


# ── KNN ──


class TestKNN:
    def test_knn_shape(self):
        m = GaussianSplatModel.load(CLEAN_PLY)
        dist, idx = m.knn(k=4)
        assert dist.shape == (1000, 4)
        assert idx.shape == (1000, 4)
        assert np.all(dist >= 0)

    def test_knn_matches_brute_force(self):
        """KNN results must match brute-force on a small subset."""
        m = GaussianSplatModel.load(CLEAN_PLY)
        k = 4
        dist_kd, idx_kd = m.knn(k=k)

        # Brute-force on first 50 points
        pts = m.means[m.alive]
        for i in range(50):
            diffs = pts - pts[i]
            dists = np.linalg.norm(diffs, axis=1)
            sorted_idx = np.argsort(dists)
            bf_idx = sorted_idx[1 : k + 1]  # skip self
            bf_dist = dists[bf_idx]

            np.testing.assert_allclose(
                np.sort(dist_kd[i]), np.sort(bf_dist), rtol=1e-5,
                err_msg=f"KNN mismatch at point {i}",
            )

    def test_knn_after_soft_delete(self):
        """KDTree rebuilds after alive change."""
        m = GaussianSplatModel.load(CLEAN_PLY)
        d1, _ = m.knn(k=4)

        keep = np.ones(1000, dtype=bool)
        keep[:500] = False
        m.apply_mask(keep)

        d2, i2 = m.knn(k=4)
        assert d2.shape == (500, 4)
        # Distances should differ since half the points are gone
        assert d2.shape[0] != d1.shape[0]

    def test_knn_performance_messy(self):
        """Full knn on messy scene (1200) should be well under 1 second."""
        m = GaussianSplatModel.load(MESSY_PLY)
        t0 = time.time()
        m.knn(k=16)
        elapsed = time.time() - t0
        assert elapsed < 1.0, f"KNN took {elapsed:.2f}s on 1200 Gaussians"


# ── Bounds ──


class TestBounds:
    def test_bounds_shape(self):
        m = GaussianSplatModel.load(CLEAN_PLY)
        bmin, bmax = m.bounds()
        assert bmin.shape == (3,)
        assert bmax.shape == (3,)
        assert np.all(bmax >= bmin)

    def test_bounds_after_delete(self):
        m = GaussianSplatModel.load(MESSY_PLY)
        bmin1, bmax1 = m.bounds()

        # Kill outliers (indices 1060-1119 are outliers at distance 4-8)
        keep = np.ones(1200, dtype=bool)
        keep[1060:1120] = False
        m.apply_mask(keep)

        bmin2, bmax2 = m.bounds()
        # Bounds should shrink without the far-away outliers
        vol1 = np.prod(bmax1 - bmin1)
        vol2 = np.prod(bmax2 - bmin2)
        assert vol2 <= vol1
