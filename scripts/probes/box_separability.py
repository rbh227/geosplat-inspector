"""Can ANY box separate the junk from the subject?

"Delete everything outside a chosen area" already works (crop_bbox). The question
this answers is whether a *better chosen area* could also remove the remaining
junk -- i.e. whether junk and subject occupy different volumes (separable) or the
same volume (not separable by position at all).

Two measurements:
  1. Spatial overlap of visible core vs near-invisible splats inside the box.
  2. A box-scale sweep: shrink the box around its center and watch what you lose.

Run from this directory:
    ../../.venv-api/bin/python box_separability.py ../../public/demos/iona_park.ply
"""
from __future__ import annotations

import sys
import numpy as np
from core_candidates_probe import read_ply, sigmoid, voxelize, components, fit_box

VISIBILITY_ALPHA = 0.10

path = sys.argv[1] if len(sys.argv) > 1 else "../../public/demos/iona_park.ply"
arr, _ = read_ply(path)
n = len(arr)
xyz = np.stack([arr["x"], arr["y"], arr["z"]], axis=1).astype(np.float32)
op = sigmoid(np.asarray(arr["opacity"], dtype=np.float32))
visible = op >= VISIBILITY_ALPHA

# Rebuild the grown box (same as the spec's candidate B).
stride = max(1, n // 100_000)
solid = xyz[::stride][op[::stride] >= 0.3].astype(np.float64)
keys, counts = voxelize(solid)
comps = components(counts, max(3, max(counts.values()) * 0.08))
pb = fit_box(solid[np.isin(keys, list(comps[0]))])
d = np.linalg.norm(pb[1] - pb[0])
c = (pb[0] + pb[1]) / 2
box = fit_box(solid[np.linalg.norm(solid - c, axis=1) <= d])
lo, hi = box[0].astype(np.float32), box[1].astype(np.float32)
inside = np.all((xyz >= lo) & (xyz <= hi), axis=1)

core = xyz[inside & visible]
junk = xyz[inside & ~visible]
print(f"inside the box: {int(inside.sum()):,} splats"
      f"  ->  visible core {len(core):,}   near-invisible {len(junk):,}\n")

print("=== 1. do they occupy the same volume? (percentile extents, per axis) ===")
for ax, name in enumerate("xyz"):
    pc = np.percentile(core[:, ax], [1, 25, 50, 75, 99])
    pj = np.percentile(junk[:, ax], [1, 25, 50, 75, 99])
    print(f"  {name}: core {np.round(pc,2).tolist()}")
    print(f"     junk {np.round(pj,2).tolist()}")

# Voxel-level co-occupancy: of the cells holding junk, how many also hold core?
R = 48
ext = np.maximum(hi - lo, 1e-6)
cell = lambda p: np.clip(((p - lo) / ext * R).astype(np.int64), 0, R - 1)
kc = set(map(tuple, cell(core)))
kj_all = list(map(tuple, cell(junk)))
kj = set(kj_all)
shared = kj & kc
junk_in_shared = sum(1 for k in kj_all if k in shared)
print(f"\n  on a {R}^3 grid over the box:")
print(f"    cells with core        {len(kc):,}")
print(f"    cells with junk        {len(kj):,}")
print(f"    cells with BOTH        {len(shared):,}  ({100*len(shared)/max(len(kj),1):.1f}% of junk cells)")
print(f"    junk splats sharing a cell with core: {junk_in_shared:,}"
      f"  ({100*junk_in_shared/max(len(kj_all),1):.1f}%)")
print("  -> junk sitting in the same cells as the subject cannot be removed by ANY box.")

print("\n=== 2. box-scale sweep: shrink around the center, what do you lose? ===")
ctr = (lo + hi) / 2
half = (hi - lo) / 2
core_total = int((inside & visible).sum())
print(f"{'scale':>6} {'splats kept':>12} {'':>7} {'visible core kept':>18} {'':>7} {'junk removed':>13}")
print("-" * 72)
junk_total = int((inside & ~visible).sum())
for sc in (1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3):
    l2, h2 = ctr - half * sc, ctr + half * sc
    m = np.all((xyz >= l2) & (xyz <= h2), axis=1)
    kept = int(m.sum())
    kcore = int((m & visible).sum())
    jremoved = junk_total - int((m & ~visible).sum())
    print(f"{sc:>6.1f} {kept:>12,} {100*kept/n:>6.1f}% "
          f"{kcore:>12,} {100*kcore/core_total:>6.1f}% "
          f"{jremoved:>12,} {100*jremoved/junk_total:>5.1f}%")

print("\nRead the sweep as: to remove X% of the junk by shrinking the box,")
print("you give up (100 - core kept)% of everything you can actually see.")
