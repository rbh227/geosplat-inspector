"""Offline probe: does a union-of-dense-components box recover the whole
settlement on the real demo scene, where the single-peak box does not?

Replicates SceneManager.getCoreBoundsBox + framing.computeTightCoreBox exactly
(100k strided sample, opacity ladder, 32^3 voxel grid, >=8% of peak, 26-neighbor
flood fill, 1-99 percentile fit + 4% pad), then runs the proposed multi-component
variant on the same sample so the two are directly comparable.
"""
from __future__ import annotations

import sys
from collections import deque

import numpy as np


def read_ply(path: str):
    with open(path, "rb") as f:
        header = b""
        while b"end_header" not in header:
            chunk = f.readline()
            if not chunk:
                raise SystemExit("no end_header")
            header += chunk
        offset = f.tell()

    lines = header.decode("ascii", "replace").splitlines()
    fmt = next(l for l in lines if l.startswith("format"))
    if "binary_little_endian" not in fmt:
        raise SystemExit(f"unsupported: {fmt}")
    count = int(next(l for l in lines if l.startswith("element vertex")).split()[2])
    props = [l.split()[-1] for l in lines if l.startswith("property float")]
    n_props = len([l for l in lines if l.startswith("property ")])
    if n_props != len(props):
        raise SystemExit("non-float properties present; probe assumes all float32")

    dtype = np.dtype([(p, "<f4") for p in props])
    arr = np.memmap(path, dtype=dtype, mode="r", offset=offset, shape=(count,))
    return arr, props


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def percentile_box(pts, lo_q, hi_q, pad=0.0):
    lo = np.percentile(pts, lo_q * 100, axis=0)
    hi = np.percentile(pts, hi_q * 100, axis=0)
    ext = np.maximum(hi - lo, 1e-6)
    return lo - ext * pad, hi + ext * pad


R = 32


def voxelize(pts):
    """Returns (cell_index_per_point, counts_dict) on the 2-98 robust extent."""
    lo = np.percentile(pts, 2, axis=0)
    hi = np.percentile(pts, 98, axis=0)
    ext = np.maximum(hi - lo, 1e-6)
    idx = np.floor((pts - lo) / ext * R).astype(np.int64)
    inside = np.all((idx >= 0) & (idx < R), axis=1)
    keys = np.full(len(pts), -1, dtype=np.int64)
    keys[inside] = idx[inside, 0] + idx[inside, 1] * R + idx[inside, 2] * R * R
    uniq, cnt = np.unique(keys[inside], return_counts=True)
    return keys, dict(zip(uniq.tolist(), cnt.tolist()))


def neighbors(key):
    ix, iy, iz = key % R, (key // R) % R, key // (R * R)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                nx, ny, nz = ix + dx, iy + dy, iz + dz
                if 0 <= nx < R and 0 <= ny < R and 0 <= nz < R:
                    yield nx + ny * R + nz * R * R


def components(counts, threshold):
    """All connected components of cells with count >= threshold."""
    dense = {k for k, c in counts.items() if c >= threshold}
    seen, comps = set(), []
    for start in dense:
        if start in seen:
            continue
        comp, q = {start}, deque([start])
        seen.add(start)
        while q:
            k = q.popleft()
            for nk in neighbors(k):
                if nk in dense and nk not in seen:
                    seen.add(nk)
                    comp.add(nk)
                    q.append(nk)
        comps.append(comp)
    comps.sort(key=lambda c: sum(counts[k] for k in c), reverse=True)
    return comps


def fit_box(pts):
    return percentile_box(pts, 0.01, 0.99, pad=0.04)


def box_stats(name, box, all_pts, solid_pts, stride, n_total):
    lo, hi = box
    inside_all = np.all((all_pts >= lo) & (all_pts <= hi), axis=1).sum()
    inside_solid = np.all((solid_pts >= lo) & (solid_pts <= hi), axis=1).sum()
    ext = hi - lo
    print(f"  {name}")
    print(f"    min {np.round(lo, 3).tolist()}  max {np.round(hi, 3).tolist()}")
    print(f"    extent {np.round(ext, 3).tolist()}  volume {np.prod(ext):.3f}")
    print(f"    splats inside  {inside_all * stride:>12,} / {n_total:,}"
          f"  ({100 * inside_all / len(all_pts):.1f}% of sample)")
    print(f"    solid inside   {inside_solid * stride:>12,}"
          f"  ({100 * inside_solid / max(len(solid_pts), 1):.1f}% of solid core retained)")
    return inside_solid / max(len(solid_pts), 1)


def main(path):
    arr, props = read_ply(path)
    n = len(arr)
    print(f"scene: {path}\nsplats: {n:,}\nproperties: {len(props)}\n")

    stride = max(1, n // 100_000)
    sample = arr[::stride]
    pts = np.stack([sample["x"], sample["y"], sample["z"]], axis=1).astype(np.float64)
    op = sigmoid(np.asarray(sample["opacity"], dtype=np.float64))
    print(f"sampled {len(pts):,} (stride {stride})")
    print(f"opacity: min {op.min():.3f} med {np.median(op):.3f} max {op.max():.3f}")

    solid = pts[op >= 0.3]
    faint = pts[(op >= 0.03) & (op < 0.3)]
    min_sample = max(200, len(pts) * 0.005)
    if len(solid) >= min_sample:
        fit_pts, ladder = solid, "solid (>=0.3)"
    elif len(solid) + len(faint) >= min_sample:
        fit_pts, ladder = np.concatenate([solid, faint]), "solid+faint (>=0.03)"
    else:
        fit_pts, ladder = pts, "all (fallback)"
    print(f"solid {len(solid):,}  faint {len(faint):,}  -> ladder: {ladder}"
          f"  ({len(fit_pts):,} fit points)\n")

    keys, counts = voxelize(fit_pts)
    peak_count = max(counts.values())
    threshold = max(3, peak_count * 0.08)
    comps = components(counts, threshold)
    tot = {i: sum(counts[k] for k in c) for i, c in enumerate(comps)}
    print(f"dense cells: {sum(1 for c in counts.values() if c >= threshold)}"
          f" / {len(counts)} occupied  (peak cell {peak_count}, threshold {threshold:.1f})")
    print(f"connected components: {len(comps)}")
    for i, c in enumerate(comps[:12]):
        print(f"  #{i}: {len(c):>4} cells, {tot[i]:>7,} pts"
              f"  ({100 * tot[i] / len(fit_pts):.1f}% of fit points)")
    if len(comps) > 12:
        print(f"  ... {len(comps) - 12} more")
    print()

    print("=== CANDIDATES ===")
    # B - core: today's single-peak box
    peak_cells = comps[0]
    kept = fit_pts[np.isin(keys, list(peak_cells))]
    box_b = fit_box(kept)
    print("B (core = TODAY'S get_core_bounds, single peak component):")
    ret_b = box_stats("", box_b, pts, solid, stride, n)

    # A - settlement: union of components >= 10% of peak component
    bar = tot[0] * 0.10
    chosen = [i for i in range(len(comps)) if tot[i] >= bar]
    union_cells = set().union(*[comps[i] for i in chosen])
    kept_a = fit_pts[np.isin(keys, list(union_cells))]
    box_a = fit_box(kept_a)
    print(f"\nA (settlement = union of {len(chosen)}/{len(comps)} components"
          f" with >=10% of peak component's points):")
    ret_a = box_stats("", box_a, pts, solid, stride, n)

    # C - wide: robust 2-98 over solid
    box_c = percentile_box(fit_pts, 0.02, 0.98)
    print("\nC (wide = robust 2-98 percentile over fit points):")
    ret_c = box_stats("", box_c, pts, solid, stride, n)

    print("\n=== VERDICT ===")
    vol = lambda b: float(np.prod(b[1] - b[0]))
    print(f"components merged into A: {len(chosen)} (B uses 1)")
    print(f"A/B volume ratio: {vol(box_a) / max(vol(box_b), 1e-9):.2f}x")
    print(f"solid core retained -> B {100*ret_b:.1f}%   A {100*ret_a:.1f}%   C {100*ret_c:.1f}%")
    print(f"A recovers {100*(ret_a - ret_b):.1f} pp more solid core than B")
    if ret_b < 0.5:
        print("NOTE: B retains <50% of solid core -> silhouette_intact WOULD revert"
              " an operator-approved crop to B today.")
    if ret_a < 0.5:
        print("NOTE: A also retains <50% -> the guard change is REQUIRED, not optional.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "public/demos/iona_park.ply")
