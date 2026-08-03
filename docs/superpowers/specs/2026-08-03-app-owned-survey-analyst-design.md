# App-Owned Survey Analyst — Design

**Date:** 2026-08-03
**Status:** approved, ready for planning
**Supersedes:** the capture-choreography portions of
`2026-07-28-analyst-scene-understanding-design.md` (its goals stand; its
model-driven navigation approach is replaced).

---

## 1. Problem

Two live-model post-mortems (2026-07-30 on Qwen3-VL-8B, 2026-08-03 on
Qwen3-VL-32B) show the same shape of failure: **the model never fails at
seeing — it fails at navigating.** Both models described captured frames
accurately. Both runs died in the perceive→navigate→capture choreography:

- 8B: dollied away from the operator's pose, answered from one bad final
  frame, parroted a stale answer from history.
- 32B: percept metadata (`in_view: false`, `coverage: 1`) lied because the
  operator's camera sat inside the scene core's bounding sphere;
  `reframe` returned to that same pose, so the model looped reframe ~20
  times and answered "the scene is not visible" — after having captured
  and correctly described a good frame mid-run.

Root cause is structural: the model is responsible for framing the scene
(the thing VLMs are bad at, guided by percept heuristics that lie from
inside-the-core viewpoints) before it is allowed to describe pixels (the
thing VLMs are good at). Additionally, frames are attached to exactly one
model call (`loop.py` clears `_pending_frames`; the OpenAI adapter attaches
images to the last user turn only), so the model can never look back at a
view it already captured.

## 2. Goal and success criterion

When the operator asks "what does this scene show?" in the Understand
stage, the agent reliably answers with an accurate description of the
scene contents — and follow-up questions ("how many buildings?") are
answered against the same views. **Demo-ready:** the answer must be
grounded in what the frames show, never "I cannot see the scene" when the
scene is renderable.

The operator's workflow stays: upload → clean in the editor → ask the
analyst. The analyst always sees the edited (compacted) scene — this was
verified, not changed, by this design.

## 3. Decisions (settled with the operator, 2026-08-03)

1. **Deliverable:** Q&A on the scene; the anchor question is "what does
   this scene show."
2. **Navigation:** the app flies a deterministic survey; the model does no
   navigation for analysis.
3. **Follow-ups:** answered from the stored survey frames only. If a
   question needs a closer look, the agent says so; the operator reframes
   and re-asks.
4. **Display:** clean markdown chat answer. No new UI component.

## 4. Design

### 4.1 Flow

An Understand-stage run:

1. **Survey phase (app-owned, before the model's first turn).** The loop
   dispatches a new frontend tool `survey_capture` over the existing
   dispatcher/WS channel. The frontend executor:
   - captures the operator's current view (frame 1 — "the angle I just
     put in" keeps meaning something),
   - computes the live scene core (`getSceneCore()`, recomputed from the
     compacted buffer),
   - flies framed poses via existing `poseForBox` / `computeFraming`
     math: top-down + two obliques (~35° elevation, opposite corners),
   - animates visibly between poses (~600 ms tweens) and captures each,
   - returns 4 labeled frames + the scene revision they were taken at.
2. **One model call.** All frames, with text labels ("View 1: operator's
   view", "View 2: top-down", …), plus the operator's question. The
   Understand tool surface shrinks to `answer` + `narrate` — no
   navigation tools are offered, so every navigation failure mode is
   unreachable.
3. **Answer** renders as a normal markdown chat message.
4. **Follow-ups:** survey frames are stored per scene conversation and
   re-attached on **every** subsequent model call. If the scene revision
   has changed (operator edited between questions), the frames are stale
   and the next run re-surveys automatically.

### 4.2 Component changes

| Where | Change |
|---|---|
| `frontend/src/agent/executors.ts`, `camera.ts` | New `survey_capture` executor; survey-pose helper reusing framing math |
| `backend/contracts/tools.py`, `frontend/src/contracts.ts` | Additive `survey_capture` registry entry + contract version bump, both mirrors, drift tests |
| `backend/agent/loop.py` | Understand runs: dispatch survey before the first `generate`; attach stored frames on every call; remove the frameless-answer nudge and navigation-oriented guards from the Understand path |
| `backend/agent/system_prompt.py` | `UNDERSTAND_TOOLS = {answer, narrate}`; rewritten analyst prompt: "you are given N labeled views of one scene — say what the imagery is first, tiered counts, artifacts are not damage, answer from pixels" |
| `backend/api/real_engine.py` | Persist survey frames + revision per scene conversation; invalidate on edit |
| Chat panel | No change |

Token budget: 4 frames × ~800 tokens ≈ 3.2K per call — comfortable inside
the 24K serving context alongside history.

### 4.3 Error handling

- No scene loaded / null core → survey fails cleanly → the agent answers
  "no scene is loaded"; it never hallucinates a description.
- Partial capture failure → proceed with ≥1 frame and note the missing
  views in the answer; zero frames → surfaced as a run error, not an
  answer.
- Renderer/WS gone → existing dispatcher error path (same "provider
  error" surfacing as today).

### 4.4 Out of scope

The Clean-stage loop keeps its full tool surface and percepts. No report
card UI, no model-requested extra looks, no 3D marker annotations. All
addable later without rework.

## 5. Testing

- **Pose math** unit tests (`framing.test.ts` style): survey poses frame
  the core; top-down sits above the center; obliques at expected
  elevation.
- **Executor** tests following `capture.test.ts` / `camera.test.ts`
  patterns.
- **Loop** headless tests with the scripted provider + mock channel
  (`test_analyst_prompt.py` / `test_proposals.py` patterns): survey
  dispatched before the first generate; frames attached to every call;
  follow-up runs reuse frames; revision bump triggers re-survey; failure
  paths (no scene, partial frames, zero frames).
- **Contract drift** tests on both sides
  (`backend/contracts/tests/test_tools.py`,
  `frontend/src/agent/contracts.test.ts`).
