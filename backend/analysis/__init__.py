"""Analysis boundary (Agent 2): metrics engine, editing engine, selection, history.

Builds against the frozen contracts and Agent 1's ``SplatModel``. The outlier criterion
lives once in :func:`outlier_mask` and is imported by the editing engine (R3).
"""

from .clusters import (
    Cluster,
    cell_index,
    core_box,
    find_clusters,
    project_to_cells,
    resolve_marks,
)
from .editing import EditingEngine
from .history import ArrayPatch, Change, History
from .metrics import (
    compute_metrics,
    list_problem_regions,
    outlier_indices,
    outlier_mask,
    per_point_mean_knn,
)
from .selection import resolve_selection

__all__ = [
    "Cluster",
    "cell_index",
    "core_box",
    "find_clusters",
    "project_to_cells",
    "resolve_marks",
    "EditingEngine",
    "History",
    "ArrayPatch",
    "Change",
    "compute_metrics",
    "list_problem_regions",
    "outlier_mask",
    "outlier_indices",
    "per_point_mean_knn",
    "resolve_selection",
]
