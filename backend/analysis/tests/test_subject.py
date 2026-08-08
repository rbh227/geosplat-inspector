"""Subject lock-on finder (subject-first cleanup, 2026-08-07)."""
import numpy as np

from backend.analysis.subject import find_subject


def _sphere_plus_floaters(n_core=600, n_junk=40, seed=7):
    rng = np.random.default_rng(seed)
    v = rng.normal(size=(n_core, 3))
    core = v / np.linalg.norm(v, axis=1, keepdims=True)  # unit shell
    d = rng.normal(size=(n_junk, 3))
    junk = d / np.linalg.norm(d, axis=1, keepdims=True) * rng.uniform(5, 8, (n_junk, 1))
    means = np.vstack([core, junk])
    opacity = np.full(len(means), 0.9)
    ids = np.arange(len(means), dtype=np.int64)
    return means, opacity, ids


def test_levels_are_nested_and_monotonic():
    s = find_subject(*_sphere_plus_floaters())
    assert s is not None
    assert len(s.level_ids) == 5 and s.default_level == 2
    for a, b in zip(s.level_ids, s.level_ids[1:]):
        assert np.isin(a, b).all()          # tight ⊂ loose
    assert s.counts == [len(l) for l in s.level_ids]


def test_subject_captures_core_and_excludes_floaters():
    means, opacity, ids = _sphere_plus_floaters()
    s = find_subject(means, opacity, ids)
    core_ids = ids[:600]
    junk_ids = ids[600:]
    got = s.level_ids[s.default_level]
    assert np.isin(core_ids, got).mean() >= 0.95     # keeps the sphere
    assert not np.isin(junk_ids, s.level_ids[-1]).any()  # loosest still excludes junk


def test_degenerate_scene_returns_none():
    means = np.random.default_rng(0).normal(size=(10, 3))
    assert find_subject(means, np.full(10, 0.9), np.arange(10)) is None


def test_giant_scale_splats_are_excluded_from_every_level():
    """Live-found (iona_park): streak/needle gaussians up to 2000x the median
    scale sit with their CENTERS inside the dense core, so a center-only test
    keeps them at every level and the slider can never remove them. Splats
    with extreme max-axis scale must be excluded from the keep-set outright."""
    means, opacity, ids = _sphere_plus_floaters()
    scales = np.full((len(means), 3), 0.01)
    scales[:10, 0] = 20.0                      # 10 core-centered giant streaks
    s = find_subject(means, opacity, ids, scales=scales)
    assert s is not None
    assert not np.isin(ids[:10], s.level_ids[-1]).any()
    # the rest of the core still keeps
    assert np.isin(ids[10:600], s.level_ids[s.default_level]).mean() >= 0.95


def test_levels_span_a_real_density_range():
    """Live-found: dilation-only levels moved ~8% of splats end to end on a
    real drone scene — an invisible slider. The tightest level must keep
    meaningfully fewer splats than the loosest."""
    rng = np.random.default_rng(3)
    core = rng.normal(0.0, 0.3, size=(1500, 3))     # dense blob
    halo = rng.normal(0.0, 1.2, size=(600, 3))      # sparse attached fringe
    means = np.vstack([core, halo])
    opacity = np.full(len(means), 0.9)
    ids = np.arange(len(means), dtype=np.int64)
    s = find_subject(means, opacity, ids)
    assert s is not None
    assert s.counts[0] > 0
    assert s.counts[0] <= 0.9 * s.counts[-1]        # a visible swing, not 1%


def test_extreme_outliers_do_not_degrade_the_voxel_scale():
    """Live-found (iona_park.ply, 2M splats): a handful of far outliers
    inflated the raw bbox ~1000x, so the voxel cell became huge, the whole
    scene collapsed into a few voxels, and the 'subject' was 99.8% of the
    scene INCLUDING the junk. The cell must derive from a robust (median/MAD)
    radius so nearby floaters still resolve as junk."""
    means, opacity, ids = _sphere_plus_floaters()
    far = np.array([
        [3000.0, 0.0, 0.0], [-2800.0, 100.0, 0.0], [0.0, 3100.0, 50.0],
        [0.0, -2900.0, 0.0], [50.0, 0.0, 3050.0],
    ])
    means = np.vstack([means, far])
    opacity = np.full(len(means), 0.9)
    ids = np.arange(len(means), dtype=np.int64)
    s = find_subject(means, opacity, ids)
    assert s is not None
    core_ids = ids[:600]
    junk_ids = ids[600:]
    assert np.isin(core_ids, s.level_ids[s.default_level]).mean() >= 0.95
    # the moderate floaters AND the extreme outliers stay out at every level
    assert not np.isin(junk_ids, s.level_ids[-1]).any()
