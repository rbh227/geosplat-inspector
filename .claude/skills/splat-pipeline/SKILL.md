---
name: splat-pipeline
description: Use when running the Gaussian splat training pipeline on Jetstream. Triggers on phrases like "train a splat", "process scene", "run colmap", "ns-train", "splatfacto", "new scene", or any reference to scenes in pipeline/data/. Use when the user wants to convert a video into a renderable .ply file, or wants help debugging COLMAP/gsplat failures.
---

# Splat training pipeline

## Pre-flight checks

Before running anything, confirm:
1. SSH'd into Jetstream (`ssh exouser@149.165.173.161`).
2. Conda env active: `conda activate geosplat`.
3. GPU visible: `nvidia-smi` shows at least one L40.
4. Working directory: `/media/volume/Tene_Volume/geosplat-inspector/pipeline`.

## Standard pipeline for a new scene

Given `data/raw/<scene>.mp4` or a folder of images:

1. **Extract frames** (skip if already images):
   ```
   mkdir -p data/frames/<scene> data/colmap data/splats
   ffmpeg -i data/raw/<scene>.mp4 -vf fps=5 data/frames/<scene>/%04d.jpg
   ```
   Target: 100–300 frames. Adjust fps to land in that range.

2. **Run COLMAP via nerfstudio**:
   ```
   ns-process-data images --data data/frames/<scene>/ \
       --output-dir data/colmap/<scene>/
   ```
   Watch for: "registered N images". N should be ≥ 90% of frame count.
   Expected time: 5–30 min depending on frame count.

3. **Train the splat**:
   ```
   ns-train splatfacto --data data/colmap/<scene>/ \
       --output-dir data/splats/<scene>/ \
       --max-num-iterations 30000
   ```
   Watch PSNR climbing past 25 by iteration 5000.
   Expected time: 20–45 min on one L40.

4. **Export .ply**:
   ```
   ns-export gaussian-splat \
       --load-config data/splats/<scene>/<run_id>/config.yml \
       --output-dir data/splats/<scene>/
   ```

5. **Verify** by checking the .ply file size (50–500 MB is normal).

## Common failures

- **COLMAP registers <50% of frames**: scan motion was too fast or had
  insufficient overlap. Re-record slower, or extract frames at higher fps.
- **Training diverges (loss → NaN)**: usually bad poses from COLMAP.
  Re-inspect the colmap output, especially the camera trajectory.
- **PSNR plateaus below 20**: scene has lots of moving objects, reflections,
  or transparent surfaces. Splats struggle with these.

## After training

Copy the .ply down to laptop, or upload to Vercel Blob for the viewer:
```
scp exouser@149.165.173.161:/media/volume/Tene_Volume/geosplat-inspector/pipeline/data/splats/<scene>/*.ply ./local_splats/
```

## Notes on data layout

Each scene's outputs live under `data/<stage>/<scene>/`. Never mix scenes
in one folder. If retraining, delete the old `data/splats/<scene>/` first
or use a versioned suffix.
