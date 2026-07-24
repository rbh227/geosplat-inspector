"""What actually survives a cube crop, and what would survive under stricter
membership tests.

`crop_bbox` keeps a Gaussian when its CENTER is inside the box. A needle whose
center is inside but whose extent reaches far outside still renders as a spike.
This measures the alternatives on the real scene, so the choice is made on
numbers rather than on the look of one screenshot.

Run from this directory:
    ../../.venv-api/bin/python crop_membership_variants.py ../../public/demos/iona_park.ply
"""
from __future__ import annotations

import sys
import numpy as np
from core_candidates_probe import read_ply, sigmoid, voxelize, components, fit_box

VISIBILITY_ALPHA = 0.10   # backend/contracts/constants.py
NEEDLE_RATIO = 10.0       # ratio > 10 counts as a needle
OVERSIZED_SCENE_FRAC = 0.05

path = sys.argv[1] if len(sys.argv) > 1 else "../../public/demos/iona_park.ply"
arr, props = read_ply(path)
n = len(arr)

# Full-scene columns (no striding: membership counts must be exact).
xyz = np.stack([arr["x"], arr["y"], arr["z"]], axis=1).astype(np.float32)
op = sigmoid(np.asarray(arr["opacity"], dtype=np.float32))
scale = np.exp(np.stack([arr["scale_0"], arr["scale_1"], arr["scale_2"]], axis=1).astype(np.float32))
max_axis = scale.max(axis=1)
min_axis = np.maximum(scale.min(axis=1), 1e-9)
ratio = max_axis / min_axis
visible = op >= VISIBILITY_ALPHA
core_n = int(visible.sum())
diag = float(np.linalg.norm(xyz.max(axis=0) - xyz.min(axis=0)))

print(f"scene {path}")
print(f"  splats {n:,}   visible core (op>={VISIBILITY_ALPHA}) {core_n:,} ({100*core_n/n:.2f}%)")
print(f"  needles (ratio>{NEEDLE_RATIO}) {int((ratio>NEEDLE_RATIO).sum()):,}"
      f"   oversized (max_axis>{OVERSIZED_SCENE_FRAC}*diag={OVERSIZED_SCENE_FRAC*diag:.2f})"
      f" {int((max_axis > OVERSIZED_SCENE_FRAC*diag).sum()):,}")
print(f"  max_axis: med {np.median(max_axis):.4f}  p99 {np.percentile(max_axis,99):.4f}"
      f"  max {max_axis.max():.2f}\n")

# --- the box: grown candidate from the spec (peak component + 1 diagonal) ----
stride = max(1, n // 100_000)
s_xyz = xyz[::stride]
s_op = op[::stride]
solid = s_xyz[s_op >= 0.3].astype(np.float64)
keys, counts = voxelize(solid)
comps = components(counts, max(3, max(counts.values()) * 0.08))
peak_box = fit_box(solid[np.isin(keys, list(comps[0]))])
d = np.linalg.norm(peak_box[1] - peak_box[0])
c = (peak_box[0] + peak_box[1]) / 2
box = fit_box(solid[np.linalg.norm(solid - c, axis=1) <= d])
lo, hi = box[0].astype(np.float32), box[1].astype(np.float32)
print(f"box (grown candidate): min {np.round(lo,3).tolist()} max {np.round(hi,3).tolist()}\n")

center_in = np.all((xyz >= lo) & (xyz <= hi), axis=1)


def extent_in(k: float) -> np.ndarray:
    """Keep only if the splat's k-sigma extent stays inside the box."""
    r = (k * max_axis)[:, None]
    return np.all((xyz - r >= lo) & (xyz + r <= hi), axis=1)


def report(label: str, keep: np.ndarray) -> None:
    kept = int(keep.sum())
    kept_core = int((keep & visible).sum())
    needles_left = int((keep & (ratio > NEEDLE_RATIO)).sum())
    # how far past the box does the worst survivor reach?
    if kept:
        r = max_axis[keep][:, None]
        over = np.maximum((xyz[keep] - r) - lo, 0) + np.maximum((xyz[keep] + r) - hi, 0)
        spill = float(np.abs(over).max())
    else:
        spill = 0.0
    print(f"{label:<38} {kept:>9,} {100*kept/n:>6.1f}%   "
          f"{kept_core:>7,} {100*kept_core/core_n:>6.1f}%   "
          f"{needles_left:>8,}   {spill:>8.2f}")


print(f"{'variant':<38} {'splats kept':>9} {'':>7}   {'core kept':>7} {'':>7}   "
      f"{'needles':>8}   {'spill':>8}")
print("-" * 96)
report("center only (crop_bbox today)", center_in)
for k in (1.0, 2.0, 3.0):
    report(f"extent-aware, k={k} sigma", extent_in(k))
report("center + drop needles(ratio>10)", center_in & (ratio <= NEEDLE_RATIO))
report("center + drop oversized", center_in & (max_axis <= OVERSIZED_SCENE_FRAC * diag))
report("center + needles + oversized", center_in & (ratio <= NEEDLE_RATIO)
       & (max_axis <= OVERSIZED_SCENE_FRAC * diag))
report("center + opacity>=0.1", center_in & visible)
report("center + needles + opacity>=0.1", center_in & (ratio <= NEEDLE_RATIO) & visible)
print("\nspill = furthest any surviving splat's 1-sigma extent reaches past the box (world units)")
print(f"box diagonal for reference: {float(np.linalg.norm(hi-lo)):.2f}")
