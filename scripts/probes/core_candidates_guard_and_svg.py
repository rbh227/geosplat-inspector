"""Exact guard math per candidate (VISIBILITY_ALPHA=0.10) + an SVG projection
so the boxes can be eyeballed against the actual subject."""
from __future__ import annotations

import sys
import numpy as np
from core_candidates_probe import read_ply, sigmoid, voxelize, components, fit_box

VISIBILITY_ALPHA = 0.10  # backend/contracts/constants.py

path = sys.argv[1] if len(sys.argv) > 1 else "public/demos/iona_park.ply"
arr, props = read_ply(path)
n = len(arr)
stride = max(1, n // 100_000)
s = arr[::stride]
pts = np.stack([s["x"], s["y"], s["z"]], axis=1).astype(np.float64)
op = sigmoid(np.asarray(s["opacity"], dtype=np.float64))

visible = pts[op >= VISIBILITY_ALPHA]      # what the backend guard counts as "solid core"
solid = pts[op >= 0.3]                     # what the frontend box-fitter uses
print(f"sample {len(pts):,} (stride {stride})")
print(f"core by backend definition (opacity >= {VISIBILITY_ALPHA}): {len(visible):,}"
      f"  -> nearTransparentFraction = {1 - len(visible)/len(pts):.4f}")

keys, counts = voxelize(solid)
comps = components(counts, max(3, max(counts.values()) * 0.08))
box_peak = fit_box(solid[np.isin(keys, list(comps[0]))])

lo = np.percentile(solid, 2, axis=0); hi = np.percentile(solid, 98, axis=0)
box_pct = (lo, hi)

# grown peak box: expand to cover solid points within one box-diagonal
diag = np.linalg.norm(box_peak[1] - box_peak[0])
c = (box_peak[0] + box_peak[1]) / 2
near = solid[np.linalg.norm(solid - c, axis=1) <= diag]
box_grown = fit_box(near)

CAND = {"peak (today)": box_peak, "grown (peak+1 diag)": box_grown, "solid 2-98": box_pct}

print(f"\n{'candidate':<22} {'core kept':>10} {'guard':>7} {'all kept':>10} {'volume':>10}")
for name, b in CAND.items():
    kv = np.all((visible >= b[0]) & (visible <= b[1]), axis=1).mean()
    ka = np.all((pts >= b[0]) & (pts <= b[1]), axis=1).mean()
    vol = float(np.prod(b[1] - b[0]))
    drop = 1 - ka
    verdict = "REVERT" if (kv < 0.5 or drop > 0.9) else "pass"
    print(f"{name:<22} {100*kv:>9.1f}% {verdict:>7} {100*ka:>9.1f}% {vol:>10.1f}")
print(f"\n(guard = silhouette_intact: reverts if core kept < 50% or total drop > 90%)")

# ---- SVG projections -------------------------------------------------------
COLORS = {"peak (today)": "#ff4d4d", "grown (peak+1 diag)": "#ffb020", "solid 2-98": "#35c26b"}


def panel(ax_h, ax_v, title, x0, y0, w, h):
    """One projection panel; returns SVG string."""
    P = np.percentile(solid, [1, 99], axis=0)
    pad_h = (P[1][ax_h] - P[0][ax_h]) * 0.35
    pad_v = (P[1][ax_v] - P[0][ax_v]) * 0.35
    lo_h, hi_h = P[0][ax_h] - pad_h, P[1][ax_h] + pad_h
    lo_v, hi_v = P[0][ax_v] - pad_v, P[1][ax_v] + pad_v
    sx = lambda v: x0 + (v - lo_h) / max(hi_h - lo_h, 1e-9) * w
    sy = lambda v: y0 + h - (v - lo_v) / max(hi_v - lo_v, 1e-9) * h

    out = [f'<rect x="{x0}" y="{y0}" width="{w}" height="{h}" fill="#0f1115" stroke="#333"/>',
           f'<text x="{x0+8}" y="{y0+18}" fill="#9aa" font-size="13" '
           f'font-family="monospace">{title}</text>']
    # faint junk (subsampled) then solid points
    junk = pts[op < VISIBILITY_ALPHA]
    j = junk[:: max(1, len(junk) // 4000)]
    for p in j:
        if lo_h <= p[ax_h] <= hi_h and lo_v <= p[ax_v] <= hi_v:
            out.append(f'<circle cx="{sx(p[ax_h]):.1f}" cy="{sy(p[ax_v]):.1f}" r="0.8" '
                       f'fill="#3a4250"/>')
    for p in solid:
        out.append(f'<circle cx="{sx(p[ax_h]):.1f}" cy="{sy(p[ax_v]):.1f}" r="1.1" '
                   f'fill="#cfd8e3" fill-opacity="0.75"/>')
    for name, b in CAND.items():
        bx, by = sx(b[0][ax_h]), sy(b[1][ax_v])
        bw = sx(b[1][ax_h]) - bx
        bh = sy(b[0][ax_v]) - by
        out.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bh:.1f}" '
                   f'fill="none" stroke="{COLORS[name]}" stroke-width="2"/>')
    return "\n".join(out)


W, H = 1160, 620
svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
       f'viewBox="0 0 {W} {H}"><rect width="{W}" height="{H}" fill="#0b0d10"/>']
svg.append(f'<text x="20" y="28" fill="#e6edf3" font-size="16" font-family="monospace">'
           f'iona_park.ply — solid splats (white), near-transparent junk (grey), candidate boxes</text>')
svg.append(panel(0, 2, "top-down  (X horiz, Z vert)", 20, 45, 540, 480))
svg.append(panel(0, 1, "side  (X horiz, Y vert)", 600, 45, 540, 480))
lx = 20
for name, col in COLORS.items():
    svg.append(f'<rect x="{lx}" y="{H-42}" width="16" height="12" fill="none" stroke="{col}" stroke-width="2"/>')
    svg.append(f'<text x="{lx+24}" y="{H-32}" fill="#9aa" font-size="13" font-family="monospace">{name}</text>')
    lx += 260
svg.append("</svg>")
out_path = "/private/tmp/claude-501/-Users-raphaelhaytene-Desktop-SplatAgent/8c933218-4c1b-4fec-9912-326f1088e9a0/scratchpad/iona_candidates.svg"
open(out_path, "w").write("\n".join(svg))
print(f"\nwrote {out_path}")
