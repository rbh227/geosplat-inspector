# Example scenes (FROZEN — Phase 0)

Shared test data so every agent works against real Gaussians, not hand-rolled stubs.
Both files are **INRIA 3DGS** format: binary little-endian, SH degree 3 (45 `f_rest`
coeffs), 62 float properties per Gaussian in header order
`x,y,z · nx,ny,nz · f_dc_0..2 · f_rest_0..44 · opacity · scale_0..2 · rot_0..3`
(see ARCHITECTURE.md §6.1). Values are stored raw: opacity = logit, scale = log,
rotation = unnormalized wxyz quaternion, color DC = `(rgb-0.5)/SH_C0`.

## Files

| File | Gaussians | Description |
|------|-----------|-------------|
| `clean.ply` | 1000 | Tidy Fibonacci-sampled sphere surface. High opacity (0.85–0.95), small uniform isotropic scales (~0.02), gentle green color variation. No defects. |
| `messy.ply` | 1200 | The same 1000-Gaussian sphere **plus 200 deliberate defects** (below). The designated dirty scene for the floater-cleanup flagship loop and for benchmarking edit ops. |

## How `messy.ply` was made

`messy.ply = clean.ply + 200 injected defects`, produced by
[`generate_test_scenes.py`](./generate_test_scenes.py) (seed `42`, deterministic).
Each defect class is tuned to trip exactly one contract threshold (§6.2), so the
metrics and editing engines have an unambiguous target:

| Defect | Count | How it's built | Trips |
|--------|-------|----------------|-------|
| **Floaters** | 80 | Scattered in `[-5,5]³`, activated opacity drawn in `0.01–0.04` | `opacity < FLOATER_ALPHA` (0.05) → `opacity_threshold` / `nearTransparentFraction` |
| **Isolated outliers** | 60 | Placed on a shell at radius `4–8` from origin (far from the unit sphere), normal opacity, colored red | high mean k-NN distance → `remove_outliers` / `outlierFraction` |
| **Needles** | 60 | One scale axis enlarged to `10–30×` the other two, colored blue | `axisRatio > NEEDLE_RATIO` (10.0) → `remove_needles` / `needleFraction` |

Verified signal (re-runnable via the validation snippet in Phase 0): `messy.ply` has
exactly **80** Gaussians under `FLOATER_ALPHA`, **60** with axis ratio `> 10` (max ≈ 29.5),
and 60 spatial outliers; `clean.ply` has **none** of these.

## Regenerate

```bash
python3 examples/generate_test_scenes.py
```

> Note (ARCHITECTURE.md §8): these are intentionally **small** for fast iteration. The
> §8 benchmark rule calls for timing all-Gaussian ops on a multi-hundred-K scene — scale
> `n_clean` up in the generator (or drop in a real captured scene) for performance runs.
