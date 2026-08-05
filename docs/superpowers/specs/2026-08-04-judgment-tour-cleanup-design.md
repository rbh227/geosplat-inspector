# Judgment-tour cleanup agent — design

**Date:** 2026-08-04
**Status:** approved direction (Spin 1 of 2026-08-04 brainstorm); supersedes the unbuilt controller halves of `2026-07-24-constrained-cleanup-controllers-design.md`
**Goal:** make the Clean-stage cleanup agent reliable and demo-able **with the local vLLM model** on a real drone building splat, while keeping genuine model agency: the model helps find the noise and decides what dies.

## 1. Problem

Live runs with the local model fail in both directions (deletes nothing, or deletes the building), break the tool protocol, and produce aimless narration. The current loop asks a weak VLM to do the three things it is worst at:

- invent continuous 3D geometry (box bounds, brush coordinates, sweep parameters),
- sequence a 41-tool protocol under stall/grounding machinery,
- exercise restraint over destructive tools.

Prior specs already concluded: *every model decision must be a single forced tool call* (2026-07-24 §3) and *the model never decides what to destroy* (2026-07-25 §1). The Understand stage got this treatment (app-owned survey) and became demo-able; Clean never did.

## 2. Design principle

**App proposes structure, model supplies judgment.** The cleanup run becomes a Python controller (a loop, not a prompt). The model is called only at forced-choice points, each with a fresh, minimal context: one image, one instruction, exactly one tool schema, no shared transcript. The model's decisions are *discrete* — grid cells and verdicts — never coordinates, never tool selection, never sequencing.

Three trust layers share this architecture; only the first is in scope here:
1. **Judgment tour** (this spec) — local model.
2. *Director macros* (future) — a stronger model sequences the same phase controllers.
3. *Language instructions* (future) — natural-language goals mapped onto candidates; the ProposalCard adjust box already gives a cheap version.

## 3. The run — six phases, one controller

`cleanup_scene` (chat pill or typed request routed to it) starts a `CleanupController` run instead of the freeform loop. Freeform Clean chat for other prompts is untouched.

### Phase 1 — Crop (existing, unchanged)
App computes the density core, shows the box preview (SDF dim + wireframe), raises the crop ProposalCard. Operator approves, adjusts via the crop gizmo, or rejects (reject skips to Phase 2 — cropping is optional, not fatal). Approval binds the exact box; `crop_bbox` executes with silhouette verify. Zero model calls.

### Phase 2 — Survey & mark ("where is the noise?")
- App flies the survey orbit (reuse the analyst's `survey_capture` executor) — **max 6 frames**, framed on post-crop bounds.
- Each frame is sent to the model with a **4×4 labeled grid (A1–D4) burned into the image** (frontend draws overlay at capture time).
- One forced call per frame: `mark_noise(cells: string[], note?: string)` — empty list = frame looks clean. Invalid cell names are dropped; a garbage/timeout reply marks the frame `unsure` and the run continues.

### Phase 3 — Lock-in (marks → objects)
- **Statistical candidates:** voxel-grid connected components over alive splats outside the core (cell size ~2–4% of scene radius, min-splat floor); per-cluster stats: splat count, mean opacity, extent, distance from core, needle fraction.
- **Mark resolution:** each marked cell + its camera pose defines a frustum wedge. Splats in the wedge (excluding the core region) vote for their cluster; cells marked in ≥2 frames triangulate. A mark that hits no statistical cluster spawns a candidate from the wedge's densest off-core component; a mark that resolves nowhere is recorded as `unresolved` (shown in the summary, costs nothing).
- Output: **deduped, labeled candidate list** (A, B, C…), ordered by splat count, **capped at 12** for the tour. Provenance tracked per candidate (`stats`, `model`, `both`) — it's demo narration gold ("the model spotted one the statistics missed").

### Phase 4 — Judgment tour ("is it junk?")
For each candidate: app flies the camera to frame the cluster's bbox (app-driven animateTo — allowed; the teleport ban constrains the *model*, not the controller), tints the cluster's splats, captures, and asks one forced call:
`judge_candidate(verdict: "junk" | "structure" | "look_closer", reason: string ≤ 120 chars)`
- `look_closer`: **once per candidate** — one more framed view from a different elevation, then the model must commit; a second `look_closer` coerces to `structure` (safe default).
- Timeout/garbage → verdict `unsure` (treated as `structure`/keep, flagged on the card).

### Phase 5 — One batch proposal
A single ProposalCard of a new payload shape: rows of `{label, splat_count, verdict, reason, provenance}` plus totals ("delete 7 clusters — 48,112 splats; keeping 2 judged structure, 1 unsure").
- **Approve** binds the union of splat IDs of junk-verdict clusters (ID snapshot, void-on-change — same invariant as today's selection binding). Deletions execute **per cluster, in visible sequence** (tint flash → delete), silhouette-verified after each; a verify failure undoes that cluster only and flags it.
- **Adjust** takes free-text feedback; the *controller* (not the tour model) applies simple label-targeted flips ("keep B", "delete C") — parse with a forced model call listing the labels as enums; unparseable feedback re-shows the card with a note.
- **Reject** ends the destructive phase; run proceeds to summary.

### Phase 6 — Scripted summary
Controller emits the wrap-up: clusters removed/kept/skipped, splat totals before/after, any verify-undos, unresolved marks. Narration throughout the run is **event-scripted** (found N candidates, visiting B, …); the model's prose appears only as its per-candidate `reason` strings.

## 4. Model-call contract

Every model interaction in the run is:
- fresh context: 1 short instruction (< 400 chars) + 1 image + exactly 1 tool schema, `tool_choice="required"`;
- no chat history, no scene transcript, no other tools;
- bounded retries (1), then a safe default (`unsure`);
- provider-agnostic via the existing `ModelProvider` protocol — a new narrow entry point on the runner side (`generate_forced_choice`), not a provider change.

The run therefore **cannot stall and cannot select a wrong tool**; worst case is conservative (junk survives), never destructive (building dies only if the operator approves a bad card).

## 5. Code changes

| Area | Change |
|---|---|
| `backend/agent/cleanup_controller.py` (new) | Phase state machine; owns survey, lock-in, tour, proposal, execution, summary. Reuses `WSChannel`, proposal banking/binding, `verify.silhouette_intact`, snapshot/undo. |
| `backend/analysis/clusters.py` (new) | Voxel connected components, cluster stats, frustum wedge resolution. Pure numpy/scipy, unit-testable headlessly. |
| `backend/contracts/tools.py` + `frontend/src/contracts.ts` | **v0.3 bump**: `mark_noise`, `judge_candidate` (controller-scope tools, not exposed to the freeform registry); batch-proposal payload (`clusters` rows) on the proposal WS command. Drift-guard tests extended on both sides. |
| `backend/api/routes.py` / `real_engine.py` | Route `cleanup_scene` pill (and an explicit `mode=cleanup` flag) to `CleanupController`; one-run-per-scene and pause/stop semantics unchanged. |
| `frontend/src/agent/` | Grid overlay at capture (canvas draw before encode); `frame_cluster` (fly-to-bbox) and `tint_ids` executors (recompositions of existing camera/selection code). |
| `src/ui/ProposalCard.tsx` | Batch layout: cluster rows + totals; approve/adjust/reject unchanged semantically. |
| Untouched | Proposal gate invariants, operator crop gizmo, Understand stage, freeform Clean loop for non-cleanup prompts, `closed_loops.py` (superseded; delete in implementation). |

## 6. Budgets & failure containment

- Caps: 6 survey frames, 12 toured candidates, 1 `look_closer` each, 1 retry per model call → hard ceiling ≈ 26 model calls, each tiny; typical run ≈ 12–15.
- Any single model failure degrades one datum to `unsure`; the run always reaches the card and the summary.
- Stop works at every phase boundary and between tour stops; manual camera input during the tour pauses before the next stop (existing pause semantics). Camera moves during card review still don't pause.
- All destructive work remains behind the two approvals; ID-snapshot binding voids on selection drift exactly as today.

## 7. Testing

- **Controller round-trip** with a scripted provider (pattern of `backend/agent/tests/test_proposals.py`): marks → lock-in → verdicts → batch card → bound execution, including unsure/timeout paths and adjust-flip parsing.
- **Cluster + frustum unit tests** on `examples/messy.ply` (seeded floaters/outliers/needles must appear as candidates) and synthetic layouts (triangulation from 2 frames, mark-with-no-cluster).
- **WS/card tests** (pattern of `backend/api/tests/test_proposal_ws.py`) for the batch payload and void-on-change.
- **Prompt-shape CI** like `test_analyst_prompt.py`: forced-choice instructions stay under budget, enum values stable.
- Live-model tuning (grid size, tint color, framing margin) is expected manual iteration — noted as such, not CI.

## 8. Acceptance

- On a real building splat with the local model: `cleanup_scene` → crop card → survey/marks → tour with visible camera stops and tints → one batch card → approved deletions execute in sequence → scripted summary. No stalls, no protocol errors, building intact unless the operator approves otherwise.
- On `messy.ply` headless with the scripted provider: all seeded junk classes reach the card as candidates.
- Worst-case with a fully broken model (all calls time out): run still completes with an app-statistics-only candidate list and marks everything `unsure` — degraded, never destructive.
