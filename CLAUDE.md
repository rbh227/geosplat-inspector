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
| Contracts | Versioned per phase (v0.2 = editor phase) | `/backend/contracts/`, `/frontend/src/contracts.ts` | Frozen WITHIN a phase; extend only with a version bump + both mirrors + registry tests |
| Splat data layer | Agent 1 | `/backend/splat/` | loader, numpy model, alive mask, exporter, spatial |
| Analysis & editing | Agent 2 | `/backend/analysis/` | metrics engine, editing engine, selection, history |
| Agent loop | Agent 3 | `/backend/agent/`, `/backend/providers/` | perceive→act→verify loop, tool dispatch, model adapters |
| API server | Agent 4 | `/backend/api/`, `/backend/server.py`, `Dockerfile`, `docker-compose.yml` | FastAPI REST + WS, scene serving, state |
| Frontend agent | Agent 5 | `/frontend/src/agent/` (new) | WS client, frontend tool executors, panel wiring |

**Rule (historical, Phase-0 multi-agent build):** the boundary map documents the original split. Contracts now freeze per phase, not forever: v0.1 froze the Phase-0 build, v0.2 (editor-first rework, `docs/plans/2026-07-05-001`) added the spatial-selection/movement/selection-edit tools. Keep `backend/contracts/tools.py` and `frontend/src/contracts.ts` in sync — `backend/contracts/tests/test_tools.py` + `frontend/src/agent/contracts.test.ts` are the drift guards.

## Build / Lint / Test Commands

### Run everything (start here)
```bash
./scripts/dev.sh              # model endpoint (:8001) + backend (:8000) + Vite (:5173)
./scripts/dev.sh --no-model   # skip the model — viewer/editor only
./scripts/local-model.sh status   # is the GPU server / SSH tunnel up?
```
`dev.sh` verifies the agent's model is actually reachable (`POST /config/test`)
before handing you a URL. `provider error: Connection error.` in the chat panel
means the `:8001` tunnel is down — usually a VPN blip, while the vLLM server
itself is still up on the GPU box. Reconnect the VPN, then `scripts/local-model.sh up`.

### Frontend
```bash
npm install
npm run dev                   # Vite dev server (http://localhost:5173, COOP/COEP headers)
npm run build                 # tsc -b type-check + vite production build → dist/
npm run lint                  # eslint (flat config)
npx tsc -b                    # type-check only
```
**Use `tsc -b`, NOT `tsc --noEmit`.** `tsconfig.json` is solution-style
(`files: []` + project references), so `--noEmit` silently type-checks ZERO
files and always "passes".

### Backend
Needs **Python 3.12** — `open3d` (used by the splat data layer) has no wheel
for newer Pythons yet. If your system Python is newer, use the Docker path
below instead, or install 3.12 via `pyenv`/`uv`/homebrew.
```bash
python3.12 -m venv .venv-api && source .venv-api/bin/activate
pip install -r backend/requirements.txt pytest mypy
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

## What Works (Fully Wired) — editor-first app (docs/plans/2026-07-05-001)
- Classic editor shell (Postshot mold): top bar with Clean/Understand stage switcher + orbit/fly toggle, left tool rail, viewport-dominant center, right agent/chat panel
- Drag-drop or click-to-load `.ply`/`.splat`/`.spz`/`.ksplat` files
- SparkJS Gaussian splat renderer with orbit controls AND custom fly navigation (WASD/QE keys, drag-to-look, on-screen movement pad — the pad lights up for ANY input source, including the agent)
- Selection tools (SuperSplat grammar): brush (`[`/`]` resize, ring cursor), lasso, polygon (≥3 verts, snap/double-click close), sphere + box volumes with live SplatEdit SDF dim-preview; delete/keep/invert/clear; Alt = remove-from-selection; Escape cancels
- Stable splat IDs across compaction (`src/viewer/idMap.ts`): frontend and backend share one ID space; after backend reloads the viewer adopts `GET /ids`
- One logical edit history: every destructive edit (manual or agent) lands in the backend `History` via `/edit` (`delete_by_ids`/`keep_only_ids`); the local stack mirrors it for instant undo; failed backend edits reload the authoritative scene with a status toast
- Backend agent with stage-gated tools: Clean = full editor surface (40-tool v0.2 registry), Understand = look-only analyst (navigation/capture/answer; edits rejected at spec AND dispatch level)
- Skills vocabulary (`backend/agent/system_prompt.py` SKILLS): one list rendered into the system prompt and served via `GET /agent/skills`; clickable pills in the chat panel run the same routines the agent composes
- Agent visible operation: `move_camera` lights the pad, sphere/box selections flash the SDF preview before committing, screen-space selections are paced; pause-on-manual-input holds the loop at the next tool-call boundary with a Resume/Stop banner
- Proposed-and-reviewed cleanup (v0.5, agent-cleanup-proposals): the Clean-stage `cleanup_scene` pill runs a good-cube crop then brush rounds where every destructive step is gated — the agent must bank an operator-approved `propose_decision` (kinds: crop-outside-box, delete-selection, keep-only-selection, bulk-edit — the statistical sweeps are gated too, and each approval binds the exact reviewed operation) before a matching edit fires; a ProposalCard in the chat panel drives approve/reject/adjust, adjust feeds natural-language feedback back into the loop and re-shows the persistent proposal box (SDF dim + wireframe, `box_screen` percept). Selection tint marks the pending set; camera moves during review do NOT pause the run; Stop cleanly ends it
- Real-time HUD (splat count, FPS, camera position) in the top bar

## What's Not Done / Known Issues
- **Analyst answer quality untuned**: the Understand-stage capture-then-answer structure is tested (CI proxies in `backend/agent/tests/test_analyst_prompt.py`), but live-model counting accuracy on real post-disaster scenes needs manual iteration
- **Cleanup-flow model behavior untuned**: the propose→approve→edit machinery is fully tested headlessly (scripted-provider round-trip in `backend/agent/tests/test_proposals.py`, WS routing in `backend/api/tests/test_proposal_ws.py`), but how well a live model chooses good-cube bounds and brush targets on real scenes needs manual iteration
- **Selection loops are O(N) per operation**: fine at demo scale; 600K+ splat scenes may want the cached-centers/stride optimizations before heavy brush sessions
- **Pipeline not tested end-to-end on GPU**: gsplat/PyTorch compatibility issue
- **No persistent storage**: no save of cleaned splats across sessions (export via the backend `.ply` serve works)

## gstack
- **Web browsing**: ALWAYS use the `/browse` skill from gstack for all web browsing. NEVER use `mcp__claude-in-chrome__*` tools.
- **Available skills**: `/office-hours`, `/plan-ceo-review`, `/plan-eng-review`, `/plan-design-review`, `/design-consultation`, `/design-shotgun`, `/design-html`, `/review`, `/ship`, `/land-and-deploy`, `/canary`, `/benchmark`, `/browse`, `/connect-chrome`, `/qa`, `/qa-only`, `/design-review`, `/setup-browser-cookies`, `/setup-deploy`, `/setup-gbrain`, `/retro`, `/investigate`, `/document-release`, `/document-generate`, `/codex`, `/cso`, `/autoplan`, `/plan-devex-review`, `/devex-review`, `/careful`, `/freeze`, `/guard`, `/unfreeze`, `/gstack-upgrade`, `/learn`

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
- Author a backlog-ready spec/issue → invoke /spec
