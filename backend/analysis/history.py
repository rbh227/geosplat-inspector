"""Diff-based snapshot / undo / redo (ARCHITECTURE.md §3.3, §6.2 UNDO_STACK_MAX).

Every destructive edit records a *reverse patch*: only the indices it touched and
their before/after values. Undo restores the before-values; redo restores the
after-values. Memory is bounded by the patch sizes (not full-scene copies) and by the
``UNDO_STACK_MAX`` cap on the undo stack, so an arbitrarily long edit session stays
bounded.

Patches address public ``SplatModel`` arrays directly. For ``alive`` this is what makes
undo possible at all: the contract's ``apply_mask`` is AND-only (it can delete but not
restore), so un-deleting requires writing ``alive`` back. The model's k-NN cache is keyed
on ``alive``'s bytes, so in-place restores are picked up automatically on the next query.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from backend.contracts.constants import UNDO_STACK_MAX
from backend.contracts.splat_model import SplatModel


@dataclass
class ArrayPatch:
    """A reversible change to one model array.

    ``rows`` indexes the first axis; ``cols`` (optional) indexes the second. ``before``
    and ``after`` hold the values at those positions before and after the edit.
    """

    attr: str
    rows: np.ndarray
    cols: np.ndarray | None
    before: np.ndarray
    after: np.ndarray

    def _apply(self, model: SplatModel, values: np.ndarray) -> None:
        arr = getattr(model, self.attr)
        if self.cols is None:
            arr[self.rows] = values
        else:
            arr[np.ix_(self.rows, self.cols)] = values

    def undo(self, model: SplatModel) -> None:
        self._apply(model, self.before)

    def redo(self, model: SplatModel) -> None:
        self._apply(model, self.after)

    def nbytes(self) -> int:
        return int(self.before.nbytes + self.after.nbytes + self.rows.nbytes)


# A single edit may touch several arrays (e.g. a future combined op); a Change groups them.
Change = list[ArrayPatch]


class History:
    """Bounded undo/redo stack of reverse patches for one scene."""

    def __init__(self, model: SplatModel, maxlen: int = UNDO_STACK_MAX) -> None:
        self.model = model
        self.maxlen = maxlen
        self._undo: list[Change] = []
        self._redo: list[Change] = []

    # -- recording -------------------------------------------------------- #

    def record(self, change: Change) -> None:
        """Push a completed change; truncate to ``maxlen`` and invalidate redo."""
        if not change:
            return
        self._undo.append(change)
        if len(self._undo) > self.maxlen:
            self._undo.pop(0)  # drop oldest — bounded memory
        self._redo.clear()

    def capture(self, attr: str, rows: np.ndarray, cols: np.ndarray | None = None) -> ArrayPatch:
        """Snapshot current values at ``rows``/``cols`` (call BEFORE mutating)."""
        arr = getattr(self.model, attr)
        rows = np.asarray(rows)
        before = (arr[rows] if cols is None else arr[np.ix_(rows, cols)]).copy()
        return ArrayPatch(attr=attr, rows=rows, cols=cols, before=before, after=before)

    def finalize(self, patch: ArrayPatch) -> ArrayPatch:
        """Record the after-values (call AFTER mutating) and return the patch."""
        arr = getattr(self.model, patch.attr)
        patch.after = (arr[patch.rows] if patch.cols is None else arr[np.ix_(patch.rows, patch.cols)]).copy()
        return patch

    # -- traversal -------------------------------------------------------- #

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        change = self._undo.pop()
        for patch in reversed(change):
            patch.undo(self.model)
        self._redo.append(change)
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        change = self._redo.pop()
        for patch in change:
            patch.redo(self.model)
        self._undo.append(change)
        return True

    # -- introspection ---------------------------------------------------- #

    @property
    def depth(self) -> int:
        return len(self._undo)

    def nbytes(self) -> int:
        return sum(p.nbytes() for change in self._undo + self._redo for p in change)
