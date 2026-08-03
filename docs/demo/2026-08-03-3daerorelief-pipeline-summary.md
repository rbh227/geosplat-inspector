# 3DAeroRelief — Demo Scene Pipeline Summary

> Reference record imported from the `3DAeroRelief_Reconstruction` repo session on 2026-08-03.
> This is the pipeline that produced the demo splats loaded into SplatAgent. The condensed
> story lives in the root [README](../../README.md#how-the-demo-scenes-were-made).

**Date:** 2026-08-03 · **Repo:** `3DAeroRelief_Reconstruction`, branch `feat/select-building` @ `fe38eaa` (2026-07-15)
**Purpose:** exact record of the pipeline that produced the demo splats, the data behind them, known limitations, and the roadmap to denser / sharper / more usable scenes.

---

## 1. What the demo deliverables are

Two generations of deliverables exist:

**(a) Six packaged whole-area scenes** (`splat_agent/scenes/`, 2026-07-06) — three each for Iona-Point and Sanibel-Island. Region-cropped splats of the densest parts of each site, ~0.8–1.2 M gaussians each after pruning, with orbit MP4s.

**(b) Per-building "house" splats** (2026-07-14/15, under `work/<site>/scenes/bldgNN/`) — the newest recipe: a single building isolated from the scene, trained with a box-weighted budget and box-masked loss, then pruned to a compact deliverable (e.g. Iona bldg01 `house.ply`: **12,375 gaussians, 2.9 MB**, holdout PSNR 21.67).

> Housekeeping caveats: the per-building outputs live only under `work/` (never packaged into `splat_agent/scenes/`), and the branch carrying all building work (`feat/select-building`) is **not merged to `master`**.

---

## 2. Input data

Drone video frames from Hurricane Ian relief sites (pre-extracted PNGs; **no EXIF/GPS**, so all reconstructions are scale-free, not metric).

| Site | Frames on disk | Resolution | Processed? |
|---|---|---|---|
| Iona-Point_P0020002 | 3,525 | 3840×2160 (4K) | ✅ full pipeline |
| Sanibel-Island_DJI_20220930105030_0001_S | 3,237 | 1920×1080 | ✅ full pipeline |
| Siesta-Dr_DJI_20220930105030_0001_S | 1,019 | 1920×1080 | frame thinning only, no SfM |
| Palmeto-Palms_DJI_0459 | 1,760 | 1920×1080 | ❌ untouched |
| Palmeto-Palms_old | 704 | 1920×1080 | ❌ untouched |

**Hardware:** shared box with 4× NVIDIA L40S (46 GB each, one job per GPU via tmux, no distributed training), 48-core CPU (all jobs pinned to `OMP_NUM_THREADS=4`). Conda env `splats`: Python 3.11, torch/cu126, COLMAP (CUDA build), gsplat 1.5.3.

---

## 3. The pipeline, stage by stage

All stages are scripts in `splat_agent/scripts/` (17 scripts, 74 unit tests across 9 test files).

### Stage 1 — Frame thinning (`select_frames.py`)
Variance-of-Laplacian sharpness scored at 960 px width; keep the sharpest frame per sliding window of 5.
- Sanibel: 3,237 → **648** frames (sharpness median 2,284)
- Iona: 3,525 → **705** frames (sharpness median 4,545)

### Stage 2 — COLMAP SfM (`run_sfm.py`)
RADIAL camera model, GPU SIFT (40 K features, `max_image_size` 6000), sequential matching (`--overlap 15`) + 32K-word vocab-tree loop closure, incremental mapping. Pass bands: ≥90 % registered = pass.
- Sanibel: **598/648 registered (92.3 %), 494,517 points** — pass
- Iona: **705/705 registered (100 %), 604,365 points** — pass

### Stage 3 — Region / target selection
Two selectors, both emitting an undistorted native-res PINHOLE scene dir + `bbox.npy`:

- **`select_chunk.py`** (whole-area demo scenes): density-scored top-K non-overlapping regions on a grid built from the SVD ground plane of quality-filtered SfM points (track ≥ 3, reproj err ≤ 2 px); emits `bbox.npy` + padded `bbox_context.npy` + heatmap.
- **`select_building.py`** (per-building scenes): detects buildings geometrically — points above the fitted ground plane, grid connected-components — prints a numbered top-down map, then `--build N` emits per-building frame **crops** (uniform, full-frame aspect) plus bbox. **Key knob: `--cell-frac 0.035`** (the 0.06 default merges beachfront condo rows into one blob; a near-full-frame crop size at emit is the red flag). Found 8 buildings on Iona, 10 on Sanibel.

### Stage 4 — (Optional branch) VGGT feed-forward geometry
`vggt_scene.py` runs Meta's **VGGT-1B** in one bf16 forward pass (62 frames at 518×294: **3.5 s, ~10 GB VRAM**) → poses + dense confidence-filtered point cloud; `vggt_to_colmap.py` wraps it as a COLMAP-format block for the trainer. Used only on Sanibel scene02/bldg01. VGGT output is in its own normalized scale — an ad-hoc umeyama similarity fit from shared camera centers maps site-frame boxes into the VGGT frame (rms 1.3 % on bldg01).

### Stage 5 — Training (`train_block.py`)
gsplat **MCMC** densification strategy, antialiased rasterization, SH degree 3. Target-region control:
- `--weight-bbox`: box-weighted MCMC budget (custom `weighted_mcmc.py` strategy; a proportional controller adapts an in-box multinomial boost toward a target in-box fraction, boost cap 500)
- `--loss-bbox`: masks the photometric loss to the projected box hull, so background pixels never demand coverage (**the fix for the background-inflation OOM** — see §6)
- `--seed-bbox`: drops SfM seed points outside the box at init
- Holdout split with per-frame PSNR + GT|render side-by-side JPEGs

### Stage 6 — Pruning (`auto_prune.py`)
Five filters: low opacity, oversized, outside footprint bbox, needle_long, needle_thin (rod-shaped only, via max/mid axis ratio — pancake surfels are kept, they're valid roofs/walls).

### Stage 7 — Packaging & rendering
`render_orbit.py` (orbit MP4 framed on splat-mass percentiles) and `package_scene.py` (scene triplet layout). **Warning that cost us a week:** the orbit-path heuristic breaks on these scenes (far floaters inflate the footprint) — orbit MP4s look like spiky garbage even when the splat is good. **Always verify from real training poses** (render at held-out COLMAP cameras vs GT frames).

---

## 4. Exact recipes used for the deliverables

### Recipe A — the six packaged demo scenes (2026-07-06)
```
select_frames --window 5
run_sfm                          # RADIAL, 40K SIFT, seq+vocab-tree
select_chunk                     # density regions, bbox + bbox_context, native-res undistort
train_block --iters 30000 --cap 3000000 --weight-bbox bbox_context.npy  # target in-box 0.85
auto_prune                       # 3 filters (pre-needle era)
render_orbit
package_scene
```

### Recipe B — the final per-building recipe (Iona bldg01, 2026-07-15 — the last and best run)
```
select_building --cell-frac 0.035 --build 1 --margin 0.5
train_block <scene> \
  --seed-bbox bbox.npy --weight-bbox bbox.npy --weight-frac 0.70 \
  --loss-bbox bbox.npy --min-opacity 0.05 \
  --cap 500000 --tile-size 32 --iters 60000 --holdout-every 10
auto_prune raw.ply --bbox bbox.npy --out house.ply
```
Environment for every GPU run: full conda activation of `splats` + `CPATH` for the gsplat JIT, `OMP_NUM_THREADS=4`, python binary hard-pinned (a stray venv shadows PATH), `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`, long jobs detached in tmux.

Note: the final recipe uses **COLMAP bundle-adjusted poses at native 4K** — the VGGT pose branch was not used for the Iona buildings (see §6, "the pose A/B that never resolved").

---

## 5. Results

### 5a. Packaged demo scenes (`splat_agent/scenes/`) — all: 30 K iters, 3 M cap, ~27–44 min on one L40S

| Scene | Gaussians (pruned) | Views | Train time | Holdout PSNR |
|---|---|---|---|---|
| Iona scene00 | 987,734 | 76 | 44.1 min | n/a* |
| Iona scene01 | 796,921 | 108 | 44.1 min | n/a* |
| Iona scene02 | 1,185,295 | 134 | 43.9 min | n/a* |
| Sanibel scene00 | 1,176,412 | 200 | 27.6 min | n/a* |
| Sanibel scene01 | 1,213,763 | 224 | 29.2 min | n/a* |
| Sanibel scene02 | 1,152,780 | 198 | 27.2 min | n/a* |

*Holdout instrumentation landed a week after these were trained; quality was verified visually from training poses.

### 5b. Needle-free refresh scenes (Iona, 2026-07-13, never packaged)

| Scene | Frames / area | Holdout PSNR (mean/min) | Verdict |
|---|---|---|---|
| scene03 (pilot) | 126 f / 10 cells | **21.23 / 19.31** | KEEP — user-approved quality bar |
| scene04 | 174 f / 31 cells | 17.16 / 6.60 | DROP — budget dilution (3× area, same 3 M cap) |
| scene06 | 160 f / 51 cells | 17.36 / 10.61 | below bar, same cause |

**Lesson: the gaussian budget must scale with covered area, or PSNR collapses.** This is the direct motivation for per-building crops.

### 5c. Per-building house splats (the newest deliverables)

| Building | Recipe | Views / res | Train | Holdout PSNR | Deliverable |
|---|---|---|---|---|---|
| Sanibel bldg01 | VGGT poses, 62 crops 1536×858, weighted+loss-bbox, 1 M cap | 62 | 14.0 min | 21.66 / 19.41 | `vggt_block/house.ply`, 419,729 g |
| Sanibel bldg01 (unweighted variant) | VGGT poses, 3 M cap | 62 | 26.8 min | **22.55 / 20.67** | `raw_unweighted.ply` |
| Iona bldg00 | COLMAP poses, unweighted, 2 M cap, 60 K iters | 264 @ 4K | 56.3 min | 17.80 / 6.74 | `house.ply`, 60,959 g |
| **Iona bldg01** | **COLMAP poses, full Recipe B** | 111 @ 4K | 45.6 min | **21.67 / 19.14** | **`house.ply`, 12,375 g (2.9 MB)**; wider-box `house_ctx.ply`, 17,669 g |

Iona bldg00's low score comes from being a large multi-structure compound trained unweighted — background soaked up the budget; the min-PSNR frame (6.74) is an outlier view. Iona bldg01, with the full box-weighted recipe, matches the user-approved quality bar at 1/100th the file size of a scene splat.

---

## 6. Failure modes we hit (and their fixes) — worth telling in the demo

1. **Budget dilution** — oblique drone frames show the whole coastline; the optimizer spreads a fixed gaussian budget over everything visible. *Fix:* per-building crops + box-weighted budget (`--weight-bbox`).
2. **Background-inflation OOM** — with a weighted budget, the starved out-of-box gaussians inflate to cover ocean/sky, each spanning thousands of raster tiles → CUDA OOM in `isect_tiles` regardless of cap (3 M/2 M/1 M all died). Cap reduction doesn't fix the *incentive*. *Fix:* `--loss-bbox` masks the photometric loss so background pixels never demand coverage.
3. **Relocation stall** — in-box fraction falling while the controller boost rails at its cap = barely-alive background gaussians starving relocation. *Fix:* raise `--min-opacity` to 0.05.
4. **Misleading orbit videos** — orbit MP4s look broken on good splats (floaters break the framing heuristic). *Fix:* judge quality only from renders at real (held-out) training poses vs GT.
5. **Needle artifacts** — rod-shaped gaussians along viewing rays; pruned by anisotropy filters that distinguish rods (bad) from pancakes (legitimate surfaces).
6. **The pose A/B that never resolved** — residual blur on bldg01 was diagnosed as likely coming from VGGT's un-bundle-adjusted poses (few-px misregistration → optimizer paints a blurred average; holdout side-by-sides show renders softer than GT at the same viewpoint). The planned VGGT-vs-COLMAP A/B **crashed with OOM before producing a verdict** (site-frame coordinates blew up the means learning rate) and was explicitly declared invalid. The project pivoted to COLMAP poses for the final Iona runs — so COLMAP "won" by pivot, not by measurement. **The blur question is still open and is the top item for future work.**

---

## 7. How to make better, denser, more usable scenes

### Near-term (with the existing stack)

- **Finish the pose experiment properly.** Train the same building from VGGT poses vs COLMAP poses *in the same normalized coordinate frame* (the site-frame LR blow-up is what killed the A/B). If poses are confirmed as the blur source, add a pose-refinement stage (see papers below).
- **Scale budget with area, always.** The scene04/06 collapse proves the failure is mechanical. Either budget-per-cell scaling in `select_chunk`, or tile everything into building-sized units and train each with Recipe B, then compose.
- **Batch the building recipe.** 8 buildings detected on Iona, 10 on Sanibel; only 3 trained. One building ≈ 45 min on one L40S — a full site is an overnight run across the 4 GPUs. The planned `build_house.py` one-command orchestrator (select → train → prune → verify) was designed but never built; it's the highest-leverage missing piece.
- **Process the untouched sites.** Siesta-Dr (SfM not yet run), both Palmeto-Palms sets (fully untouched).
- **Denser where it matters:** with `--loss-bbox` containing memory, the in-box density can be pushed much higher — bldg01 used only a 500 K cap with 13.7 % in-box; raising cap + target in-box fraction is untested headroom.
- **More holdout discipline:** every future run should keep `--holdout-every 10`; the early packaged scenes have no PSNR record at all.
- **Merge and package.** `feat/select-building` (9 commits, reviewed) is unmerged; house splats live only under `work/`. Package them into `scenes/` with the same triplet layout so deliverables are reproducible.

### New pipelines / papers worth adopting (as of mid-2026)

**Pose quality & the blur problem — most directly relevant:**
- **3R-GS** — jointly optimizes camera poses *with* the 3DGS scene starting from feed-forward (MASt3R-SfM) initializations; exactly the "imperfect poses → blur" problem. Retrofit: add a camera-pose optimizer to `train_block` following its practices. ([project page](https://zsh523.github.io/3R-GS/), [paper](https://arxiv.org/pdf/2504.04294))
- **JOGS** — joint pose + splat optimization that reports beating even COLMAP-initialized baselines; COLMAP-free. ([arXiv 2510.26117](https://arxiv.org/abs/2510.26117))

**VGGT successors — faster/better feed-forward geometry:**
- **VGGT-Omega** (CVPR 2026 oral) — the direct successor to VGGT-1B: better depth, lower memory, same single-forward-pass workflow. Drop-in candidate for `vggt_scene.py`. ([project page](https://www.robots.ox.ac.uk/~vedaldi/research/2026/vggt-omega/vggt-omega.html))
- **FastVGGT** — training-free acceleration of VGGT for longer frame sequences. ([arXiv 2509.02560](https://arxiv.org/pdf/2509.02560))
- **VGG-T³** — offline feed-forward reconstruction at scale (thousands of frames), relevant to whole-site geometry in one shot. ([arXiv 2602.23361](https://arxiv.org/html/2602.23361v1))
- Survey for orientation: [From DUSt3R to VGGT](https://arxiv.org/pdf/2507.08448).

**Direct feed-forward splatting (skip per-scene optimization entirely):**
- **AnySplat** (SIGGRAPH/TOG 2025) — one forward pass from uncalibrated images → gaussians + poses + intrinsics. Could replace the whole SfM→train loop for quick-turnaround previews; per-scene optimization still wins on final quality. ([paper](https://arxiv.org/html/2505.23716v1), [TOG](https://dl.acm.org/doi/10.1145/3763326))
- **ReSplat** — recurrent refinement of feed-forward gaussians. ([arXiv 2510.08575](https://arxiv.org/pdf/2510.08575))

**Denser / higher-fidelity training (upgrades to the MCMC strategy we use):**
- **ImprovedGS** (CVPR 2026) — better when/how-to-densify decisions; better quality with *fewer* gaussians. ([code](https://github.com/XiaoBin2001/Improved-GS), [paper](https://arxiv.org/pdf/2508.12313))
- **GDAGS** — gradient-direction-aware density control, composes with MCMC-3DGS (our strategy). ([arXiv 2508.09239](https://arxiv.org/pdf/2508.09239))
- **Learnable density control** — replaces heuristic densification hyperparameters. ([arXiv 2605.00408](https://arxiv.org/pdf/2605.00408))

**Large-scale / aerial-specific:**
- **HUG** — hierarchical urban gaussians with block-based reconstruction for large aerial scenes; the principled version of our ad-hoc chunking. ([arXiv 2504.16606](https://arxiv.org/pdf/2504.16606))
- **Momentum-GS** — momentum self-distillation for high-quality large-scene reconstruction across blocks. ([arXiv 2412.04887](https://arxiv.org/pdf/2412.04887))
- **UAV GS pipeline survey** — end-to-end drone-video → 3DGS with quality within 4–7 % of offline references. ([arXiv 2602.20342](https://arxiv.org/abs/2602.20342))
- Domain-specific: [Manhattan-constrained UAV splatting](https://doi.org/10.3390/electronics15081647), [structure-sensitive density control for UAV orthophotos](https://doi.org/10.3390/rs18091400).

### Suggested priority order
1. Pose refinement in-loop (3R-GS-style) — attacks the one confirmed quality ceiling (blur).
2. `build_house.py` orchestrator + batch all detected buildings — turns the proven recipe into scalable output.
3. VGGT-Omega swap-in + redo the pose A/B cleanly — decides whether SfM can be dropped for new sites.
4. ImprovedGS/GDAGS densification — denser detail per gaussian budget.
5. HUG-style hierarchical composition — whole-site deliverables assembled from per-building splats.
