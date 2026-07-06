# Manual QA Script — Editor-First Rework - Plan

- **Date:** 2026-07-06
- **Verifies:** `docs/plans/2026-07-05-001-feat-editor-first-rework-plan.md` (Definition of Done: AE1–AE5 + SC1)
- **Status:** ready to run — this is the one open step from the 2026-07-05 implementation run; all automated gates were green at hand-off (121 backend pytest, 54 frontend vitest, `tsc -b`, eslint, production build)
- **Test scenes:** `examples/messy.ply` (1200 Gaussians: sphere + 80 floaters + 60 outliers + 60 needles), `examples/clean.ply` (control)

How to use: run parts in order. Part 1 needs no model key. Part 2 needs a live vision model. Check each `[ ]` as it passes; on failure, note the test ID and observed behavior in the Results section at the bottom — don't stop the session unless the failure blocks later tests.

---

## Part 0 — Setup and pre-flight

### 0.1 Re-run automated gates (confirm nothing drifted since 2026-07-05)

- [ ] `cd backend && pytest` → all green
- [ ] `npm run build` → type-check + production build pass
- [ ] `npx vitest run` → all green
- [ ] `npm run lint` → clean

### 0.2 Launch

```bash
# Terminal 1 — backend (repo root)
uvicorn backend.server:app --port 8000

# Terminal 2 — frontend dev server (proxies /api + /ws to :8000)
npm run dev        # http://localhost:5173
```

For Part 2, first copy `backend/.env.example` → `backend/.env` and set a model path:
Gemini (`GEMINI_API_KEY`) or local vLLM via SSH tunnel on `:8001` (see README "Local vLLM runbook").

- [ ] Backend starts without the `[agent] real runner unavailable` stub warning (Part 2 only — stub is fine for Part 1)
- [ ] Frontend loads at `http://localhost:5173` with the editor shell (no console errors)

---

## Part 1 — Editor features (no model required)

### T1. Editor shell + HUD

- [ ] Empty state prompts for a scene; drag-drop `examples/messy.ply` loads it
- [ ] Layout matches the Postshot mold: top bar (stage switcher Clean/Understand, orbit/fly toggle, HUD), left tool rail, viewport-dominant center, right chat panel
- [ ] No metrics panel, capabilities panel, or welcome page anywhere
- [ ] HUD shows splat count (1200 for messy.ply), live FPS, camera position; count updates after edits
- [ ] Skill pills render in the chat panel (names match `GET /agent/skills`)

### T2. Selection tools (run each on `messy.ply`)

Common grammar, verify once per tool where noted:

- [ ] **Brush** — ring cursor follows pointer; `[` / `]` shrink/grow it; painting selects splats under the stroke
- [ ] **Lasso** — freehand loop selects enclosed splats
- [ ] **Polygon** — click ≥3 vertices; closes on snap-to-first-vertex or double-click; fewer than 3 verts cannot close
- [ ] **Sphere** — drag defines the volume; selected region shows the live SDF dim-preview (dimmed splats match the volume position — no Y-flip offset)
- [ ] **Box** — same as sphere with box volume
- [ ] **Modifiers** — Alt-drag removes from an existing selection; Escape cancels an in-progress selection; Invert and Clear behave as named
- [ ] **Camera lock** — while a selection tool is active, dragging does not orbit the camera; switching back to a nav mode restores camera control
- [ ] **Delete / Keep** — Delete removes exactly the selected splats; Keep removes everything else; delete with empty selection is disabled/no-op
- [ ] Select the visually obvious floaters around the sphere and delete them → the sphere looks clean, HUD count drops accordingly

### T3. Fly navigation + move pad

- [ ] Orbit/fly toggle switches modes; orbit still works as before
- [ ] In fly mode: W/A/S/D translate, Q/E move down/up, drag-to-look rotates
- [ ] On-screen move pad buttons drive the same motion as keys
- [ ] Pad buttons light up when the corresponding key is held (pad reflects ANY input source)
- [ ] Toggling fly → orbit keeps the camera pointing at a sensible target (no snap to origin, no crash — the FlyControls `.target` regression)

### T4. Unified history + stable IDs (the highest-risk manual test)

The frontend index→ID map must survive undo, or later selections delete the wrong splats.

- [ ] Make selection edit A (delete some floaters) → undo → scene restores exactly (compare HUD count)
- [ ] **After** that undo, make a new selection B elsewhere and delete → exactly the splats you selected disappear (wrong-splat deletion here = ID-map-on-undo bug)
- [ ] Interleave: manual delete → second manual delete → undo → undo → both revert in LIFO order, scene back to 1200
- [ ] Undo is instant (frontend mirror), and a subsequent edit still round-trips the backend correctly
- [ ] Kill the backend mid-session, attempt a delete → status toast appears and the viewer reloads/recovers to the authoritative scene when the backend returns (failed-edit recovery path)

### T5. Contracts drift guard (spot-check)

- [ ] `pytest backend/contracts/tests/` and `npx vitest run frontend/src/agent/contracts.test.ts` both green (already covered by 0.1 — just confirm they ran)

---

## Part 2 — Agent features (live model required)

Use `messy.ply` unless noted. Analyst answer *quality* is a known-untuned area — for AE3 the pass bar is structural (navigates, captures, answers about visual content), not count accuracy.

### T6. Clean-stage agent run + visible operation

- [ ] In Clean stage, ask the agent to clean the scene → it runs with visible tool use: camera moves light the move pad, sphere/box selections flash the SDF preview before committing, screen-space selections draw at human-visible pace
- [ ] Agent edits appear in the same history: after the run, undo reverts the agent's last edit (AE4 setup)
- [ ] Scene is visibly cleaner at the end; HUD count dropped

### T7. Pause / takeover (AE1 — covers R13, R14)

- [ ] Mid-run, press W (or pick a selection tool) → agent pauses at the next tool-call boundary; your input takes effect immediately
- [ ] Pause banner appears and persists until you act — it does not auto-dismiss
- [ ] Stage switcher is disabled during the run (confirm-cancel behavior when paused, if prompted)
- [ ] Make a manual edit while paused, then Resume → agent continues the same run and its next steps reflect the updated scene (no stale-state crash)
- [ ] Stop (instead of Resume) cleanly ends the run
- [ ] Pause during an in-flight tool call takes effect after that call returns, not mid-call (no half-drawn stroke)

### T8. Agent undo (AE4 — covers R6)

- [ ] Sequence: agent deletes region X → you manually delete region Y → undo → Y restores → undo → X restores. Exactly the agent's edit reverts on the second undo, regardless of author interleaving

### T9. Understand-stage gating + analyst Q&A (AE2, AE3 — covers R15, R16)

- [ ] Switch to Understand stage; ask "clean this up" → no edit occurs, splat count unchanged, agent responds without editing tools (AE2)
- [ ] Ask "what is in this scene?" → analyst moves the camera, captures views, then answers describing visual content — not Gaussian counts or metrics (AE3 structure)
- [ ] On a real scene if available: ask a counting question ("how many damaged buildings?") → answer includes a count and what it saw; log accuracy for the tuning backlog, don't fail the run on it
- [ ] Switch back to Clean → editing tools work again

### T10. Skill pills (AE5 — covers R11)

- [ ] Click a movement skill pill (e.g. "hover around") → the same routine runs the agent would compose: same visible camera movement, same pacing, pad lights up

---

## Part 3 — SC1 full demo path (end to end, one unbroken session)

Reload fresh and run the whole arc without restarting anything:

- [ ] Load `messy.ply` → watch agent clean it with visible tool use → touch up by hand (one manual selection+delete) → undo something → switch to Understand → ask two questions, get sensible answers → no metrics panel or suggested prompt touched at any point
- [ ] Session survives the stage switch and mixed manual/agent editing with no console errors or backend tracebacks

---

## Results

| Test | Result | Notes |
|------|--------|-------|
| 0.1 gates | | |
| T1 shell | | |
| T2 selection | | |
| T3 fly nav | | |
| T4 history/IDs | | |
| T5 contracts | | |
| T6 clean run | | |
| T7 pause (AE1) | | |
| T8 undo (AE4) | | |
| T9 analyst (AE2/AE3) | | |
| T10 skills (AE5) | | |
| SC1 demo | | |

**On failure:** capture the test ID, repro steps, console/backend output, and file it against the owning boundary (see CLAUDE.md boundary map). Known non-failures: analyst count accuracy (untuned by design), selection latency on 600K+ scenes (O(N) loops, optimization deferred).

**When all green:** the 2026-07-05 plan's Definition of Done is met — commit the rework (nothing is committed yet on `fix/agent-camera-and-cleanup-bugs`).
