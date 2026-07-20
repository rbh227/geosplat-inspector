"""v0.2 ID-based editing: delete/keep by original id, shared-history undo (AE4)."""

from __future__ import annotations

import numpy as np

from backend.analysis.editing import EditingEngine
from backend.analysis.selection import resolve_selection


def _alive_ids(model) -> set[int]:
    return set(int(i) for i in model.alive_indices())


def test_ids_selection_mode_filters_dead_and_out_of_range(clean_model):
    eng = EditingEngine(clean_model)
    eng.delete_by_ids([0, 1])
    n = clean_model.alive.shape[0]
    resolved = resolve_selection(clean_model, {"mode": "ids", "ids": [0, 1, 2, -5, n + 100]})
    assert set(int(i) for i in resolved) == {2}


def test_delete_by_ids_removes_exactly_those_ids(clean_model):
    eng = EditingEngine(clean_model)
    before = _alive_ids(clean_model)
    res = eng.delete_by_ids([3, 7, 11])
    assert res["removed"] == 3
    assert _alive_ids(clean_model) == before - {3, 7, 11}


def test_keep_only_ids_inverts(clean_model):
    eng = EditingEngine(clean_model)
    res = eng.keep_only_ids([1, 2, 3])
    assert res["after"] == 3
    assert _alive_ids(clean_model) == {1, 2, 3}


def test_delete_by_ids_idempotent_on_dead_and_unknown(clean_model):
    eng = EditingEngine(clean_model)
    eng.delete_by_ids([5])
    depth_before = eng.history.depth
    # id 5 already dead, id out of range: effectively empty -> no-op, no history
    res = eng.delete_by_ids([5, 10_000_000])
    assert res["removed"] == 0
    assert eng.history.depth == depth_before


def test_empty_delete_records_nothing(clean_model):
    eng = EditingEngine(clean_model)
    depth_before = eng.history.depth
    res = eng.delete_by_ids([])
    assert res["removed"] == 0
    assert eng.history.depth == depth_before


def test_empty_keep_is_noop_not_delete_everything(clean_model):
    eng = EditingEngine(clean_model)
    before = int(clean_model.alive.sum())
    res = eng.keep_only_ids([])
    assert res["after"] == before


def test_undo_restores_exactly_the_id_delete(clean_model):
    eng = EditingEngine(clean_model)
    before = _alive_ids(clean_model)
    eng.delete_by_ids([2, 4])
    assert eng.undo()["ok"]
    assert _alive_ids(clean_model) == before


def test_interleaved_agent_and_manual_edits_undo_lifo(clean_model):
    """AE4: one shared history — agent op then manual ID delete undo in LIFO order."""
    eng = EditingEngine(clean_model)
    start = _alive_ids(clean_model)

    eng.opacity_threshold(0.05)          # agent-style op
    after_agent = _alive_ids(clean_model)
    eng.delete_by_ids(sorted(after_agent)[:2])  # manual ID delete
    after_manual = _alive_ids(clean_model)
    assert after_manual != after_agent

    assert eng.undo()["ok"]              # reverts the manual delete only
    assert _alive_ids(clean_model) == after_agent
    assert eng.undo()["ok"]              # reverts the agent op
    assert _alive_ids(clean_model) == start


def test_selection_state_counts_and_bbox(clean_model):
    eng = EditingEngine(clean_model)
    ids = sorted(_alive_ids(clean_model))[:5]
    state = eng.selection_state(ids)
    assert state["count"] == 5
    pts = clean_model.means[np.asarray(ids)]
    assert state["bbox"]["min"] == [float(v) for v in pts.min(axis=0)]
    assert state["bbox"]["max"] == [float(v) for v in pts.max(axis=0)]
    assert eng.selection_state([])["count"] == 0
