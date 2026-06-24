"""Selection model (ARCHITECTURE.md §6.5 selection schema).

Resolves a selection spec into full-N Gaussian ids (always a subset of alive).
Modes: ``all`` | ``bbox`` | ``sphere`` | ``predicate`` | ``region``.
"""

from __future__ import annotations

import numpy as np

from backend.contracts.constants import OUTLIER_K
from backend.contracts.splat_model import SplatModel

from .metrics import _axis_ratio, per_point_mean_knn

_OPS = {
    "<": np.less,
    "<=": np.less_equal,
    ">": np.greater,
    ">=": np.greater_equal,
    "==": np.equal,
}


def _predicate_values(model: SplatModel, field: str) -> np.ndarray:
    """Per-alive scalar series for a predicate field (alive order)."""
    if field == "opacity":
        return model.opacity(alive_only=True)
    if field == "scale":
        return model.scale(alive_only=True).max(axis=1)
    if field == "axis_ratio":
        return _axis_ratio(model.scale(alive_only=True))
    if field == "nn_distance":
        return per_point_mean_knn(model, OUTLIER_K)
    raise ValueError(f"unknown predicate field: {field!r}")


def resolve_selection(model: SplatModel, selection: dict) -> np.ndarray:
    """Return full-N Gaussian ids selected by ``selection`` (subset of alive)."""
    mode = selection["mode"]
    alive = model.alive_indices()
    pts = model.means[alive]

    if mode == "all":
        return alive

    if mode in ("bbox", "region"):
        bbox = selection["bbox"] if mode == "bbox" else selection["region"]["bbox"]
        mn = np.asarray(bbox["min"], dtype=np.float32)
        mx = np.asarray(bbox["max"], dtype=np.float32)
        inside = np.all((pts >= mn) & (pts <= mx), axis=1)
        return alive[inside]

    if mode == "sphere":
        sp = selection["sphere"]
        center = np.asarray(sp["center"], dtype=np.float32)
        radius = float(sp["radius"])
        d = np.linalg.norm(pts - center, axis=1)
        inside = d <= radius
        if sp.get("invert"):
            inside = ~inside
        return alive[inside]

    if mode == "predicate":
        pred = selection["predicate"]
        values = _predicate_values(model, pred["field"])
        mask = _OPS[pred["op"]](values, float(pred["value"]))
        return alive[mask]

    raise ValueError(f"unknown selection mode: {mode!r}")
