"""Follow-up diagnostics: why does the core box miss, if not multi-component?"""
from __future__ import annotations

import sys
import numpy as np
from core_candidates_probe import read_ply, sigmoid, voxelize, components, fit_box, R

path = sys.argv[1] if len(sys.argv) > 1 else "public/demos/iona_park.ply"
arr, props = read_ply(path)
print("properties:", props, "\n")

n = len(arr)
stride = max(1, n // 100_000)
sample = arr[::stride]
pts = np.stack([sample["x"], sample["y"], sample["z"]], axis=1).astype(np.float64)
raw = np.asarray(sample["opacity"], dtype=np.float64)
op = sigmoid(raw)

print(f"raw opacity logits: min {raw.min():.2f} p25 {np.percentile(raw,25):.2f} "
      f"med {np.median(raw):.2f} p75 {np.percentile(raw,75):.2f} max {raw.max():.2f}")
print("activated opacity distribution:")
for t in (0.9, 0.7, 0.5, 0.3, 0.2, 0.1, 0.05, 0.03, 0.01):
    k = int((op >= t).sum())
    print(f"  >= {t:<5} {k:>7,} of {len(op):,}  ({100*k/len(op):5.2f}%)"
          f"  -> {k*stride:>10,} full-scene")

# scale magnitude: are the transparent ones huge blobs (junk) or normal?
scale_cols = [p for p in props if p.startswith("scale_")]
if scale_cols:
    sc = np.stack([sample[c] for c in scale_cols], axis=1).astype(np.float64)
    maxax = np.exp(sc).max(axis=1)
    print(f"\nmax-axis scale (world): med {np.median(maxax):.4f}  "
          f"p99 {np.percentile(maxax,99):.4f}  max {maxax.max():.4f}")
    for label, mask in (("solid>=0.3", op >= 0.3), ("faint<0.3", op < 0.3)):
        m = maxax[mask]
        if len(m):
            print(f"  {label:<10} n={len(m):>6,}  med scale {np.median(m):.4f}"
                  f"  p90 {np.percentile(m,90):.4f}")

print("\n=== component structure at several opacity thresholds ===")
for t in (0.3, 0.1, 0.05, 0.01):
    fit = pts[op >= t]
    if len(fit) < 100:
        print(f"t={t}: only {len(fit)} pts, skip")
        continue
    keys, counts = voxelize(fit)
    peak = max(counts.values())
    thr = max(3, peak * 0.08)
    comps = components(counts, thr)
    tot = [sum(counts[k] for k in c) for c in comps]
    box = fit_box(fit[np.isin(keys, list(comps[0]))])
    inside_fit = np.all((fit >= box[0]) & (fit <= box[1]), axis=1).mean()
    inside_all = np.all((pts >= box[0]) & (pts <= box[1]), axis=1).mean()
    ext = box[1] - box[0]
    print(f"t={t:<5} fit={len(fit):>6,}  peakcell={peak:>4}  comps={len(comps):>3}"
          f"  top3={[round(100*x/len(fit),1) for x in tot[:3]]}%"
          f"  box_ext={np.round(ext,2).tolist()}"
          f"  keeps {100*inside_fit:.0f}% of fit / {100*inside_all:.0f}% of all")

print("\n=== where are the solid points that fall OUTSIDE the peak-component box? ===")
fit = pts[op >= 0.3]
keys, counts = voxelize(fit)
peak = max(counts.values())
comps = components(counts, max(3, peak * 0.08))
box = fit_box(fit[np.isin(keys, list(comps[0]))])
out = fit[~np.all((fit >= box[0]) & (fit <= box[1]), axis=1)]
print(f"{len(out):,} of {len(fit):,} solid points outside box B")
if len(out):
    c = box[0] + (box[1] - box[0]) / 2
    d = np.linalg.norm(out - c, axis=1)
    boxdiag = np.linalg.norm(box[1] - box[0])
    print(f"  distance from box center, in box-diagonals:"
          f" med {np.median(d)/boxdiag:.2f}  p90 {np.percentile(d,90)/boxdiag:.2f}"
          f"  max {d.max()/boxdiag:.2f}")
    near = (d < boxdiag).sum()
    print(f"  {100*near/len(out):.0f}% sit within one box-diagonal of the box"
          f" (i.e. a halo hugging the subject, not a separate settlement)")

print("\n=== spatial spread of ALL splats vs solid (per axis, percentiles) ===")
for ax, name in enumerate("xyz"):
    a_all = np.percentile(pts[:, ax], [1, 25, 50, 75, 99])
    a_sol = np.percentile(fit[:, ax], [1, 25, 50, 75, 99])
    print(f"  {name}: all {np.round(a_all,2).tolist()}   solid {np.round(a_sol,2).tolist()}"
          f"   boxB [{box[0][ax]:.2f}, {box[1][ax]:.2f}]")
