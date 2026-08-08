"""Scene-hull carve (v0.8.1): the model outlines the ACTUAL scene per survey
view; code carves the keep-set by reprojecting splat centers through the
recorded poses. Reasoning leads, statistics are the floor — these tests drive
the deterministic half with scripted boxes."""
import numpy as np

from backend.analysis.scene_hull import apply_hull
from backend.analysis.subject import find_subject


def _building_scene(n=2000, seed=0):
    rng = np.random.default_rng(seed)
    means = rng.uniform(-0.5, 0.5, size=(n, 3))
    opacity = np.full(n, 0.9)
    ids = np.arange(n, dtype=np.int64)
    return means, opacity, ids


def _pose():
    # Render-space camera at z=8 looking at the origin: the whole building
    # lands near the center of the frame (u,v ~ 0.5 +- 0.11).
    return {"position": [0.0, 0.0, 8.0], "target": [0.0, 0.0, 0.0],
            "fov": 60.0, "aspect": 1.0}


def _subject(means, opacity, ids):
    s = find_subject(means, opacity, ids)
    assert s is not None
    return s


def test_full_frame_boxes_change_nothing():
    means, opacity, ids = _building_scene()
    s = _subject(means, opacity, ids)
    views = [{"pose": _pose(), "box": (0.0, 0.0, 1.0, 1.0)}] * 3
    out = apply_hull(s, means, ids, views)
    assert [len(l) for l in out.level_ids] == [len(l) for l in s.level_ids]


def test_left_half_box_carves_the_right_half_away():
    means, opacity, ids = _building_scene()
    s = _subject(means, opacity, ids)
    # Model says the scene is only the LEFT half of every view. Render x =
    # backend x, so u < 0.5 <=> backend x < 0.
    views = [{"pose": _pose(), "box": (0.0, 0.0, 0.5, 1.0)}] * 3
    out = apply_hull(s, means, ids, views, pads=(0.0,) * 5)
    kept = out.level_ids[out.default_level]
    kept_x = means[np.isin(ids, kept)][:, 0]
    assert len(kept) > 0
    assert kept_x.max() < 0.05                 # right half is gone
    # nesting still holds
    for a, b in zip(out.level_ids, out.level_ids[1:]):
        assert np.isin(a, b).all()


def test_pads_widen_the_kept_band_monotonically():
    means, opacity, ids = _building_scene()
    s = _subject(means, opacity, ids)
    views = [{"pose": _pose(), "box": (0.0, 0.0, 0.5, 1.0)}] * 3
    out = apply_hull(s, means, ids, views, pads=(-0.04, -0.02, 0.0, 0.05, 0.2))
    assert out.counts[0] < out.counts[2] < out.counts[4]


def test_unusable_boxes_fall_back_to_the_statistical_subject():
    """Boxes that carve (almost) everything away must not produce a
    near-empty keep-set — the statistical subject stands."""
    means, opacity, ids = _building_scene()
    s = _subject(means, opacity, ids)
    views = [{"pose": _pose(), "box": (0.0, 0.0, 0.01, 0.01)}] * 3
    out = apply_hull(s, means, ids, views)
    assert out is s


def test_no_views_is_a_no_op():
    means, opacity, ids = _building_scene()
    s = _subject(means, opacity, ids)
    assert apply_hull(s, means, ids, []) is s


def test_splats_seen_by_no_view_are_not_kept():
    """Out-of-frustum splats can't be vouched for by any outline — they are
    junk by construction (the survey frames the scene)."""
    means, opacity, ids = _building_scene()
    # a far blob BEHIND the camera in render space (backend z = -20 -> render
    # z = +20, camera sits at z = 8 looking toward -z)
    blob = np.array([[0.0, 0.0, -20.0]]) + np.random.default_rng(1).normal(0, 0.05, (200, 3))
    means = np.vstack([means, blob])
    opacity = np.full(len(means), 0.9)
    ids = np.arange(len(means), dtype=np.int64)
    s = _subject(means, opacity, ids)
    views = [{"pose": _pose(), "box": (0.0, 0.0, 1.0, 1.0)}] * 3
    out = apply_hull(s, means, ids, views)
    assert not np.isin(ids[2000:], out.level_ids[-1]).any()
