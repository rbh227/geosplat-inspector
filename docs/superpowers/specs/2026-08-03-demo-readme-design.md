# Demo README rework — design

**Date:** 2026-08-03
**Status:** approved in brainstorming; this doc records the design
**Goal:** rework the root `README.md` into the on-screen companion for a recorded demo video, telling the full story in presentation order — how the demo scenes were made (upstream pipeline), how every editor tool works, and how the two agents work — illustrated with hand-drawn-style diagrams.

## Deliverables

1. **Reworked root `README.md`** — story-first structure (see below); existing quick-start / model-backend / dev content is kept but demoted below the story.
2. **8 hand-drawn-style SVG diagrams** committed under `docs/diagrams/`, embedded in the README with `<img>` tags.
3. **Pipeline reference doc** — the full 3DAeroRelief pipeline summary (provided from the reconstruction repo session) saved verbatim as `docs/demo/2026-08-03-3daerorelief-pipeline-summary.md`, linked from the README.

No code, contract, or ARCHITECTURE.md changes. Docs-only.

## Key context

- The demo scenes were **not** produced by this repo's `pipeline/` directory. They come from a separate repo, `3DAeroRelief_Reconstruction` (branch `feat/select-building`): drone video of Hurricane Ian relief sites → frame thinning → COLMAP SfM → region/building selection → gsplat MCMC training with box-weighted budget + box-masked loss → anisotropy pruning → packaged `.ply` scenes. The README's pipeline section describes *that* pipeline as "how the demo scenes were made," notes it lives in a separate repo, and briefly mentions this repo's `pipeline/` as the untested in-repo equivalent.
- The two agents = the **Understand-stage analyst** (survey-first, look-only: app flies the camera, model answers from captures) and the **Clean-stage cleanup agent** (propose → operator approve/adjust/reject via ProposalCard → gated edit; good-cube crop then brush rounds).

## README structure (video order)

1. **Hero** — one-liner ("a local tool where an AI agent inspects, navigates, and cleans 3D Gaussian Splat scenes"), system-overview diagram, 3-bullet elevator pitch (browser is renderer *and* the agent's eyes; CPU-only backend owns data/edits/agent loop; model-agnostic providers).
2. **How the demo scenes were made** — pipeline diagram + tight prose walk of the 7 stages; a "what went wrong (and got fixed)" call-out box with 3–4 of the best failure modes (budget dilution, background-inflation OOM, misleading orbit videos, needle artifacts); headline numbers (e.g. Iona bldg01: 12,375 gaussians, 2.9 MB, holdout PSNR 21.67); link to the full reference doc.
3. **The editor** — 4 family subsections, one diagram each:
   - Screen-space selection: brush (`[`/`]` resize), lasso, polygon; Alt = remove, Escape = cancel.
   - Volume selection: sphere + box with live SplatEdit SDF dim-preview.
   - Navigation: orbit vs fly (WASD/QE, drag-look, movement pad that lights for any input source including the agent).
   - Edit ops & history: delete/keep/invert/clear; every destructive edit lands in the backend `History` via `/edit`; local stack mirrors for instant undo; stable splat IDs across compaction.
4. **The two agents** — stage-gating intro (Clean = full 40-tool surface, Understand = look-only, edits rejected at spec AND dispatch), then one subsection + diagram per agent:
   - Analyst (Understand): survey flight → framed captures → model answers only from what it saw.
   - Cleanup (Clean): propose_decision kinds, ProposalCard approve/reject/adjust loop, approval binds the exact reviewed operation, selection tint, stop/pause semantics.
5. **Quick start** — existing content (Docker one-liner, native setup, gear-icon provider config).
6. **Model backends / development** — existing content.

## Diagrams (8)

All in `docs/diagrams/`, hand-authored SVG, excalidraw-like aesthetic: wobbly rounded rectangles (slight path jitter), sketchy arrows, handwritten font stack (`Virgil, Segoe Print, Bradley Hand, Comic Sans MS, cursive`), each diagram on an opaque warm-paper rounded card so it renders identically on GitHub light and dark themes.

| File | Content |
|---|---|
| `system-overview.svg` | Browser (SparkJS renderer = agent's eyes, editor UI) ↔ REST/WS ↔ FastAPI backend (splat data, metrics, history, agent loop) ↔ model provider; Clean/Understand stage switch shown as a gate on the tool registry |
| `pipeline.svg` | Drone frames → thin (sharpness) → COLMAP SfM → select region/building → train (gsplat MCMC, box-weighted budget, loss mask) → prune → package → `.ply` into SplatAgent; VGGT feed-forward branch drawn as dashed alternate path |
| `editor-screenspace.svg` | Brush / lasso / polygon acting on the viewport; Alt-remove and resize affordances |
| `editor-volumes.svg` | Sphere + box volumes with SDF dim-preview before commit |
| `editor-navigation.svg` | Orbit pivot vs fly (WASD + pad); pad lighting up for agent input |
| `editor-history.svg` | Manual + agent edits → `/edit` → backend History (authoritative) with mirrored local undo stack; ID stability across compaction |
| `agent-analyst.svg` | Understand loop: question → app-flown survey flight → captures persisted per scene conversation → answer; edit tools crossed out |
| `agent-cleanup.svg` | Clean loop: analyze → propose (good-cube / delete-selection / keep-only / bulk-edit) → ProposalCard (approve / adjust-with-feedback / reject) → gated edit → verify → next round |

## Non-goals

- No changes to `pipeline/` code or docs beyond the honest one-line framing in the README.
- No mermaid (GitHub's renderer won't honor the hand-drawn look).
- No screenshots/GIFs of the live app in this pass (can be added later; the video itself shows the live app).

## Acceptance

- README reads top-to-bottom as the video script's skeleton in the agreed order.
- All 8 SVGs render on GitHub in both themes with legible text.
- Existing setup instructions survive intact (moved, not deleted).
- Full pipeline summary reachable from the README at `docs/demo/2026-08-03-3daerorelief-pipeline-summary.md`.
