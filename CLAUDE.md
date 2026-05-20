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
- GPUs: 4× L40 (use one for training)

## Conventions

- All pipeline scripts are runnable as `python pipeline/scripts/<name>.py --help`.
- Data products go in `pipeline/data/{raw,frames,colmap,splats}/<scene_name>/`.
- Viewer code follows Next.js App Router conventions; no Pages Router.
- Anthropic API key lives in `viewer/.env.local`, never committed.
- Skills in `.claude/skills/` are project-scoped and version-controlled.

## Scenes

(Update this list as scenes are added.)

- (none yet)

## Status

Phase 0 in progress. See docs/00-start-here.md.
