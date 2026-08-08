"""Stub engine — a real (if simplified) numpy implementation of the `Scene`
and `SceneBackend` seams so the transport layer is testable end-to-end on a
real `.ply` before Agents 1/2 land.

It loads a standard INRIA Gaussian `.ply`, computes a structurally-complete
`Metrics` (the frozen §6.4 schema), applies edits to the alive mask with
snapshot/undo/redo, and exports a valid `.ply` of the alive set. Replace with
the composed (SplatModel + metrics/editing/history) engine at integration —
routes never change.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone

import numpy as np

from backend.contracts import (
    HIST_BINS,
    NEEDLE_RATIO,
    OUTLIER_K,
    OUTLIER_STD_RATIO,
    OVERSIZED_SCENE_FRAC,
    SH_C0,
    UNDO_STACK_MAX,
    VISIBILITY_ALPHA,
    Metrics,
)

try:  # spatial queries: use scipy if available, else a numpy fallback
    from scipy.spatial import cKDTree as _KDTree
except Exception:  # pragma: no cover - exercised only without scipy
    _KDTree = None


# --------------------------------------------------------------------------- #
# Minimal header-driven PLY I/O (auto-detects f_rest count -> SH degree).
# This duplicates *no* frozen contract; the real loader is Agent 1's.
# --------------------------------------------------------------------------- #

def _parse_header(f) -> tuple[int, list[str]]:
    line = f.readline().decode("ascii").strip()
    if line != "ply":
        raise ValueError("Not a PLY file")
    n = 0
    props: list[str] = []
    while True:
        line = f.readline().decode("ascii").strip()
        if line.startswith("element vertex"):
            n = int(line.split()[-1])
        elif line.startswith("property float"):
            props.append(line.split()[-1])
        elif line.startswith("property "):
            props.append(line.split()[-1])
        elif line == "end_header":
            break
    if n <= 0:
        raise ValueError("PLY header has no vertices")
    return n, props


def _count_f_rest(props: list[str]) -> int:
    return sum(1 for p in props if p.startswith("f_rest_"))


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-6, 1.0 - 1e-6)
    return np.log(p / (1.0 - p))


class StubScene:
    """A loaded scene backed by parallel numpy arrays + an alive mask."""

    def __init__(
        self,
        means: np.ndarray,
        normals: np.ndarray,
        f_dc: np.ndarray,
        f_rest: np.ndarray,
        opacity_raw: np.ndarray,
        scales_raw: np.ndarray,
        quats: np.ndarray,
        sh_degree: int,
    ) -> None:
        self.means = means
        self.normals = normals
        self.f_dc = f_dc
        self.f_rest = f_rest
        self.opacity_raw = opacity_raw
        self.scales_raw = scales_raw
        self.quats = quats
        self.sh_degree = sh_degree
        n = means.shape[0]
        self.alive = np.ones(n, dtype=bool)
        self._undo: list[dict] = []
        self._redo: list[dict] = []

    # ---- loading ---------------------------------------------------------- #
    @classmethod
    def load(cls, path: str) -> "StubScene":
        with open(path, "rb") as f:
            n, props = _parse_header(f)
            num_props = len(props)
            buf = np.frombuffer(
                f.read(n * num_props * 4), dtype="<f4"
            ).reshape(n, num_props).astype(np.float32)
        idx = {name: i for i, name in enumerate(props)}
        k = _count_f_rest(props)
        sh_degree = {0: 0, 9: 1, 24: 2, 45: 3}.get(k, 3)

        def col(name: str) -> np.ndarray:
            return buf[:, idx[name]]

        means = np.stack([col("x"), col("y"), col("z")], axis=1)
        if "nx" in idx:
            normals = np.stack([col("nx"), col("ny"), col("nz")], axis=1)
        else:
            normals = np.zeros((n, 3), dtype=np.float32)
        f_dc = np.stack([col("f_dc_0"), col("f_dc_1"), col("f_dc_2")], axis=1)
        f_rest = (
            np.stack([col(f"f_rest_{i}") for i in range(k)], axis=1)
            if k
            else np.zeros((n, 0), dtype=np.float32)
        )
        opacity_raw = col("opacity")
        scales_raw = np.stack(
            [col("scale_0"), col("scale_1"), col("scale_2")], axis=1
        )
        quats = np.stack(
            [col("rot_0"), col("rot_1"), col("rot_2"), col("rot_3")], axis=1
        )
        return cls(
            means.copy(), normals.copy(), f_dc.copy(), f_rest.copy(),
            opacity_raw.copy(), scales_raw.copy(), quats.copy(), sh_degree,
        )

    # ---- history ---------------------------------------------------------- #
    def _snapshot_state(self) -> dict:
        return {
            "alive": self.alive.copy(),
            "f_dc": self.f_dc.copy(),
            "f_rest": self.f_rest.copy(),
            "opacity_raw": self.opacity_raw.copy(),
        }

    def _restore(self, snap: dict) -> None:
        self.alive = snap["alive"]
        self.f_dc = snap["f_dc"]
        self.f_rest = snap["f_rest"]
        self.opacity_raw = snap["opacity_raw"]

    def _push_snapshot(self) -> None:
        self._undo.append(self._snapshot_state())
        if len(self._undo) > UNDO_STACK_MAX:
            self._undo.pop(0)
        self._redo.clear()

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._snapshot_state())
        self._restore(self._undo.pop())
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._snapshot_state())
        self._restore(self._redo.pop())
        return True

    def count(self) -> int:
        return int(self.alive.sum())

    def alive_ids(self) -> list[int]:
        return [int(i) for i in np.where(self.alive)[0]]

    # ---- activated accessors (alive-only) --------------------------------- #
    def _ai(self) -> np.ndarray:
        return np.where(self.alive)[0]

    def _opacity(self, i: np.ndarray) -> np.ndarray:
        return _sigmoid(self.opacity_raw[i])

    def _scale(self, i: np.ndarray) -> np.ndarray:
        return np.exp(self.scales_raw[i])

    def _color(self, i: np.ndarray) -> np.ndarray:
        return 0.5 + SH_C0 * self.f_dc[i]

    # ---- editing ---------------------------------------------------------- #
    def edit(
        self, op: str, params: dict, selection: dict | None = None
    ) -> tuple[int, int]:
        before = self.count()
        self._push_snapshot()  # every destructive op snapshots first
        handler = getattr(self, f"_op_{op}", None)
        if handler is None:
            self._undo.pop()  # nothing happened; don't keep a dead snapshot
            raise ValueError(f"Unknown edit op: {op!r}")
        handler(params or {}, selection)
        return before, self.count()

    def _keep(self, mask_over_alive: np.ndarray) -> None:
        """AND `mask_over_alive` (indexed over current alive ids) into alive."""
        alive_idx = self._ai()
        drop = alive_idx[~mask_over_alive]
        self.alive[drop] = False

    def _op_opacity_threshold(self, p: dict, _sel) -> None:
        i = self._ai()
        self._keep(self._opacity(i) >= float(p["min_alpha"]))

    def _op_prune_oversized(self, p: dict, _sel) -> None:
        i = self._ai()
        frac = float(p["max_axis_scene_frac"])
        diag = self._diagonal(i)
        max_axis = self._scale(i).max(axis=1)
        self._keep(max_axis <= frac * diag)

    def _op_remove_needles(self, p: dict, _sel) -> None:
        i = self._ai()
        s = self._scale(i)
        ratio = s.max(axis=1) / np.clip(s.min(axis=1), 1e-9, None)
        self._keep(ratio <= float(p["max_axis_ratio"]))

    def _op_remove_outliers(self, p: dict, _sel) -> None:
        i = self._ai()
        k = int(p.get("k", OUTLIER_K))
        std_ratio = float(p.get("std_ratio", OUTLIER_STD_RATIO))
        d = _mean_knn_distance(self.means[i], k)
        thresh = d.mean() + std_ratio * d.std()
        self._keep(d <= thresh)

    def _op_recolor(self, p: dict, sel) -> None:
        i = self._select(sel)
        rgb = np.asarray(p["rgb"], dtype=np.float32)
        self.f_dc[i] = (rgb - 0.5) / SH_C0

    def _op_adjust_opacity(self, p: dict, sel) -> None:
        i = self._select(sel)
        factor = float(p["factor"])
        new = np.clip(_sigmoid(self.opacity_raw[i]) * factor, 1e-6, 1 - 1e-6)
        self.opacity_raw[i] = _logit(new)

    def _op_truncate_sh(self, p: dict, _sel) -> None:
        degree = int(p["degree"])
        keep = {0: 0, 1: 9, 2: 24, 3: 45}.get(degree, self.f_rest.shape[1])
        if keep < self.f_rest.shape[1]:
            self.f_rest[:, keep:] = 0.0

    def _op_snapshot(self, _p: dict, _sel) -> None:
        pass  # the snapshot already happened in edit()

    def _select(self, sel: dict | None) -> np.ndarray:
        """Resolve a selection to alive Gaussian ids. Stub: all-alive or bbox."""
        i = self._ai()
        if not sel:
            return i
        if "min" in sel and "max" in sel:
            lo = np.asarray(sel["min"], dtype=np.float32)
            hi = np.asarray(sel["max"], dtype=np.float32)
            inside = np.all((self.means[i] >= lo) & (self.means[i] <= hi), axis=1)
            return i[inside]
        return i

    def _diagonal(self, i: np.ndarray) -> float:
        pts = self.means[i]
        if pts.size == 0:
            return 1.0
        return float(np.linalg.norm(pts.max(axis=0) - pts.min(axis=0)) or 1.0)

    # ---- metrics ---------------------------------------------------------- #
    def metrics(self, region: dict | None = None) -> Metrics:
        i = self._ai()
        if region and "min" in region and "max" in region:
            lo = np.asarray(region["min"], dtype=np.float32)
            hi = np.asarray(region["max"], dtype=np.float32)
            inside = np.all((self.means[i] >= lo) & (self.means[i] <= hi), axis=1)
            i = i[inside]

        n = int(i.size)
        op = self._opacity(i) if n else np.zeros(0, np.float32)
        sc = self._scale(i) if n else np.zeros((0, 3), np.float32)
        col = self._color(i) if n else np.zeros((0, 3), np.float32)
        pts = self.means[i] if n else np.zeros((0, 3), np.float32)

        if n:
            mn = pts.min(axis=0)
            mx = pts.max(axis=0)
            diag = float(np.linalg.norm(mx - mn) or 1.0)
            vol = float(np.prod(np.clip(mx - mn, 1e-9, None)))
        else:
            mn = mx = np.zeros(3, np.float32)
            diag, vol = 1.0, 0.0

        max_axis = sc.max(axis=1) if n else np.zeros(0)
        ratio = (
            sc.max(axis=1) / np.clip(sc.min(axis=1), 1e-9, None)
            if n else np.zeros(0)
        )
        nn = _mean_knn_distance(pts, 1) if n > 1 else np.zeros(max(n, 0))
        knn_d = _mean_knn_distance(pts, OUTLIER_K) if n > 1 else np.zeros(max(n, 0))
        outlier_thresh = (
            knn_d.mean() + OUTLIER_STD_RATIO * knn_d.std() if n > 1 else 0.0
        )

        def hist(a: np.ndarray, lo: float, hi: float) -> list[int]:
            if a.size == 0:
                return [0] * HIST_BINS
            return np.histogram(a, bins=HIST_BINS, range=(lo, hi))[0].astype(int).tolist()

        return {
            "gaussianCount": n,
            "opacity": {
                "histogram": hist(op, 0.0, 1.0),
                "nearTransparentFraction": float((op < VISIBILITY_ALPHA).mean()) if n else 0.0,
                "mean": float(op.mean()) if n else 0.0,
                "median": float(np.median(op)) if n else 0.0,
            },
            "scale": {
                "histogram": hist(max_axis, 0.0, float(max_axis.max()) if n else 1.0),
                "oversizedFraction": float((max_axis > OVERSIZED_SCENE_FRAC * diag).mean()) if n else 0.0,
                "axisRatio": {
                    "histogram": hist(ratio, 1.0, float(ratio.max()) if n else 10.0),
                    "needleFraction": float((ratio > NEEDLE_RATIO).mean()) if n else 0.0,
                },
            },
            "spatial": {
                "nnDistance": {
                    "mean": float(nn.mean()) if nn.size else 0.0,
                    "std": float(nn.std()) if nn.size else 0.0,
                    "histogram": hist(nn, 0.0, float(nn.max()) if nn.size else 1.0),
                },
                "outlierFraction": float((knn_d > outlier_thresh).mean()) if n > 1 else 0.0,
                "density": float(n / vol) if vol > 0 else 0.0,
            },
            "bounds": {
                "min": [float(x) for x in mn],
                "max": [float(x) for x in mx],
                "volume": vol,
            },
            "color": {
                "dcMean": [float(x) for x in (col.mean(axis=0) if n else np.zeros(3))],
                "dcStd": [float(x) for x in (col.std(axis=0) if n else np.zeros(3))],
            },
            "computedAt": datetime.now(timezone.utc).isoformat(),
            "region": region,
        }

    # ---- export ----------------------------------------------------------- #
    def export(self, path: str) -> None:
        i = self._ai()
        n = int(i.size)
        k = self.f_rest.shape[1]
        header = ["ply", "format binary_little_endian 1.0", f"element vertex {n}"]
        for c in ("x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2"):
            header.append(f"property float {c}")
        for j in range(k):
            header.append(f"property float f_rest_{j}")
        for c in ("opacity", "scale_0", "scale_1", "scale_2",
                  "rot_0", "rot_1", "rot_2", "rot_3"):
            header.append(f"property float {c}")
        header.append("end_header")
        block = np.concatenate(
            [
                self.means[i], self.normals[i], self.f_dc[i], self.f_rest[i],
                self.opacity_raw[i][:, None], self.scales_raw[i], self.quats[i],
            ],
            axis=1,
        ).astype("<f4")
        with open(path, "wb") as f:
            f.write(("\n".join(header) + "\n").encode("ascii"))
            block.tofile(f)


def _mean_knn_distance(pts: np.ndarray, k: int) -> np.ndarray:
    """Mean distance to the k nearest neighbours (excluding self) per point."""
    n = pts.shape[0]
    if n <= 1:
        return np.zeros(n)
    k = min(k, n - 1)
    if _KDTree is not None:
        tree = _KDTree(pts)
        dist, _ = tree.query(pts, k=k + 1)  # +1: nearest is self (dist 0)
        return dist[:, 1:].mean(axis=1)
    # numpy fallback (fine for the small stub scenes)
    out = np.empty(n)
    for j in range(n):
        d = np.linalg.norm(pts - pts[j], axis=1)
        d[j] = np.inf
        out[j] = np.partition(d, k)[:k].mean()
    return out


class StubBackend:
    """`SceneBackend` factory. Replace with the composed real engine."""

    def load(self, path: str) -> StubScene:
        return StubScene.load(path)


__all__ = ["StubBackend", "StubScene"]
