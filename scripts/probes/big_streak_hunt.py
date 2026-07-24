"""Which splats actually draw the streaks?

A needle is elongated but may be tiny. What paints a streak across the viewport
is a splat with a large ABSOLUTE major axis. prune_oversized already targets
this, but its threshold is OVERSIZED_SCENE_FRAC * scene_diagonal, and the raw
diagonal is corrupted by far-flung outliers (~285,000 units here), so the
threshold lands at ~14,248 and nothing qualifies.

This measures a robust-scale version: threshold on the extent of the actual
subject, and report exactly what each cut removes and costs.

Run from this directory:
    ../../.venv-api/bin/python big_streak_hunt.py ../../public/demos/iona_park.ply
"""
from __future__ import annotations

import sys
import numpy as np
from core_candidates_probe import read_ply, sigmoid, voxelize, components, fit_box

VISIBILITY_ALPHA = 0.10
NEEDLE_RATIO = 10.0

path = sys.argv[1] if len(sys.argv) > 1 else "../../public/demos/iona_park.ply"
arr, _ = read_ply(path)
n = len(arr)
xyz = np.stack([arr["x"], arr["y"], arr["z"]], axis=1).astype(np.float32)
op = sigmoid(np.asarray(arr["opacity"], dtype=np.float32))
scale = np.exp(np.stack([arr["scale_0"], arr["scale_1"], arr["scale_2"]], axis=1).astype(np.float32))
max_axis = scale.max(axis=1)
ratio = max_axis / np.maximum(scale.min(axis=1), 1e-9)
visible = op >= VISIBILITY_ALPHA
surface = visible & (ratio <= NEEDLE_RATIO)

raw_diag = float(np.linalg.norm(xyz.max(axis=0) - xyz.min(axis=0)))
p_lo, p_hi = np.percentile(xyz, 1, axis=0), np.percentile(xyz, 99, axis=0)
robust_diag = float(np.linalg.norm(p_hi - p_lo))
print(f"scene diagonal: raw {raw_diag:,.0f}   robust(1-99) {robust_diag:.2f}")
print(f"  current oversize threshold = 0.05 * raw    = {0.05*raw_diag:,.1f}"
      f"  -> {int((max_axis > 0.05*raw_diag).sum()):,} splats qualify")
print(f"  robust-scale threshold     = 0.05 * robust = {0.05*robust_diag:.3f}"
      f"  -> {int((max_axis > 0.05*robust_diag).sum()):,} splats qualify\n")

print("=== max-axis distribution ===")
for q in (50, 90, 99, 99.9, 99.99):
    print(f"  p{q:<6} {np.percentile(max_axis, q):.4f}")
print(f"  max     {max_axis.max():.3f}")
print(f"  among VISIBLE splats: p50 {np.percentile(max_axis[visible],50):.4f}"
      f"  p90 {np.percentile(max_axis[visible],90):.4f}"
      f"  p99 {np.percentile(max_axis[visible],99):.4f}"
      f"  max {max_axis[visible].max():.3f}\n")

tot_surface = int(surface.sum())
print("=== what a max-axis cut removes, and what it costs ===")
print(f"{'threshold':>10} {'removed':>12} {'of which visible':>18} "
      f"{'surface lost':>16} {'sum of length removed':>22}")
print("-" * 84)
for t in (2.0, 1.0, 0.735, 0.5, 0.3, 0.2, 0.1, 0.05):
    big = max_axis > t
    lost = int((big & surface).sum())
    print(f"{t:>10.3f} {int(big.sum()):>12,} {int((big&visible).sum()):>18,} "
          f"{lost:>10,} {100*lost/tot_surface:>5.1f}% "
          f"{float(max_axis[big].sum()):>22,.0f}")

print("\n'sum of length removed' = total major-axis length deleted (world units)")
print("-- a proxy for how much streak area disappears from the render.\n")

# Where do the big ones sit? Inside the subject or out in the halo?
big = max_axis > 0.3
if big.sum():
    ctr = np.median(xyz[surface], axis=0)
    db = np.linalg.norm(xyz[big] - ctr, axis=1)
    dsz = np.linalg.norm(xyz[surface] - ctr, axis=1)
    print(f"=== location of splats with max_axis > 0.3 (n={int(big.sum()):,}) ===")
    print(f"  distance from subject centroid: p50 {np.median(db):.2f}"
          f"  p90 {np.percentile(db,90):.2f}  p99 {np.percentile(db,99):.2f}")
    print(f"  (surface splats for comparison: p50 {np.median(dsz):.2f}"
          f"  p90 {np.percentile(dsz,90):.2f})")
    print(f"  visible fraction among them: {100*visible[big].mean():.1f}%")
    print(f"  needle fraction among them:  {100*(ratio[big]>NEEDLE_RATIO).mean():.1f}%")

# Combined recipe: crop to grown box + drop big axes, keep everything else.
stride = max(1, n // 100_000)
sol = xyz[::stride][op[::stride] >= 0.3].astype(np.float64)
keys, counts = voxelize(sol)
comps = components(counts, max(3, max(counts.values()) * 0.08))
pb = fit_box(sol[np.isin(keys, list(comps[0]))])
d = np.linalg.norm(pb[1] - pb[0]); c = (pb[0] + pb[1]) / 2
gb = fit_box(sol[np.linalg.norm(sol - c, axis=1) <= d])
glo, ghi = gb[0].astype(np.float32), gb[1].astype(np.float32)
inbox = np.all((xyz >= glo) & (xyz <= ghi), axis=1)

print("\n=== combined recipes (all start from the grown-box crop) ===")
print(f"{'recipe':<44} {'splats':>10} {'surface kept':>15} {'streak length left':>20}")
print("-" * 92)
def row(label, keep):
    ks = int((keep & surface).sum())
    print(f"{label:<44} {int(keep.sum()):>10,} {ks:>9,} {100*ks/tot_surface:>5.1f}% "
          f"{float(max_axis[keep].sum()):>20,.0f}")

row("crop only (today)", inbox)
row("crop + max_axis<=0.735 (robust oversize)", inbox & (max_axis <= 0.735))
row("crop + max_axis<=0.3", inbox & (max_axis <= 0.3))
row("crop + max_axis<=0.1", inbox & (max_axis <= 0.1))
row("crop + opacity>=0.1", inbox & visible)
row("crop + opacity>=0.1 + max_axis<=0.3", inbox & visible & (max_axis <= 0.3))
