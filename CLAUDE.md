# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# SplatAgent (GeoSplat Inspector)

## What This Is
A local tool where an AI agent autonomously inspects, navigates, and cleans up 3D Gaussian Splatting (`.ply`) scenes. Python backend owns the data/metrics/agent loop; thin TypeScript/React frontend renders via Three.js + SparkJS.

## Architecture Overview
See ARCHITECTURE.md for the full spec. Key points:
- **Python backend** (FastAPI): splat data, metrics, editing, model providers, agent loop
- **TS/React frontend**: renderer (SparkJS), camera, canvas capture, UI
- **Communication**: REST + WebSocket
- **CPU-only**: no CUDA, browser is the renderer AND the agent's eyes
- **Model-agnostic**: `ModelProvider` interface, Gemini Flash default

## Agent Boundary Map (ARCHITECTURE.md §5)

| Boundary | Owner | Path | Edits |
|----------|-------|------|-------|
| Contracts | FROZEN (Phase 0) | `/backend/contracts/`, `/frontend/src/contracts.ts` | **Never** — stop and raise |
| Splat data layer | Agent 1 | `/backend/splat/` | loader, numpy model, alive mask, exporter, spatial |
| Analysis & editing | Agent 2 | `/backend/analysis/` | metrics engine, editing engine, selection, history |
| Agent loop | Agent 3 | `/backend/agent/`, `/backend/providers/` | perceive→act→verify loop, tool dispatch, model adapters |
| API server | Agent 4 | `/backend/api/`, `/backend/server.py`, `Dockerfile`, `docker-compose.yml` | FastAPI REST + WS, scene serving, state |
| Frontend agent | Agent 5 | `/frontend/src/agent/` (new) | WS client, frontend tool executors, panel wiring |

**Rule:** An agent edits only its own folder(s). Import from `/backend/contracts/` freely; never edit contracts.

## Build / Lint / Test Commands

### Frontend
```bash
npm install
npm run dev                   # Vite dev server (http://localhost:5173, COOP/COEP headers)
npm run build                 # tsc -b type-check + vite production build → dist/
npm run lint                  # eslint (flat config)
npx tsc --noEmit              # type-check only
```

### Backend
```bash
cd backend && pip install -e ".[dev]"    # or: pip install -r requirements.txt
pytest                                    # run all backend tests
pytest backend/splat/tests/              # run splat layer tests only
pytest -x -v                             # stop on first failure, verbose
python -m mypy backend/                  # optional type-check
```

### Docker (CPU-only)
```bash
docker compose build          # builds python:3.12-slim + deps (no CUDA)
docker compose up              # backend on :8000
```

### Pipeline (needs CUDA GPU — separate from the backend)
```bash
cd pipeline && pip install -e .
splatagent-pipeline run --source images --input ./photos/
```

## Project Structure
```
/backend
  /contracts/        ← FROZEN. Shared schemas, interfaces, constants.
    __init__.py       Exports everything
    constants.py      §6.2: SH_C0, FLOATER_ALPHA, OUTLIER_K, etc.
    splat_model.py    §6.3: SplatModel Protocol
    metrics.py        §6.4: Metrics TypedDict
    tools.py          §6.5: TOOL_REGISTRY, TOOL_BY_NAME, FRONTEND_TOOLS, BACKEND_TOOLS
    model_provider.py §6.6: ModelProvider Protocol, ToolSpec, ToolCall, ModelResponse
    frontend_channel.py §6.8: FrontendChannel Protocol
  /splat/            Agent 1: loader, numpy model, exporter, spatial
  /analysis/         Agent 2: metrics engine, editing engine, selection, history
  /agent/            Agent 3: agent loop, tool dispatch
  /providers/        Agent 3: ModelProvider adapters (Gemini, stubs)
  /api/              Agent 4: FastAPI REST + WebSocket
  server.py          Agent 4: app entrypoint

/frontend
  /src/contracts.ts  ← FROZEN. TS mirror of API + WS + tool contract.
  /src/agent/        Agent 5: WS client, frontend tool executors

/examples
  clean.ply          1000 Gaussians (sphere) — well-behaved test scene
  messy.ply          1200 Gaussians (sphere + 80 floaters + 60 outliers + 60 needles)
  generate_test_scenes.py  Script that produced both PLY files

src/                 Existing frontend (React + Vite + SparkJS)
pipeline/            Offline generation pipeline (separate from backend)
```

## Key Conventions
- **Coordinates**: Pipeline outputs COLMAP Y-down. Viewer applies `mesh.rotation.x = Math.PI` to flip to Three.js Y-up.
- **PLY format**: Binary little-endian, INRIA header order: x/y/z, nx/ny/nz, f_dc_0..2, f_rest_0..44, opacity, scale_0..2, rot_0..3. Raw values (log-scale, logit-opacity).
- **Import alias**: `@/` resolves to `src/` (vite.config.ts + tsconfig)
- **API keys**: via env only (`VITE_GEMINI_API_KEY` for frontend, `GEMINI_API_KEY` for backend). Never in code/image.
- **Dev server**: `npm run dev` (Vite with COOP/COEP headers for SharedArrayBuffer)

## What Works (Fully Wired)
- Welcome page with animated 3D robot scene
- Drag-drop or click-to-load `.ply`/`.splat`/`.spz`/`.ksplat` files
- SparkJS Gaussian splat renderer with orbit controls
- Existing browser-based Gemini agent with 16 tools (being replaced by backend agent)
- Capture frame → send screenshot to Gemini as image for analysis
- Basic cleanup: opacity filter, outlier removal, bbox crop
- Advanced cleanup: scale filter, color filter, density filter, height filter, auto-clean pipeline
- All cleanup operations reversible with undo stack
- Chat UI with action history display
- Real-time HUD (splat count, FPS, camera position)

## What's Not Done / Known Issues
- **Backend not yet implemented**: agents 1–5 build the server-side agent
- **Pipeline not tested end-to-end on GPU**: gsplat/PyTorch compatibility issue
- **No persistent storage**: no save/export of cleaned splats across sessions

## gstack
- **Web browsing**: ALWAYS use the `/browse` skill from gstack for all web browsing. NEVER use `mcp__claude-in-chrome__*` tools.
- **Available skills**: `/office-hours`, `/plan-ceo-review`, `/plan-eng-review`, `/plan-design-review`, `/design-consultation`, `/design-shotgun`, `/design-html`, `/review`, `/ship`, `/land-and-deploy`, `/canary`, `/benchmark`, `/browse`, `/connect-chrome`, `/qa`, `/qa-only`, `/design-review`, `/setup-browser-cookies`, `/setup-deploy`, `/setup-gbrain`, `/retro`, `/investigate`, `/document-release`, `/document-generate`, `/codex`, `/cso`, `/autoplan`, `/plan-devex-review`, `/devex-review`, `/careful`, `/freeze`, `/guard`, `/unfreeze`, `/gstack-upgrade`, `/learn`
