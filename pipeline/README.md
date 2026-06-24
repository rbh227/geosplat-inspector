# SplatAgent Pipeline

Generate 3D Gaussian Splats from images or video. Produces a `.ply` file and JSON manifest for the SplatAgent viewer.

## Pipeline Stages

1. **Ingest** — Validate/normalize images or extract frames from video (ffmpeg). Blur filtering, dedup, resize.
2. **SfM** — COLMAP feature extraction, matching, and sparse reconstruction.
3. **Train** — Gaussian splat training using gsplat. Configurable iterations, densification, checkpointing.
4. **Export** — Write `.ply` (COLMAP Y-down coordinates) + `manifest.json`.

## Requirements

- Python 3.10+
- CUDA GPU + PyTorch with CUDA support
- [gsplat](https://github.com/nerfstudio-project/gsplat) (`pip install gsplat`)
- [COLMAP](https://colmap.github.io/install.html)
- ffmpeg (for video input)

## Install

```bash
cd pipeline
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Usage

```bash
# Full pipeline from images
splatagent-pipeline run --source images --input ./my_photos/

# Full pipeline from video
splatagent-pipeline run --source video --input ./my_video.mp4

# Custom config + fewer iterations
splatagent-pipeline run --source images --input ./photos/ --config pipeline.toml --iterations 7000

# Resume a previous run
splatagent-pipeline run --source images --input ./photos/ --resume ./runs/<scene-id>/

# Run a single stage
splatagent-pipeline stage --run-dir ./runs/<scene-id>/ --stage train --iterations 50000

# Check toolchain
splatagent-pipeline info

# Validate config
splatagent-pipeline validate --config pipeline.toml
```

## Config

All parameters are in `pipeline.toml`. Key sections:

| Section | Key params |
|---------|-----------|
| `[ingest.video]` | `fps`, `max_frames`, `blur_threshold` |
| `[ingest.images]` | `max_dimension` |
| `[sfm]` | `camera_model`, `matcher`, `min_registered_ratio` |
| `[train]` | `iterations`, `sh_degree`, learning rates, densification params |
| `[export]` | `max_sh_degree` |

## Output

Each run produces a directory under `./runs/<scene-id>/`:

```
runs/<scene-id>/
  images/            # Normalized frames
  sparse/0/          # COLMAP reconstruction
  train/             # Checkpoints + metrics
  output/
    scene.ply        # Gaussian splat model
    manifest.json    # Metadata for the viewer
  pipeline.log       # Structured log
```

## Coordinate Convention

The pipeline outputs PLY files in **COLMAP convention (Y-down)**. The SplatAgent viewer applies `rotation.x = Math.PI` to flip to Three.js Y-up.

## Known Limitations

- Training requires a CUDA GPU (no CPU or MPS fallback)
- COLMAP needs sufficient feature overlap between views — sparse/textureless scenes may fail
- Video dedup uses simple average hashing; fast camera motion may drop useful frames
