"""Is the crop box simply too big?

Earlier separability work treated every splat with opacity >= 0.1 as "subject",
but roughly half of those are needles -- the bright spikes in the render. This
splits the visible population into SURFACE (compact, ratio <= 10) and SPIKE
(needle, ratio > 10) and asks whether they occupy different volumes. If they do,
a tighter box is the fix and shrinking costs far less than it appeared.

Run from this directory:
    ../../.venv-api/bin/python spike_vs_surface.py ../../public/demos/iona_park.ply
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
ratio = scale.max(axis=1) / np.maximum(scale.min(axis=1), 1e-9)

visible = op >= VISIBILITY_ALPHA
spike = visible & (ratio > NEEDLE_RATIO)
surface = visible & (ratio <= NEEDLE_RATIO)
print(f"whole scene: {n:,} splats")
print(f"  visible (op>={VISIBILITY_ALPHA})  {int(visible.sum()):,}")
print(f"    SURFACE (ratio<={NEEDLE_RATIO})  {int(surface.sum()):,}")
print(f"    SPIKE   (ratio> {NEEDLE_RATIO})  {int(spike.sum()):,}\n")

print("=== do surface and spike occupy different volumes? (percentiles) ===")
S, K = xyz[surface], xyz[spike]
for ax, name in enumerate("xyz"):
    ps = np.percentile(S[:, ax], [1, 5, 50, 95, 99])
    pk = np.percentile(K[:, ax], [1, 5, 50, 95, 99])
    print(f"  {name}: surface {np.round(ps,2).tolist()}")
    print(f"     spike   {np.round(pk,2).tolist()}")

# radial: how far from the surface centroid does each population reach?
ctr = np.median(S, axis=0)
ds = np.linalg.norm(S - ctr, axis=1)
dk = np.linalg.norm(K - ctr, axis=1)
print(f"\n  distance from surface centroid {np.round(ctr,2).tolist()}:")
print(f"    surface: p50 {np.median(ds):.2f}  p90 {np.percentile(ds,90):.2f}"
      f"  p99 {np.percentile(ds,99):.2f}")
print(f"    spike:   p50 {np.median(dk):.2f}  p90 {np.percentile(dk,90):.2f}"
      f"  p99 {np.percentile(dk,99):.2f}")

# --- the box fitted to SURFACE only -----------------------------------------
print("\n=== box fitted to SURFACE splats only (5-95 percentile + 5% pad) ===")
lo = np.percentile(S, 5, axis=0); hi = np.percentile(S, 95, axis=0)
ext = hi - lo
lo, hi = (lo - ext * 0.05).astype(np.float32), (hi + ext * 0.05).astype(np.float32)
print(f"  min {np.round(lo,3).tolist()}  max {np.round(hi,3).tolist()}"
      f"  extent {np.round(hi-lo,2).tolist()}")
m = np.all((xyz >= lo) & (xyz <= hi), axis=1)
print(f"  splats kept   {int(m.sum()):>10,}  ({100*m.mean():.1f}% of scene)")
print(f"  SURFACE kept  {int((m&surface).sum()):>10,}  "
      f"({100*(m&surface).sum()/surface.sum():.1f}% of all surface)")
print(f"  SPIKE  kept   {int((m&spike).sum()):>10,}  "
      f"({100*(m&spike).sum()/spike.sum():.1f}% of all spikes)")

# --- sweep, tracking both populations separately ----------------------------
print("\n=== box-scale sweep around the SURFACE centroid, populations split ===")
# start from the grown box used previously, so the comparison is apples-to-apples
stride = max(1, n // 100_000)
sol = xyz[::stride][op[::stride] >= 0.3].astype(np.float64)
keys, counts = voxelize(sol)
comps = components(counts, max(3, max(counts.values()) * 0.08))
pb = fit_box(sol[np.isin(keys, list(comps[0]))])
d = np.linalg.norm(pb[1] - pb[0]); c = (pb[0] + pb[1]) / 2
gb = fit_box(sol[np.linalg.norm(sol - c, axis=1) <= d])
glo, ghi = gb[0].astype(np.float32), gb[1].astype(np.float32)
gctr, ghalf = (glo + ghi) / 2, (ghi - glo) / 2
tot_s, tot_k = int(surface.sum()), int(spike.sum())

print(f"{'scale':>6} {'splats':>11} {'surface kept':>16} {'spikes kept':>16} {'S:K ratio':>10}")
print("-" * 66)
for sc in (1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.35, 0.3, 0.25):
    l2, h2 = gctr - ghalf * sc, gctr + ghalf * sc
    mm = np.all((xyz >= l2) & (xyz <= h2), axis=1)
    ks, kk = int((mm & surface).sum()), int((mm & spike).sum())
    print(f"{sc:>6.2f} {int(mm.sum()):>11,} {ks:>10,} {100*ks/tot_s:>5.1f}% "
          f"{kk:>10,} {100*kk/tot_k:>5.1f}% {ks/max(kk,1):>10.2f}")
print("\nS:K ratio = surviving surface splats per surviving spike. Higher is cleaner.")
print("If shrinking raises S:K, the box IS too big and tightening genuinely helps.")
