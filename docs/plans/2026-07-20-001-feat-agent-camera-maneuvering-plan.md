# Implementation Plan: Agent Camera Maneuvering (A + B + C)

**Session:** developer / SplatAgent — "make the agent genuinely operate the splat."
**Scope:** the agent's ability to move, look, zoom, and orbit real (off-origin,
large-extent) scenes reliably, driving the same primitives a human uses.

**Intent confirmed with the user (2026-07-20):**
- The goal is three working capabilities in dependency order: **navigate →
  analyze → clean** the excess/messy Gaussians. Navigation is the current
  blocker for all three, so it goes first.
- **Navigate like a human is a hard requirement:** relative move/turn/zoom
  guided by what the agent SEES — steer AWAY from absolute-coordinate jumps,
  don't just patch them. → **Phase B is core, not optional.**
- **Loop rhythm is batched:** chain a few relative moves, then capture to check
  (not a look-after-every-step loop). → keep the existing batched loop.

**CORRECTION (2026-07-20, after a live run still failed):** the operator-seeded
viewpoint is NOT a bonus — it is the **PRIMARY navigation model.** Evidence: even
with working grounding, `get_bounds` returns the raw min/max over ALL Gaussians
(floater-polluted → a 244k-unit box), so the "center" the agent correctly used
was the center of a mostly-empty volume → the subject frames to a speck → "spazz."
The whole coordinate approach is fragile at the root.

**The requirement (user's words):** the agent must ANCHOR to the operator's
current camera pose — the zoom and angle the user is already at — and maneuver
from there using the on-screen BUTTONS (move pad, rotate pad, zoom): relative,
human-like, never teleporting to a computed world coordinate. This bypasses
bounds/center entirely — no correct coordinate is ever needed to navigate.

→ **Phases B and C MERGE and both become core.** The absolute-coordinate and
reset/teleport tools are removed from the offered nav set so the agent CANNOT
fling itself away from the operator's view. Sequencing: Phase 0 (done) → A (done,
frustum) → **B+C merged: anchor-to-pose + button-only relative nav.**

## Problem (evidence-backed, from the understand pass)

Three coupled defects make agent navigation glitch on real scenes:

1. **The frustum never follows the camera.** `updateNearFar()` is called ONLY
   inside `frameScene()` (on load) — `SceneManager.ts:1493,1505`. The render
   loop (`:204-222`) and the agent's per-frame `setCameraPose(...,animate=false)`
   path (`:272-315`) never recompute `camera.near/far`. When the agent flies the
   camera farther than the load distance, the splat crosses the stale far plane
   and is **clipped → blank / flicker ("glitch")**. This is the primary bug.
2. **Framing distance is large and untamed.** `reset_view`/`frame_object` →
   `poseForBox` → `framingDistance = radius·1.6/sin(fit/2)` (`camera.ts:100-105`).
   A ~15k core radius flies the camera ~40k units out ("zooms out a bunch").
   Correct in principle, but with (1) it lands in clipped space.
3. **No relative "look/turn" primitive for the agent.** The registry has
   absolute-coordinate tools (`look_at`, `set_view`, `orbit`) the model can't
   compute for off-origin scenes, plus `dolly` (zoom) and `move_camera` (WASD
   holds). The human's yaw/pitch rotate-pad (`setRotationInput`) is NOT on the
   agent bridge or exposed as a tool. The agent can strafe but can't turn.

The human WASD is reliable because it shares `setMovementInput` with the agent;
the agent fails because its *other* primitives teleport it into clipped space
before any WASD hold runs.

## Design decisions

- **A — fix the shared core first.** Cache the scene radius; recompute near/far
  every frame from the current camera→target distance. One seam, always correct.
  Nothing else works reliably until this lands.
- **B — additive relative vocabulary.** The contract is frozen "additions only"
  (`tools.py:3-6`), so we **bump v0.2→v0.3 and ADD** a relative `turn` tool
  (yaw/pitch, mirroring the human rotate-pad); we do NOT remove `look_at`/`orbit`.
  We *curate what's offered/taught*: the system prompt + skills teach the
  relative set (`move_camera`, `turn`, `dolly`, `frame_object`, `reset_view`) as
  the primary way to navigate and demote absolute-coordinate tools.
- **C — human-seeded viewpoint (DEFERRED).** Confirmed a bonus, not the design.
  Not built in this pass. If revisited: the run's WS `channel` already pulls
  frontend state (selection), so a `get_pose` pull could let `_seed_grounding`
  hand the model the operator's current view. Left out for now.

- **Phase 0 — cheap bounds (from the Codex adversarial review).** `_seed_grounding`
  currently dispatches `get_metrics`, which runs full-scene k-NN — a heavy
  startup pass on every run (incl. look-only Understand), stalling large scenes
  before any visible action. Replace it with a cheap bounds-only accessor
  (`model.bounds()` is a single min/max pass, no k-NN). Prerequisite: Phase A's
  relative-move sizing and `reset_view` both need scene scale, and B/analysis
  build on this seed — clean it before extending.

## File map

**Phase A — camera core (frontend only)**
- `src/viewer/SceneManager.ts` — cache `coreRadius` (set on load/frame, invalidate
  in the `markSplatDirty()` seam); recompute near/far each frame in the render
  loop from current distance + cached radius. New private `refreshNearFar()`.
- `src/viewer/framing.ts` — (if needed) tighten `nearFarForDistance` guards; add
  a unit test for the "camera far from scene" case.
- `frontend/src/agent/camera.ts` — clamp the framing margin so `reset_view`
  doesn't overshoot (cap distance to a multiple of radius).

**Phase B — relative `turn` tool (contract v0.3, additive)**
- `backend/contracts/tools.py` — v0.3 header note; ADD `turn` ToolEntry
  (frontend), `{direction: enum[left,right,up,down], duration_ms}`.
- `frontend/src/contracts.ts` — mirror the `turn` entry.
- `backend/contracts/tests/test_tools.py` + `frontend/src/agent/contracts.test.ts`
  — drift guards include `turn`.
- `backend/agent/dispatch.py` — `_FRONTEND_CMD_TYPE["turn"] = "rotation_input"`.
- `backend/api/ws.py` — add `"rotation_input"`, `"get_pose"` to the command
  allow-list (`:29`).
- `frontend/src/agent/ws-client.ts` — add `'rotation_input'`, `'get_pose'` to
  `COMMAND_TYPES` and `switch` cases.
- `frontend/src/agent/executors.ts` — new `turn({direction,duration_ms})` (holds
  `setRotationInput`, mirroring `move_camera`); `get_pose()` returns pose+core.
- `frontend/src/agent/types.ts` — add `setRotationInput`, `getSceneCore` (done)
  to `RendererBridge`.
- `src/backend/bridge.ts` — map `setRotationInput`.
- `backend/agent/system_prompt.py` — teach the relative set; demote absolute
  tools; update `hover_around`/`survey_scene` recipes.

**Phase C — human-seeded viewpoint**
- `backend/agent/dispatch.py` — pull `get_pose` (like `get_selection`).
- `backend/agent/loop.py` — extend `_seed_grounding` with the operator pose +
  "start from this view, move relatively" guidance.
- `backend/agent/system_prompt.py` — navigation doctrine: begin from the
  operator's view; `reset_view` only when lost.

## Tasks (dependency order; each carries its own test cycle)

### Phase 0 — cheap bounds  *(Codex review fix; ship first)*

- [ ] **0.1 — grounding seed uses a bounds-only path, not full metrics.**
  Files: `backend/agent/dispatch.py` (or a small backend accessor),
  `backend/agent/loop.py`, `backend/agent/mocks.py`, `backend/agent/tests/`.
  Impl: give the dispatcher/executor a cheap `get_bounds()` (backed by
  `model.bounds()` — min/max only, no k-NN); `_seed_grounding` calls it instead
  of `get_metrics`. Keep it internal (no tool_call event, no ledger write); skip
  cleanly when unavailable.
  Test: `test_grounding_seed.py` — Understand seeding does NOT invoke the
  expensive metrics implementation (assert `get_metrics`/`compute_metrics` not
  called; a spy/mock counter), and the `[scene]` message still carries the real
  center from bounds.
  Verify: `pytest backend/agent`.

### Phase A — camera core  *(after Phase 0)*

- [ ] **A1 — near/far tracks the camera every frame.**
  Files: `src/viewer/SceneManager.ts`.
  Impl: add `private coreRadius = 0`; set it in `frameScene()` (from
  `computeCoreBounds`) and invalidate/recompute in `markSplatDirty()`. Add
  `private refreshNearFar()` that calls `nearFarForDistance(camera↔target dist,
  this.coreRadius)` and updates the projection matrix; call it once per frame in
  the render loop (`:204-222`), after the movement steps.
  Test: `src/viewer/framing.test.ts` — `nearFarForDistance(d, r)` keeps
  `far > d + r` for `d` up to 10× `r` (camera far from scene stays unclipped).
  Verify: `npm test`, `npx tsc --noEmit`; **manual (decisive): load a real
  off-origin scene, run an agent `reset_view`/orbit — viewport stays on the
  scene, no blank/flicker.**

- [ ] **A2 — tame framing overshoot.**
  Files: `frontend/src/agent/camera.ts`.
  Impl: in `framingDistance`/`poseForBox`, clamp the result to
  `≤ radius · MAX_FRAME_FACTOR` (e.g. 4) so `reset_view` frames the core without
  flinging to the far plane.
  Test: `frontend/src/agent/camera.test.ts` — `poseForBox` on a large box yields
  a camera distance within the clamp.
  Verify: `npm test`; manual: `reset_view` on a real scene frames the subject,
  not a distant dot.

- [ ] **Checkpoint A:** agent `reset_view` + orbit + a WASD hold on a real scene
  never blank or jump wildly. Type-check/lint/tests green. Then continue into
  Phase B (core — relative nav is the confirmed requirement, no hard-stop here).

### Phase B+C (merged) — anchor to operator view + button-only nav  *(after A; CORE)*

Decision (user, 2026-07-20): **strict button-only.** The agent anchors to the
operator's current pose (run-start already does NOT reset the camera —
`App.tsx:532`) and maneuvers ONLY with the on-screen buttons. The teleport/
absolute tools are REMOVED from the offered set so it physically cannot fling
away. The one missing button primitive is `turn` (the rotate pad).

Offered nav set after this phase: `move_camera` (move pad), `turn` (rotate pad),
`dolly` (zoom), `scan_pause`, `capture_frame`, `narrate`, `answer` (+ the
selection/edit tools in Clean). REMOVED from the offered set (kept in the
registry — contract is additive): `reset_view`, `look_at`, `set_view`, `orbit`,
`frame_object`, `capture_orbit`.

- [ ] **BC1 — add the `turn` tool end-to-end (contract v0.3).**
  Files: `backend/contracts/tools.py`, `frontend/src/contracts.ts`,
  `backend/contracts/tests/test_tools.py`, `frontend/src/agent/contracts.test.ts`,
  `backend/agent/dispatch.py`, `backend/api/ws.py`,
  `frontend/src/agent/{ws-client,executors,types}.ts`, `src/backend/bridge.ts`.
  Impl: ADD `turn` (frontend) `{direction: left|right|up|down, duration_ms}` →
  rotate-pad directions (left=yaw-left, right=yaw-right, up=pitch-up,
  down=pitch-down); dispatch → `rotation_input`; ws-client case → `executors.turn`
  → hold `bridge.setRotationInput(dir,true)`, sleep, `(dir,false)` (mirror
  `move_camera`; lights the rotate pad for the agent per R8). Add `setRotationInput`
  to `RendererBridge` + `bridge.ts`.
  Test: `test_tools.py` asserts `turn` in registry/`TOOL_BY_NAME`,
  `runs_on=frontend`; `contracts.test.ts` mirrors it; an executor test asserts
  `turn` toggles `setRotationInput` on a fake bridge.
  Verify: `pytest backend/contracts`, `npm test`, `npx tsc --noEmit`.

- [ ] **BC2 — gate the offered nav tools to the button-only set.**
  Files: `backend/agent/system_prompt.py` (`UNDERSTAND_TOOLS`, `stage_tools`/
  `build_tool_specs`), `backend/agent/tests/`.
  Impl: define `NAV_TOOLS = {move_camera, turn, dolly, scan_pause, capture_frame,
  narrate, answer}`; Understand offers exactly these; Clean offers these + the
  selection/edit/history tools; the teleport tools (`reset_view`, `look_at`,
  `set_view`, `orbit`, `frame_object`, `capture_orbit`) are offered in NEITHER
  stage. The dispatch backstop (`loop._handle_call`) already rejects unoffered
  tools, so a hallucinated teleport bounces.
  Test: `build_tool_specs("understand")` and `("clean")` exclude every teleport
  tool and include `turn`/`move_camera`/`dolly`; a loop test asserts a
  hallucinated `reset_view` is rejected (not dispatched).
  Verify: `pytest backend/agent`.

- [ ] **BC3 — prompt + skills: anchor-and-buttons doctrine.**
  Files: `backend/agent/system_prompt.py`.
  Impl: both stage prompts open with: "You START at the operator's current view —
  their chosen zoom and angle. Do NOT jump to coordinates; you have no teleport.
  Maneuver ONLY with the buttons: `move_camera` (W/A/S/D/Q/E), `turn` (look
  yaw/pitch), `dolly` (zoom). Take a few button moves, then `capture_frame` to
  check what you see." Rewrite `survey_scene`/`hover_around` to button sequences
  (move+turn+capture), drop the coordinate/`capture_orbit` recipes. The grounding
  seed stops pushing a nav center (coords no longer drive nav).
  Test: prompt-content assertions name `move_camera`/`turn`/`dolly` and the
  "start at the operator's view / no teleport" doctrine; the removed-tool names
  no longer appear as recommended nav.
  Verify: `pytest backend/agent`.

- [ ] **Checkpoint B+C (decisive, live):** from a view you framed, run the agent —
  it moves/turns/zooms from your vantage with the buttons, stays on the scene, and
  never jumps to a computed coordinate. Gates green; live behavior confirmed by you.

## Verification gates (per Iron Law)

- **Mechanical (this repo):** `pytest` (backend), `npx tsc --noEmit`, `npm run
  lint`, `npm test` — green after every task.
- **Decisive/behavioral (needs a browser + real scene + live model):** A is
  proven when agent reset/orbit/WASD on a real off-origin scene stays on-screen
  and steady. B/C are proven when the agent turns-to-face and dollies-in from the
  operator's view without coordinate guessing. *These require a manual live run;
  they are NOT proven by the test suite.*

## Open unknowns

- Whether A alone restores usable navigation (may make B/C lower-priority) —
  resolved at Checkpoint A.
- Live-model behavior with the relative vocabulary (B2/C2) is a prompt-tuning
  unknown; the CI proxies guard structure, not answer quality.
- Per-frame `updateProjectionMatrix()` cost at 600k+ splats — expected
  negligible (one matrix rebuild/frame), confirm if FPS regresses.

## Deferred (not in this plan)
- Removing/renaming absolute camera tools (contract forbids; demotion only).
- Phase C (operator-seeded viewpoint) — confirmed a bonus, not the design.
- **Cleanup "navigate like a human" carryover:** the same relative philosophy
  should apply to editing — prefer screen-space selection (brush/lasso on what
  the agent SEES) over world-coordinate spheres (the earlier radius-10000 sphere
  grabbing 1.9M was exactly this failure). Belongs to the cleanup workstream.
