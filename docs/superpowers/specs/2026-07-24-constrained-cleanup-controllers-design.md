# Constrained Cleanup + Analyst Controllers — Design

**Date:** 2026-07-24
**Status:** approved, ready for planning
**Supersedes (partially):** the free-form `cleanup_scene` skill path from
`docs/superpowers/specs/2026-07-22-agent-cleanup-proposals-design.md` (v0.5).
The proposal/approval machinery from v0.5 is kept and reused; only the
*sequencing* moves out of the model's hands.

---

## 1. Problem

The agent cannot reliably clean a scene end to end. Four structural causes,
each verified in the code:

1. **`get_core_bounds` returns one connected component.**
   `computeTightCoreBox` (`src/viewer/framing.ts:150-225`) voxel-bins the solid
   splats on a 32³ grid, then flood-fills the dense component containing the
   single **peak** cell. In a settlement scene, building clusters separated by a
   street or a void are separate components, so the "core box" covers one
   subsection rather than the whole subject.

2. **The Clean agent gets the entire editing surface.** `AgentLoop` builds the
   full 40-tool v0.2 registry for the clean stage (`backend/agent/loop.py:115-116`).
   A model that deviates has 39 other things to deviate into: it can abandon the
   crop, propose a mismatched operation, start brushing, or narrate in circles.

3. **The post-revert feedback actively steers toward other cleanup tools.**
   `backend/agent/loop.py:564-568` feeds back a literal hint naming
   `remove_outliers` / `opacity_threshold` / `prune_oversized`. A reverted crop
   therefore *launches* a bulk-sweep excursion — the origin of the observed
   1.16-million-Gaussian selection.

4. **Clean and Understand share one conversation.** `backend/api/real_engine.py:225-233`
   reads and writes the same `scene.chat_history` regardless of stage. The two
   stages have different tool permissions but identical memory; they are not
   separate agents.

**The interaction is what actually breaks the demo.** A *correct* good-cube crop
on a scene that is >90% junk deletes most of the scene. `silhouette_intact`
(`backend/agent/verify.py:70-106`) reverts any edit that drops the solid core
below 50%, and it runs on **operator-approved** crops too. So: cause (1) yields a
box covering one cluster → the approved crop drops the other clusters' solid core
below the threshold → the guard reverts it → cause (3) redirects the model into
bulk sweeps → cause (2) supplies the tools to do damage with.

## 2. Goals

The demo needs exactly two beats:

1. **Crop.** The agent finds the good part of the splat, crops to it, and deletes
   the Gaussians outside — with operator approval.
2. **Read.** The agent describes the scene in plain language: "aerial imagery of
   what looks like a neighborhood, ~8 buildings, debris on the ground."

Non-goals for this pass: brush rounds in the cleanup path, statistical sweeps in
the cleanup path, multi-round autonomous cleanup, tuned counting accuracy beyond
an approximate figure.

## 3. Constraints

- **Model is local Qwen-VL (via the Bina vLLM server, OpenAI-compatible provider).**
  Instruction-following is the weak point. Every model decision must be a single
  forced tool call with an enumerated or tightly-typed argument — never a
  sequence the model composes itself.
- The proposal/approval UI (`ProposalCard`), WS event plumbing, tool dispatcher,
  history/undo, and stable-ID machinery all work and are reused unchanged.
- Contracts are mirrored: any tool added needs `backend/contracts/tools.py` and
  `frontend/src/contracts.ts` updated together (drift tests guard this).

## 4. Architecture

Two deterministic controllers in `backend/agent/`. Each owns its sequence in
Python and calls the model only where semantics are required.

```
CropController            (Clean stage — "cleanup_scene" pill)
  geometry → 3 candidate boxes → captures
  → [MODEL: pick one]  → [MODEL: nudge? ≤1 round]
  → propose_decision → operator approves → crop_bbox → verify → STOP

AnalystController         (Understand stage — the describe_scene / count_objects pills)
  fixed 4-view orbit sweep (no model navigation)
  → [MODEL: one structured read] → answer → STOP
```

At each model call the model is offered **one tool**, forced
(`tool_choice=required`, already in place for the OpenAI-compatible provider).
There is no alternative tool to wander into, so tool-mixing, narration loops, and
unauthorized edits are structurally impossible rather than prompt-discouraged.

**The free-form `AgentLoop` is not removed.** It remains the handler for ad-hoc
chat ("fly over there and look at that roof"), so the agentic surface survives
for the demo. It is simply no longer what runs when the cleanup or describe pill
is clicked.

**Why not just improve the prompt:** `backend/agent/system_prompt.py` already
carries `"Start IMMEDIATELY — do not navigate or improve coverage first"` and a
numbered 7-step recipe, and the model still deviates. A numbered list in a prompt
is a suggestion; a Python loop is not.

## 5. Component: `CropController`

`backend/agent/crop_controller.py` — a state machine over the existing
`ToolDispatcher` and `FrontendChannel`.

| # | Actor | Action |
|---|-------|--------|
| 1 | code | `get_crop_candidates` → 3 boxes + per-box stats |
| 2 | code | per candidate: `show_box_preview` → fixed framing → `capture_frame` |
| 3 | **model** | one call, 3 labeled images + stats text, one tool: `choose_box(label, reason)` |
| 4 | **model** | ≤1 call: `adjust_box(action, reason)`; `accept` ends the step |
| 5 | code | `propose_decision(kind='crop_outside_box')` → `ProposalCard` |
| 6 | code | on approval: `crop_bbox` with the approved box |
| 7 | code | `capture_frame` + before/after counts → narrate result → **STOP** |

**Model call 3 — `choose_box`**

```
choose_box(label: "A" | "B" | "C", reason: string)
```
Images are captioned with their label and stats. If the model returns an invalid
label, retry once with the constraint restated; on a second failure, default to
candidate A (settlement) and note the fallback in the run report.

**Model call 4 — `adjust_box`**

```
adjust_box(action: "accept" | "grow" | "shrink" | "shift_up" | "shift_down"
                 | "shift_left" | "shift_right" | "shift_forward" | "shift_back",
           reason: string)
```
Mapped onto the existing `adjust_box_preview` semantics (the box is the ruler —
one unit = a fixed fraction of the box extent). Hard cap: **one** adjustment
round, then the controller proceeds to the proposal regardless.

**Operator verdicts** (existing `ProposalCard` semantics):
- *approved* → step 6.
- *adjusted* → operator feedback text is applied as one more `adjust_box` model
  call, then re-proposed. Cap: 2 adjust cycles, then the run reports and stops.
- *rejected* → the chosen candidate is struck from the list and the controller
  returns to step 3 with the remainder. With no candidates left, the run stops
  and reports that no acceptable box was found. **It never reroutes to another
  cleanup method.**

**Guard change.** `silhouette_intact` gains an approved-operation path: for an
operator-approved crop, only a *catastrophic* backstop applies — revert if the
crop leaves under 1% of splats or zero solid core. Operator approval is the
subject-protection mechanism for that operation; the 50%-core rule is what
silently ate the correct crops.

**Revert-hint change.** The hint at `backend/agent/loop.py:564-568` stops naming
alternative cleanup tools. It states what was reverted and why, and nothing more.
(This is a fix to the free-form loop, which still exists for chat.)

## 6. Component: candidate geometry

`src/viewer/framing.ts` — new `computeCoreCandidates(points)`. It reuses the
existing voxel binning of `computeTightCoreBox` but labels **all** connected
dense components rather than only the peak's. `computeTightCoreBox` itself is
left untouched (other callers depend on it).

Returns three candidates, each with a box and stats:

- **A — settlement:** union of every dense component whose point count is ≥10% of
  the peak component's. This is the direct fix for cause (1).
- **B — core:** the current single-peak box. Correct when there really is one
  dense object and the rest is junk.
- **C — wide:** the robust 2–98 percentile box over solid splats. Deliberately
  generous; it is the escape hatch when density clustering is wrong, and its
  presence makes the model's choice a real discrimination rather than a rubber
  stamp.

Stats per candidate (shown to the model as text beside its image): splats inside,
solid splats inside, fraction of the scene's solid core retained, number of
components merged.

**Runaway-union guard.** A single stray dense cluster far from the subject could
clear the 10% bar and balloon candidate A. Drop any component whose inclusion more
than doubles the union's volume while adding under 10% more solid splats. The
model's visual check is the second line of defence.

Input sampling is unchanged: `SceneManager.getCoreBoundsBox` already strides to a
100k sample and pre-filters to solid splats (`opacity >= 0.3`,
`SceneManager.ts:965-983`); the new `getCropCandidates()` reuses that path.

## 7. Component: `AnalystController`

`backend/agent/analyst_controller.py`. Both Understand-stage skill pills
(`describe_scene` and `count_objects`) route here — `report_scene` returns both
the description and the counts, so one controller serves both.

**Per-stage memory.** `scene.chat_history` becomes a dict keyed by stage
(`real_engine.py:225-233`). Clean and Understand stop sharing a transcript, so
the analyst never "remembers" a crop debate.

**Deterministic capture sweep.** The model does not navigate. The controller
frames the scene with the existing `computeFraming` / `tweenCamera` path and
captures 4 views at 90° orbit increments.

**One model call:**

```
report_scene(
  scene_type:   string,                                  # "aerial imagery of a residential neighborhood"
  observations: string[],                                # 2-4 short factual sentences
  counts:       {label: string, count: int,
                 confidence: "approximate" | "confident"}[]
)
```

The controller renders this into the chat answer. The `confidence` field lets an
approximate count read as honest rather than wrong. That is the entire analyst —
no navigation, no re-capture loop, no free-form tool selection.

## 8. Files touched

| File | Change |
|---|---|
| `src/viewer/framing.ts` | + `computeCoreCandidates()` (`computeTightCoreBox` unchanged) |
| `src/viewer/SceneManager.ts` | + `getCropCandidates()` beside `getCoreBoundsBox()` |
| `frontend/src/agent/executors.ts` | + `get_crop_candidates` handler |
| `backend/contracts/tools.py` | v0.6: `get_crop_candidates`, `choose_box`, `adjust_box`, `report_scene` |
| `frontend/src/contracts.ts` | mirror of the above |
| `backend/agent/crop_controller.py` | **new** |
| `backend/agent/analyst_controller.py` | **new** |
| `backend/agent/verify.py` | `silhouette_intact` approved-operation path |
| `backend/agent/loop.py` | revert hint no longer names alternative cleanup tools |
| `backend/api/real_engine.py` | per-stage chat history; route the two pills to controllers |
| `backend/agent/system_prompt.py` | `cleanup_scene` / describe recipes now name the controllers |

Reused unchanged: proposal machinery, `ProposalCard`, WS events, `ToolDispatcher`,
`History`/undo, stable IDs.

## 9. Error handling

| Situation | Behaviour |
|---|---|
| No scene loaded | `get_crop_candidates` returns `ok:false`; controller reports and stops |
| Geometry returns <2 distinct candidates | Proceed with what exists; a single candidate still goes through the proposal |
| Model returns an invalid enum | Retry once with the constraint restated; then fall back (A for `choose_box`, `accept` for `adjust_box`) and note it |
| Model call fails / times out | Report the failure in chat and stop — never fall through to an unreviewed edit |
| All candidates rejected | Stop, report that no acceptable box was found |
| Approved crop leaves <1% of splats or no solid core | Revert, report the catastrophic backstop fired |
| Operator hits Stop mid-run | Existing stop semantics: end cleanly at the next boundary, clear previews |

## 10. Testing

**Headless (CI):**
- Scripted-provider round trip for `CropController` (pattern from
  `backend/agent/tests/test_proposals.py`): asserts the exact tool sequence, that
  no edit fires without a matching approval, that an approved crop is **not**
  reverted by the core guard, and that a rejected candidate re-proposes rather
  than switching cleanup method.
- Scripted-provider test for `AnalystController`: 4 captures, one `report_scene`,
  no edit tools reachable.
- Geometry unit test: synthetic two-cluster scene where the single-peak box
  provably excludes cluster two and the union box includes both; plus a
  runaway-union case that the volume guard rejects.
- Contract drift tests (existing) cover the v0.6 tool additions.
- Per-stage history test: a Clean run's transcript is absent from a subsequent
  Understand run.

**Manual (cannot be skipped):** a live run with Qwen against a real
post-disaster `.ply` (candidates in `public/demos/`), confirming it picks the
settlement candidate. If it does not, the tuning surface is one enum and three
images — far smaller than a 40-tool prompt.

## 11. Pre-implementation check

Before writing the controllers, compute `computeCoreCandidates` offline against
the actual demo `.ply` and confirm the union candidate recovers the whole
settlement. The whole design hinges on that geometry being right; it is a short
check that de-risks everything downstream.

Also: the backend was not running at the time of writing (nothing on :8000).
Start it and reproduce the current failure before changing code, so the fix is
measured against an observed baseline.
