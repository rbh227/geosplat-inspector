"""Tests for the subject-aware silhouette guard (backend/agent/verify.py).

The guard must judge edit survival by the SOLID (non-near-transparent) core
rather than the raw total count, so that correctly removing the noise majority
on messy outdoor scenes is KEPT, while an edit that destroys the dense subject
is reverted.
"""

from __future__ import annotations

from typing import Any, cast

from backend.contracts import Metrics
from backend.agent.verify import silhouette_intact, solid_core


def _metrics(gaussian_count: int, near_transparent: float) -> Metrics:
    """Minimal Metrics dict with only the fields silhouette_intact reads."""
    m: dict[str, Any] = {
        "gaussianCount": gaussian_count,
        "opacity": {"nearTransparentFraction": near_transparent},
    }
    return cast(Metrics, m)


def test_keeps_edit_that_removes_transparent_majority() -> None:
    # solid core 500 -> 300 (~60% retained) even though total dropped 70%.
    before = _metrics(1000, 0.5)
    after = _metrics(300, 0.0)
    assert silhouette_intact(before, after) is True


def test_reverts_edit_that_destroys_solid_subject() -> None:
    # solid core 900 -> 90 (10% retained) -> revert.
    before = _metrics(1000, 0.1)
    after = _metrics(100, 0.1)
    assert silhouette_intact(before, after) is False


def test_small_removal_is_kept() -> None:
    # Tiny removal: core barely changes -> unchanged keep behavior.
    before = _metrics(1000, 0.2)
    after = _metrics(950, 0.2)
    assert silhouette_intact(before, after) is True


def test_empty_scene_is_kept() -> None:
    before = _metrics(0, 0.0)
    after = _metrics(0, 0.0)
    assert silhouette_intact(before, after) is True


def test_catastrophic_total_drop_reverts_even_with_transparent_majority() -> None:
    # Almost everything deleted (>90% of total) -> backstop reverts regardless
    # of how transparent the removed Gaussians were.
    before = _metrics(1000, 0.9)
    after = _metrics(50, 0.0)
    assert silhouette_intact(before, after) is False


def test_solid_core_helper() -> None:
    assert solid_core(_metrics(1000, 0.5)) == 500.0
    assert solid_core(_metrics(300, 0.0)) == 300.0
    assert solid_core(_metrics(1000, 0.1)) == 900.0


def test_no_solid_core_falls_back_to_total_survival() -> None:
    # Fully transparent scene: no subject to protect, judged by total drop only.
    before = _metrics(1000, 1.0)
    after_kept = _metrics(800, 1.0)   # 20% total drop -> kept
    after_revert = _metrics(50, 1.0)  # 95% total drop -> reverted (backstop)
    assert silhouette_intact(before, after_kept) is True
    assert silhouette_intact(before, after_revert) is False


# --------------------------------------------------------------------------
# Operator-approved operations (v0.6)
#
# `max_total_drop` is measured against the RAW total count, which is a
# meaningless denominator on junk-dominated captures. Measured on
# public/demos/iona_park.ply: 2,000,000 splats of which ~67,000 (3.4%) are
# visible; an opacity sweep there removes ~96% of the scene while retaining
# 100% of the visible core. That is the correct result and the backstop
# reverted it. When the operator has reviewed and approved the exact
# operation, their approval is the subject-protection mechanism; only a
# genuinely catastrophic result may override it.
# --------------------------------------------------------------------------


def test_approved_edit_survives_catastrophic_total_drop() -> None:
    # The real iona_park case: 2M -> 63k, but the visible core is fully kept.
    before = _metrics(2_000_000, 0.9663)
    after = _metrics(63_494, 0.0)
    assert silhouette_intact(before, after) is False, "unapproved: backstop applies"
    assert silhouette_intact(before, after, approved=True) is True


def test_approved_crop_below_half_core_is_kept() -> None:
    # An approved crop that clips some of the subject is the operator's call.
    before = _metrics(1000, 0.0)
    after = _metrics(300, 0.0)
    assert silhouette_intact(before, after) is False
    assert silhouette_intact(before, after, approved=True) is True


def test_approved_edit_that_wipes_the_core_still_reverts() -> None:
    # Nothing visible survives -> catastrophic regardless of approval.
    before = _metrics(1000, 0.0)
    after = _metrics(0, 0.0)
    assert silhouette_intact(before, after, approved=True) is False


def test_approved_edit_leaving_under_one_percent_of_core_reverts() -> None:
    before = _metrics(100_000, 0.0)
    after = _metrics(500, 0.0)  # 0.5% of the core
    assert silhouette_intact(before, after, approved=True) is False


def test_approved_edit_at_the_one_percent_boundary_is_kept() -> None:
    before = _metrics(100_000, 0.0)
    after = _metrics(1_000, 0.0)  # exactly 1% of the core
    assert silhouette_intact(before, after, approved=True) is True


def test_unapproved_behaviour_is_unchanged() -> None:
    before = _metrics(1000, 0.5)
    after = _metrics(300, 0.0)
    assert silhouette_intact(before, after) is True
    assert silhouette_intact(before, after, approved=False) is True
