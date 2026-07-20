# Implementation Plan: Agent Reliability — Boundary Correction (Codex review)

**Session:** developer / SplatAgent.
**Prereq committed:** `feat/agent-nav-buttononly` (c66d9f6) — button-only nav,
frustum tracking, cheap grounding, move_camera fix. This plan builds ON it.

## The thesis (Codex adversarial review, endorsed by the operator)

The failures this session share one root: **the model holds low-level control
(timed motor holds, guessed dolly distances, coordinate selection, authorizing
deletes) while its feedback is not tied to state.** The correct boundary:

- **The application owns** deterministic motion, capture freshness, camera state,
  and safety limits.
- **The model chooses** higher-level intentions and interprets *fresh* percepts.
- **Every percept is tied to** a camera pose and scene revision.
- **Destructive edits are constrained** by hard thresholds or operator approval.
- **Prompts supplement enforcement**, they do not replace it.

Adopt this **incrementally**, cheapest-highest-value first — not a big-bang
"navigation controller" rewrite. Each phase moves one responsibility from the
model to the app and proves it before the next.

## Design decisions

- **Keep the button primitives as fine-adjust fallback**, but add app-owned
  intention operations the model prefers. The model says "get closer to that
  cluster"; the app executes it deterministically and returns a fresh,
  state-tagged percept. (Reconciles "drive the buttons" with Codex's boundary —
  app-executed intent looks *more* purposeful than model-twitched holds.)
- **Percept integrity is foundational and goes first** — every later phase
  (framing feedback, cleanup review) depends on percepts that carry pose +
  revision.
- **Every destructive edit is gated** — operator approval (the existing
  pause/resume) and/or a hard threshold (the existing `silhouette_intact`
  subject-loss guard). No silent deletes.

## File map

**Phase R1 — percept integrity (pose + scene revision on every frame)**
- `src/viewer/SceneManager.ts` — expose a monotonic `getSceneRevision()` (bump in
  `markSplatDirty`, already the single edit seam).
- `src/types/viewer.ts`, `frontend/src/agent/types.ts`, `src/backend/bridge.ts` —
  thread `getSceneRevision` onto the bridge.
- `frontend/src/agent/executors.ts` (`capture_frame`) — return
  `{ png_base64, pose, revision }` (pose from `getCameraPose`).
- `backend/api/ws.py` — carry pose/revision through the capture reply decode.
- `backend/agent/loop.py` (`_handle_vision`) — record each frame's pose/revision;
  include a one-line "[percept @ pose … rev N]" note with the fed image; drop/
  re-request a percept whose revision is stale after an edit.

**Phase R2 — scale-aware framing (app owns "frame this")**
- `frontend/src/agent/framing.ts` (new, or extend `camera.ts`) — pure helper:
  project the scene core bounds to screen, return coverage fraction.
- `frontend/src/agent/executors.ts` — `capture_frame` also returns
  `coverage` (scene fills ~X% of view); add a deterministic `frame_subject`
  executor (move along the view axis until coverage ≈ target band, app-controlled
  loop) OR keep `dolly` but surface coverage so the model self-corrects.
- `backend/contracts/tools.py` (+ mirrors + drift tests) — add `frame_subject`
  (v0.4) if we go the deterministic-op route.
- `backend/agent/system_prompt.py` — teach: read the coverage signal; use
  `frame_subject` / adjust; never guess a raw distance blind.

**Phase R3 — two-page flow + default Analyze**
- `src/App.tsx` / stage UI — default stage = `understand` (Analyze); make the two
  pages visibly distinct so a cleanup is never launched by accident.
- (No agent-logic change — the stage gating from the prior commit already
  enforces look-only Analyze vs Cleanup.)

**Phase R4 — autonomous-with-review cleanup (good-cube + brush, gated)**
- `frontend/src/agent/executors.ts` — `propose_good_cube`: compute the dense-core
  AABB (reuse `coreBounds`/`sampleWorldPoints`), show it via the existing
  `showSelectionPreview('box', …)`, return `{ bbox, kept_count, outside_count }`.
- `backend/analysis/editing.py` — ensure crop-to-core (keep inside the cube,
  delete outside) is available and subject-loss-guarded.
- `backend/contracts/tools.py` (+ mirrors + drift) — `propose_good_cube` (v0.4)
  and the review-gated crop.
- `backend/agent/loop.py` — the review gate: after a proposal, PAUSE for operator
  approval (existing pause/resume) before the destructive crop; hard-threshold
  fallback via `silhouette_intact`.
- `backend/agent/system_prompt.py` — cleanup skill: propose good-cube → review →
  crop outside → brush the small remaining clusters (each brush stroke also
  reviewed).

## Tasks (dependency order; each carries its own test cycle)

- [ ] **R1.1 — monotonic scene revision.** Files: `SceneManager.ts`, viewer/bridge
  types. Impl: `private revision`, bump in `markSplatDirty`, `getSceneRevision()`.
  Test: `SceneManager` unit — revision increases after an edit; stable otherwise.
  Verify: `npm test`, `tsc`.
- [ ] **R1.2 — captures carry pose + revision.** Files: `executors.ts`, `ws.py`,
  `loop.py`. Impl: `capture_frame` returns `{png_base64, pose, revision}`; loop
  records them and annotates the fed frame; a percept older than the current
  revision after an edit is re-requested.
  Test: backend loop test — an edit invalidates a cached percept (re-capture);
  frontend executor test — capture result carries pose+revision.
  Verify: `pytest backend/agent`, `npm test`.
- [ ] **Checkpoint R1:** every image the model sees is tagged with where/when it
  was taken; stale percepts can't drive a decision. Gates green.

- [ ] **R2.1 — coverage feedback.** Files: `framing.ts` (new), `executors.ts`.
  Impl: project core bounds → coverage %; `capture_frame` returns it.
  Test: `framing.ts` unit — a centered core of known size yields expected
  coverage; off-screen → ~0.
  Verify: `npm test`, `tsc`.
- [ ] **R2.2 — `frame_subject` deterministic op (or dolly+coverage).** Files:
  contract (+mirrors+drift), `executors.ts`, `system_prompt.py`. Impl: app moves
  to a target coverage band; model calls intent, not a raw distance.
  Test: contract drift; executor test — frame_subject reaches the coverage band
  on a fake bridge; prompt teaches the signal.
  Verify: `pytest backend/contracts backend/agent`, `npm test`, `tsc`.
- [ ] **Checkpoint R2:** the agent can no longer bury itself — it frames to a
  target coverage using an app-owned op / the coverage signal. Live check: run
  from a framed view, confirm it stops at a sane distance.

- [ ] **R3.1 — default to Analyze, distinct pages.** Files: `App.tsx`/stage UI.
  Impl: default stage `understand`; clarify the two surfaces.
  Test: existing stage-gating tests stay green; a UI/state test for the default.
  Verify: `npm test`, live: cleanup never triggers unless you go to Cleanup.
- [ ] **Checkpoint R3:** you always know which flow you launched; Analyze is
  default and cannot edit.

- [ ] **R4.1 — propose_good_cube (app-computed, previewed).** Files: `executors.ts`,
  contract (+mirrors+drift). Impl: dense-core AABB via `coreBounds`; preview box;
  return counts.
  Test: executor test — proposes a cube around a synthetic core, excludes far
  floaters; contract drift.
  Verify: `npm test`, `pytest backend/contracts`, `tsc`.
- [ ] **R4.2 — review-gated crop-to-core.** Files: `editing.py`, `loop.py`,
  `system_prompt.py`. Impl: on proposal, PAUSE for approval; on OK, crop outside
  the cube (keep inside), subject-loss-guarded; then the brush fine pass.
  Test: backend — crop keeps inside / deletes outside; loop pauses before the
  destructive crop and only commits after resume; subject-loss guard reverts an
  over-crop.
  Verify: `pytest backend/agent backend/analysis`.
- [ ] **Checkpoint R4 (decisive, live):** on the Cleanup page, the agent proposes
  the good-cube, you approve, it deletes the outside floaters (bounds snap back to
  the subject), then brushes the small stuff — every delete reviewed. Gates green.

## Verification gates

- **Mechanical:** `pytest`, `tsc --noEmit`, `eslint`, `npm test` green per task.
- **Decisive/behavioral (live, per checkpoint):** R2 — frames to a sane distance,
  no burying; R4 — proposes/crops/brushes with review, floaters gone, subject
  intact. These are the reliability claims Codex says are unproven; they are
  proven only by the live checks, not the suite.

## Open unknowns / risks

- **How much motion to make deterministic.** R2 offers two routes (a coverage
  signal the model acts on, vs a full `frame_subject` op). Start with the signal;
  escalate to the op only if the model still misjudges — decided at Checkpoint R2.
- **Percept-staleness enforcement strength.** R1 starts by *annotating* pose/rev
  and re-capturing after edits; hard rejection of every stale percept is a
  follow-up if annotation proves insufficient.
- **Core detection on ambiguous scenes** (subject not clearly denser than junk) —
  the review gate is the backstop; flag scenes where the cube is low-confidence.

## Deferred
- Full stateful navigation controller (waypoints, path planning) — only if the
  incremental boundary moves prove insufficient.
- Contract v0.4 groups R2.2 + R4.1 additions in one bump.
