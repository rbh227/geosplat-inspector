"""Concrete SplatModel implementation (ARCHITECTURE.md §6.3).

Loads INRIA-format .ply files via plyfile, stores raw values in parallel
numpy arrays, and provides activated accessors + spatial queries.
"""

from __future__ import annotations

import numpy as np
from plyfile import PlyData, PlyElement
from scipy.spatial import cKDTree

from backend.contracts.constants import SH_C0


# SH rest coefficient counts by degree
_SH_REST_BY_DEGREE = {0: 0, 1: 9, 2: 24, 3: 45}
_DEGREE_BY_REST = {v: k for k, v in _SH_REST_BY_DEGREE.items()}


class GaussianSplatModel:
    """Concrete implementation of the SplatModel protocol."""

    def __init__(
        self,
        means: np.ndarray,
        scales_raw: np.ndarray,
        quats: np.ndarray,
        opacity_raw: np.ndarray,
        f_dc: np.ndarray,
        f_rest: np.ndarray,
        sh_degree: int,
        normals: np.ndarray | None = None,
    ) -> None:
        n = means.shape[0]
        assert means.shape == (n, 3)
        assert scales_raw.shape == (n, 3)
        assert quats.shape == (n, 4)
        assert opacity_raw.shape == (n,)
        assert f_dc.shape == (n, 3)
        assert f_rest.shape[0] == n

        self.means = means.astype(np.float32)
        self.scales_raw = scales_raw.astype(np.float32)
        self.quats = quats.astype(np.float32)
        self.opacity_raw = opacity_raw.astype(np.float32)
        self.f_dc = f_dc.astype(np.float32)
        self.f_rest = f_rest.astype(np.float32)
        self.sh_degree = sh_degree
        self.alive = np.ones(n, dtype=bool)
        self._normals = normals.astype(np.float32) if normals is not None else np.zeros((n, 3), dtype=np.float32)

        # Lazy spatial cache
        self._kdtree: cKDTree | None = None
        self._kdtree_alive_hash: int | None = None

    # ── Loader ──

    @classmethod
    def load(cls, path: str) -> GaussianSplatModel:
        """Load an INRIA-format .ply file, auto-detecting the field set."""
        plydata = PlyData.read(path)
        vertex = plydata["vertex"]
        props = {p.name for p in vertex.properties}
        n = vertex.count

        # Positions (required)
        means = np.stack([vertex["x"], vertex["y"], vertex["z"]], axis=-1)

        # Normals (optional, often zero)
        if {"nx", "ny", "nz"} <= props:
            normals = np.stack([vertex["nx"], vertex["ny"], vertex["nz"]], axis=-1)
        else:
            normals = None

        # DC color (required)
        f_dc = np.stack([vertex["f_dc_0"], vertex["f_dc_1"], vertex["f_dc_2"]], axis=-1)

        # SH rest: auto-detect count from header
        rest_count = 0
        while f"f_rest_{rest_count}" in props:
            rest_count += 1
        if rest_count not in _DEGREE_BY_REST:
            raise ValueError(
                f"Unexpected f_rest count {rest_count}; "
                f"expected one of {list(_DEGREE_BY_REST.keys())}"
            )
        sh_degree = _DEGREE_BY_REST[rest_count]

        if rest_count > 0:
            f_rest = np.stack(
                [vertex[f"f_rest_{i}"] for i in range(rest_count)], axis=-1
            )
        else:
            f_rest = np.zeros((n, 0), dtype=np.float32)

        # Opacity (logit)
        opacity_raw = np.array(vertex["opacity"], dtype=np.float32)

        # Scale (log-space)
        scales_raw = np.stack(
            [vertex["scale_0"], vertex["scale_1"], vertex["scale_2"]], axis=-1
        )

        # Rotation quaternion (w,x,y,z)
        quats = np.stack(
            [vertex["rot_0"], vertex["rot_1"], vertex["rot_2"], vertex["rot_3"]],
            axis=-1,
        )

        return cls(
            means=means,
            scales_raw=scales_raw,
            quats=quats,
            opacity_raw=opacity_raw,
            f_dc=f_dc,
            f_rest=f_rest,
            sh_degree=sh_degree,
            normals=normals,
        )

    # ── Exporter ──

    def export(self, path: str) -> None:
        """Write a valid INRIA .ply of alive Gaussians in exact header order."""
        idx = self.alive_indices()
        n = idx.shape[0]

        # Build structured array with exact INRIA property order
        dtype_fields: list[tuple[str, str]] = []
        # pos
        for name in ("x", "y", "z"):
            dtype_fields.append((name, "<f4"))
        # normals
        for name in ("nx", "ny", "nz"):
            dtype_fields.append((name, "<f4"))
        # f_dc
        for i in range(3):
            dtype_fields.append((f"f_dc_{i}", "<f4"))
        # f_rest
        rest_count = _SH_REST_BY_DEGREE[self.sh_degree]
        for i in range(rest_count):
            dtype_fields.append((f"f_rest_{i}", "<f4"))
        # opacity
        dtype_fields.append(("opacity", "<f4"))
        # scale
        for i in range(3):
            dtype_fields.append((f"scale_{i}", "<f4"))
        # rot
        for i in range(4):
            dtype_fields.append((f"rot_{i}", "<f4"))

        arr = np.empty(n, dtype=dtype_fields)
        arr["x"] = self.means[idx, 0]
        arr["y"] = self.means[idx, 1]
        arr["z"] = self.means[idx, 2]
        arr["nx"] = self._normals[idx, 0]
        arr["ny"] = self._normals[idx, 1]
        arr["nz"] = self._normals[idx, 2]
        for i in range(3):
            arr[f"f_dc_{i}"] = self.f_dc[idx, i]
        for i in range(rest_count):
            arr[f"f_rest_{i}"] = self.f_rest[idx, i]
        arr["opacity"] = self.opacity_raw[idx]
        for i in range(3):
            arr[f"scale_{i}"] = self.scales_raw[idx, i]
        for i in range(4):
            arr[f"rot_{i}"] = self.quats[idx, i]

        el = PlyElement.describe(arr, "vertex")
        PlyData([el], byte_order="<").write(path)

    # ── Alive mask ──

    def alive_indices(self) -> np.ndarray:
        return np.where(self.alive)[0]

    def apply_mask(self, keep: np.ndarray) -> None:
        """AND a keep-mask into alive. keep is indexed over ALL Gaussians."""
        assert keep.shape == self.alive.shape
        assert keep.dtype == bool
        self.alive &= keep
        self._invalidate_spatial()

    # ── Activated accessors ──

    def opacity(self, alive_only: bool = True) -> np.ndarray:
        """Sigmoid of raw opacity."""
        raw = self.opacity_raw[self.alive] if alive_only else self.opacity_raw
        return 1.0 / (1.0 + np.exp(-raw))

    def scale(self, alive_only: bool = True) -> np.ndarray:
        """Exp of raw scale."""
        raw = self.scales_raw[self.alive] if alive_only else self.scales_raw
        return np.exp(raw)

    def color(self, alive_only: bool = True) -> np.ndarray:
        """DC color: 0.5 + C0 * f_dc → RGB [0,1] (clamped)."""
        dc = self.f_dc[self.alive] if alive_only else self.f_dc
        return np.clip(0.5 + SH_C0 * dc, 0.0, 1.0)

    # ── Spatial queries ──

    def _invalidate_spatial(self) -> None:
        self._kdtree = None
        self._kdtree_alive_hash = None

    def _ensure_kdtree(self) -> cKDTree:
        alive_hash = hash(self.alive.data.tobytes())
        if self._kdtree is None or self._kdtree_alive_hash != alive_hash:
            self._kdtree = cKDTree(self.means[self.alive])
            self._kdtree_alive_hash = alive_hash
        return self._kdtree

    def knn(self, k: int) -> tuple[np.ndarray, np.ndarray]:
        """k-NN over alive positions.

        Returns (distances (M,k), indices (M,k)) where M = alive count.
        Indices are into the alive-only subset.
        """
        tree = self._ensure_kdtree()
        # k+1 because the closest neighbor is the point itself. workers=-1:
        # parallel query — single-threaded, 2M splats × k=17 takes minutes.
        dist, idx = tree.query(tree.data, k=k + 1, workers=-1)
        # Drop self-match (column 0)
        return dist[:, 1:].astype(np.float32), idx[:, 1:]

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        """Axis-aligned bounding box of alive positions."""
        pts = self.means[self.alive]
        return pts.min(axis=0), pts.max(axis=0)
