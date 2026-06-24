"""SplatModel interface (ARCHITECTURE.md §6.3). Frozen."""

from __future__ import annotations

from typing import Protocol

import numpy as np


class SplatModel(Protocol):
    """Protocol for the Gaussian splat data model.

    Parallel numpy arrays indexed by Gaussian id, storing raw/stored values.
    Agent 1 implements; Agents 2 & 3 import.
    """

    means: np.ndarray           # (N,3) float32
    scales_raw: np.ndarray      # (N,3) log-space
    quats: np.ndarray           # (N,4) wxyz, unnormalized
    opacity_raw: np.ndarray     # (N,)  logit
    f_dc: np.ndarray            # (N,3)
    f_rest: np.ndarray          # (N,K) K depends on sh_degree
    alive: np.ndarray           # (N,)  bool — soft-delete mask
    sh_degree: int

    @classmethod
    def load(cls, path: str) -> SplatModel: ...

    def export(self, path: str) -> None: ...

    def alive_indices(self) -> np.ndarray: ...

    def apply_mask(self, keep: np.ndarray) -> None: ...

    def opacity(self, alive_only: bool = True) -> np.ndarray: ...

    def scale(self, alive_only: bool = True) -> np.ndarray: ...

    def color(self, alive_only: bool = True) -> np.ndarray: ...

    def knn(self, k: int) -> tuple[np.ndarray, np.ndarray]: ...

    def bounds(self) -> tuple[np.ndarray, np.ndarray]: ...
