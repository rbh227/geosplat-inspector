"""Editing-engine acceptance tests (ARCHITECTURE.md §6.5, §3 reversibility, R3)."""

from __future__ import annotations

import numpy as np
import pytest

from backend.analysis.editing import EditingEngine
from backend.analysis.metrics import compute_metrics, outlier_indices
from backend.contracts.constants import UNDO_STACK_MAX

_MUTABLE = ("alive", "means", "scales_raw", "quats", "opacity_raw", "f_dc", "f_rest")


def _snapshot(model) -> dict:
    return {a: getattr(model, a).copy() for a in _MUTABLE}


def _assert_equal(model, snap: dict) -> None:
    for a, before in snap.items():
        np.testing.assert_array_equal(getattr(model, a), before, err_msg=f"array {a} not restored")


# --- the flagship spatial guarantee --------------------------------------- #


def test_remove_outliers_lowers_outlier_fraction(messy_model):
    before = compute_metrics(messy_model)["spatial"]["outlierFraction"]
    eng = EditingEngine(messy_model)
    res = eng.remove_outliers()
    assert res["removed"] > 0
    after = compute_metrics(messy_model)["spatial"]["outlierFraction"]
    assert after < before


def test_remove_outliers_removes_exactly_the_predicate_set(messy_model):
    expected = set(int(i) for i in outlier_indices(messy_model))
    before_alive = messy_model.alive.copy()
    EditingEngine(messy_model).remove_outliers()
    removed = set(int(i) for i in np.where(before_alive & ~messy_model.alive)[0])
    assert removed == expected


# --- reversibility: every op fully reverts via undo ----------------------- #

def _ops():
    """Each op as (name, callable(engine)). Run against the synth model."""
    return [
        ("opacity_threshold", lambda e: e.opacity_threshold(0.6)),
        ("remove_outliers", lambda e: e.remove_outliers()),
        ("prune_oversized", lambda e: e.prune_oversized(0.01)),
        ("remove_needles", lambda e: e.remove_needles(1.2)),
        # crop_bbox / crop_sphere were DELETED with the crop-box flow (v0.8.2)
        ("recolor", lambda e: e.recolor({"mode": "all"}, [0.2, 0.4, 0.6])),
        ("adjust_opacity", lambda e: e.adjust_opacity({"mode": "all"}, 0.5)),
        ("truncate_sh", lambda e: e.truncate_sh(1)),
    ]


@pytest.mark.parametrize("name,op", _ops(), ids=[n for n, _ in _ops()])
def test_op_fully_reverts(synth_model, name, op):
    snap = _snapshot(synth_model)
    eng = EditingEngine(synth_model)
    op(eng)
    eng.undo()
    _assert_equal(synth_model, snap)


@pytest.mark.parametrize("name,op", _ops(), ids=[n for n, _ in _ops()])
def test_op_redo_roundtrip(synth_model, name, op):
    eng = EditingEngine(synth_model)
    op(eng)
    after_op = _snapshot(synth_model)
    eng.undo()
    eng.redo()
    _assert_equal(synth_model, after_op)


def test_destructive_op_auto_snapshots(synth_model):
    eng = EditingEngine(synth_model)
    assert eng.history.depth == 0
    eng.opacity_threshold(0.6)
    assert eng.history.depth == 1  # snapshotted before mutating


def test_sequential_ops_revert_in_lifo_order(messy_model):
    snap = _snapshot(messy_model)
    eng = EditingEngine(messy_model)
    eng.opacity_threshold(0.05)
    eng.remove_needles()
    eng.remove_outliers()
    eng.undo()
    eng.undo()
    eng.undo()
    _assert_equal(messy_model, snap)


# --- memory bounded across 50+ sequential edits --------------------------- #


def test_memory_bounded_across_many_edits(synth_model):
    eng = EditingEngine(synth_model)
    n_edits = UNDO_STACK_MAX + 15  # exceed the cap
    for i in range(n_edits):
        # alternate cheap attribute edits so each records a small diff
        eng.recolor({"mode": "all"}, [0.1 * (i % 5), 0.2, 0.3])
    # stack is capped: depth never exceeds UNDO_STACK_MAX
    assert eng.history.depth == UNDO_STACK_MAX
    # bounded memory: each patch only stores its touched rows (not full history)
    per_edit_cap = synth_model.f_dc.nbytes * 4  # before+after of one full-array recolor, slack
    assert eng.history.nbytes() <= UNDO_STACK_MAX * per_edit_cap
    # we can still undo exactly the retained edits, then it stops
    undone = 0
    while eng.history.undo():
        undone += 1
    assert undone == UNDO_STACK_MAX
