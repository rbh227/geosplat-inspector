# GeoSplat Inspector

Browser-based viewer for Gaussian splats of UAV/handheld scenes that an LLM
agent can semantically query.

## Architecture

- `pipeline/` — Python code that runs on Jetstream. Takes video → frames →
  COLMAP poses → trained Gaussian splat (.ply). One-time per scene.
- `viewer/` — Next.js + TypeScript app. Renders .ply files in browser via
  WebGL/WebGPU. Hosts the agent loop that calls Anthropic API with tools
  the agent uses to manipulate the view.

## Compute model

- Jetstream is a TRAINING RIG, not a runtime server. Spin up to process new
  scenes, shelve when done.
- Vercel hosts the always-on viewer + agent relay.
- .ply files are served as static assets (Vercel Blob for >100MB).

## Jetstream

- SSH: `ssh exouser@149.165.173.161`
- Persistent volume: `/media/volume/Tene_Volume/`
- Conda env: `geosplat`
- GPUs: 4× L40S (use one for training)

## Conventions

- All pipeline scripts are runnable as `python pipeline/scripts/<name>.py --help`.
- Data products go in `pipeline/data/{raw,frames,colmap,splats}/<scene_name>/`.
- Viewer code follows Next.js App Router conventions; no Pages Router.
- Anthropic API key lives in `viewer/.env.local`, never committed.
- Skills in `.claude/skills/` are project-scoped and version-controlled.

## Scenes

(Update this list as scenes are added.)

- `scene2` — first real-world capture. Trained two checkpoints with
  splatfacto on Jetstream (`pipeline/data/splats/scene2/`):
  - `splat_7k.ply` (7,000 iters, 63 MB, 265k Gaussians) — fast iteration baseline.
  - `splat_30k.ply` (30,000 iters, 65 MB, 271k Gaussians) — current dev
    default in `viewer/public/scene2.ply`. Marginal Gaussian-count
    gain over 7k; the win is in sharpness/color refinement.

## Status

Phase 2 chunk 1 in progress. Next.js viewer scaffolded; renders
`scene2.ply` with `@mkkellogg/gaussian-splats-3d`. See
`docs/00-start-here.md` for the overall plan and
`docs/01-jetstream-setup.md` for the GPU-side environment brief.
