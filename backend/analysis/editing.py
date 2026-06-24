"""Editing engine (ARCHITECTURE.md §6.5 backend edit tools, Tier 3).

All edits are deterministic numpy masking over the ``SplatModel``. Deletions go through
the contract's ``apply_mask`` (AND-only); attribute edits (recolor / opacity / SH) write
the public arrays in place. Every destructive op snapshots first via :class:`History` and
returns before/after counts, so the agent can always undo (§3 reversibility).

The outlier filter imports the single criterion from :mod:`.metrics` (R3); it never
re-derives "what is an outlier".
"""

from __future__ import annotations

import numpy as np

from backend.contracts.constants import (
    NEEDLE_RATIO,
    OUTLIER_K,
    OUTLIER_STD_RATIO,
    OVERSIZED_SCENE_FRAC,
    SH_C0,
)
from backend.contracts.splat_model import SplatModel

from .history import ArrayPatch, History
from .metrics import _axis_ratio, outlier_mask
from .selection import resolve_selection

# f_rest coefficients kept per colour channel at each SH degree (channel-grouped layout).
_KEEP_PER_CHANNEL = {0: 0, 1: 3, 2: 8, 3: 15}
_REST_PER_CHANNEL = {0: 0, 1: 3, 2: 8, 3: 15}  # cumulative == keep, by construction
_EPS = 1e-6


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, _EPS, 1.0 - _EPS)
    return np.log(p / (1.0 - p))


class EditingEngine:
    """Stateful editor: owns a :class:`History` for one scene's model."""

    def __init__(self, model: SplatModel, history: History | None = None) -> None:
        self.model = model
        self.history = history or History(model)

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #

    def _counts(self, before: int, after: int, extra: dict | None = None) -> dict:
        out = {"before": before, "after": after, "removed": before - after}
        if extra:
            out.update(extra)
        return out

    def _apply_keep(self, keep_full: np.ndarray) -> dict:
        """Snapshot the alive diff, AND ``keep_full`` into alive, record, return counts."""
        before_alive = self.model.alive
        before = int(before_alive.sum())
        removed = np.where(before_alive & ~keep_full)[0]
        patch = self.history.capture("alive", removed)  # before-values: all True
        self.model.apply_mask(keep_full)
        self.history.record([self.history.finalize(patch)])  # after-values: all False
        after = int(self.model.alive.sum())
        return self._counts(before, after)

    def _mutate(self, attr: str, rows: np.ndarray, new_values: np.ndarray,
                cols: np.ndarray | None = None) -> int:
        """Snapshot, write ``new_values`` at rows/cols, record. Returns affected count."""
        if rows.size == 0:
            return 0
        patch: ArrayPatch = self.history.capture(attr, rows, cols)
        arr = getattr(self.model, attr)
        if cols is None:
            arr[rows] = new_values
        else:
            arr[np.ix_(rows, cols)] = new_values
        self.history.record([self.history.finalize(patch)])
        return int(rows.size)

    def _scene_diag(self) -> float:
        if int(self.model.alive.sum()) == 0:
            return 0.0
        mn, mx = self.model.bounds()
        return float(np.linalg.norm(mx - mn))

    # ------------------------------------------------------------------ #
    # deletion ops (alive mask) — each returns before/after counts
    # ------------------------------------------------------------------ #

    def opacity_threshold(self, min_alpha: float) -> dict:
        """Prune Gaussians whose activated opacity is below ``min_alpha``."""
        keep = np.ones(self.model.alive.shape, dtype=bool)
        alive_idx = self.model.alive_indices()
        below = self.model.opacity(alive_only=True) < min_alpha
        keep[alive_idx[below]] = False
        return self._apply_keep(keep)

    def remove_outliers(self, k: int = OUTLIER_K, std_ratio: float = OUTLIER_STD_RATIO) -> dict:
        """Prune spatial outliers using the single criterion from :mod:`.metrics` (R3)."""
        keep = np.ones(self.model.alive.shape, dtype=bool)
        alive_idx = self.model.alive_indices()
        mask = outlier_mask(self.model, k, std_ratio)
        if mask.size:
            keep[alive_idx[mask]] = False
        return self._apply_keep(keep)

    def prune_oversized(self, max_axis_scene_frac: float = OVERSIZED_SCENE_FRAC) -> dict:
        """Prune Gaussians whose largest axis exceeds ``frac`` of the scene diagonal."""
        keep = np.ones(self.model.alive.shape, dtype=bool)
        alive_idx = self.model.alive_indices()
        thresh = max_axis_scene_frac * self._scene_diag()
        over = self.model.scale(alive_only=True).max(axis=1) > thresh
        keep[alive_idx[over]] = False
        return self._apply_keep(keep)

    def remove_needles(self, max_axis_ratio: float = NEEDLE_RATIO) -> dict:
        """Prune needle-like Gaussians (max/min axis ratio above the cutoff)."""
        keep = np.ones(self.model.alive.shape, dtype=bool)
        alive_idx = self.model.alive_indices()
        needle = _axis_ratio(self.model.scale(alive_only=True)) > max_axis_ratio
        keep[alive_idx[needle]] = False
        return self._apply_keep(keep)

    def crop_bbox(self, min: list[float], max: list[float]) -> dict:
        """Keep only Gaussians inside the axis-aligned box."""
        keep = np.ones(self.model.alive.shape, dtype=bool)
        alive_idx = self.model.alive_indices()
        pts = self.model.means[alive_idx]
        mn = np.asarray(min, dtype=np.float32)
        mx = np.asarray(max, dtype=np.float32)
        outside = ~np.all((pts >= mn) & (pts <= mx), axis=1)
        keep[alive_idx[outside]] = False
        return self._apply_keep(keep)

    def crop_sphere(self, center: list[float], radius: float, invert: bool = False) -> dict:
        """Keep Gaussians inside (or, if ``invert``, outside) a sphere."""
        keep = np.ones(self.model.alive.shape, dtype=bool)
        alive_idx = self.model.alive_indices()
        pts = self.model.means[alive_idx]
        d = np.linalg.norm(pts - np.asarray(center, dtype=np.float32), axis=1)
        inside = d <= radius
        drop = inside if invert else ~inside
        keep[alive_idx[drop]] = False
        return self._apply_keep(keep)

    # ------------------------------------------------------------------ #
    # attribute ops (no deletion) — return affected count
    # ------------------------------------------------------------------ #

    def recolor(self, selection: dict, rgb: list[float]) -> dict:
        """Set the DC colour of the selection to ``rgb`` (stored as raw f_dc)."""
        idx = resolve_selection(self.model, selection)
        rgb_arr = np.asarray(rgb, dtype=np.float32)
        dc = (rgb_arr - 0.5) / SH_C0
        new_vals = np.broadcast_to(dc, (idx.size, 3)).astype(np.float32)
        affected = self._mutate("f_dc", idx, new_vals)
        alive = int(self.model.alive.sum())
        return self._counts(alive, alive, {"affected": affected})

    def adjust_opacity(self, selection: dict, factor: float) -> dict:
        """Multiply activated opacity of the selection by ``factor`` (stored as logit)."""
        idx = resolve_selection(self.model, selection)
        if idx.size == 0:
            alive = int(self.model.alive.sum())
            return self._counts(alive, alive, {"affected": 0})
        cur = 1.0 / (1.0 + np.exp(-self.model.opacity_raw[idx]))
        new_raw = _logit(cur * factor).astype(np.float32)
        affected = self._mutate("opacity_raw", idx, new_raw)
        alive = int(self.model.alive.sum())
        return self._counts(alive, alive, {"affected": affected})

    def truncate_sh(self, degree: int) -> dict:
        """Zero all f_rest coefficients above ``degree`` (channel-grouped layout)."""
        alive = int(self.model.alive.sum())
        rest = self.model.f_rest
        rest_count = rest.shape[1]
        if rest_count == 0 or degree >= self.model.sh_degree:
            return self._counts(alive, alive, {"affected": 0})
        per_channel = rest_count // 3
        keep = _KEEP_PER_CHANNEL[degree]
        cols = [c * per_channel + j for c in range(3) for j in range(keep, per_channel)]
        cols_arr = np.asarray(cols, dtype=int)
        rows = np.arange(rest.shape[0])
        new_vals = np.zeros((rows.size, cols_arr.size), dtype=np.float32)
        self._mutate("f_rest", rows, new_vals, cols=cols_arr)
        return self._counts(alive, alive, {"affected": int(cols_arr.size)})

    # ------------------------------------------------------------------ #
    # history passthrough
    # ------------------------------------------------------------------ #

    def snapshot(self) -> dict:
        """Explicit checkpoint. Destructive ops already auto-snapshot, so this is a
        no-op marker kept for tool-contract symmetry."""
        return {"ok": True, "depth": self.history.depth}

    def undo(self) -> dict:
        ok = self.history.undo()
        return {"ok": ok, "alive": int(self.model.alive.sum())}

    def redo(self) -> dict:
        ok = self.history.redo()
        return {"ok": ok, "alive": int(self.model.alive.sum())}
