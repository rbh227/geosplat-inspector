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
