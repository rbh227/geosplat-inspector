# Agent Cleanup Proposals — Design

**Date:** 2026-07-22
**Status:** Approved (brainstorm session, all sections reviewed live)
**Phase:** Cleanup flow — agent proposes and performs edits with operator review
**Contract version:** v0.2 → v0.5 (v0.3/v0.4 already taken by the turn/reframe ops)

## Goal

The agent can clean a scene autonomously, but **every delete is proposed and
reviewed, never silent**. Two cleanup levels (per the confirmed 2026-07-20 flow):

1. **Good cube (coarse):** detector-seeded box around the dense "good" core,
   visually verified by the agent, proposed to the operator, adjusted in
   natural language, then crop-outside on approval.
2. **Brush (fine):** screen-space brush rounds on small floater clusters,
   batch-proposed per round.

Everything the agent does is visible: persistent box preview with wireframe
outline, persistent selection tint, paced strokes.

## Decisions (from brainstorm)

- **Approval flow:** blocking `propose_decision` tool — the agent loop blocks
  on the WS correlated reply until the operator clicks Approve/Reject or types
  adjustment text. One continuous run; verdict returns as the tool result.
- **Cube adjustment:** operator tells the agent in words ("bigger, move
  right"); the agent emits view-relative deltas; deterministic frontend code
  resolves them against the operator's camera. No gizmo.
- **Cube seeding:** detector seed (percentile bounds) + agent visual check
  before proposing. Never model-computed world coordinates.
- **Brush review granularity:** batch per round — one proposal covers all
  clusters brushed from a viewpoint.
- **Scope:** cube pass + brush pass + visualization in one plan (shared
  proposal machinery).
- **Stage gating:** the four new proposal / good-cube tools are Clean-stage
  only (excluded from `UNDERSTAND_TOOLS`, rejected at spec AND dispatch level).
  `crop_sphere` — the other destructive backend crop — is gated the same way:
  Clean-stage only, no silent delete outside the proposal flow.
- **Gate scope (operator decision, 2026-07-22, post final review):** the
  statistical cleaners (`remove_outliers`, `opacity_threshold`,
  `prune_oversized`, `remove_needles`) are ALSO approval-gated, under a third
  proposal kind `bulk_edit` (one approval = one sweep; the proposal summary
  names the tool and parameters). "Every delete is reviewed" holds for the
  whole registry.
- **Approval binding (final review, Fix 2):** a `crop_outside_box` approval
  binds the box the operator actually reviewed — the loop overrides the
  model's `crop_bbox` args with the approved box (narrated honestly) and
  rejects `crop_sphere` against a box approval. `delete_selection` binds the
  reviewed count but not exact IDs (tracked follow-up).

## 1. Contract extension (v0.5)

Registry bump in both mirrors (`backend/contracts/tools.py`,
`frontend/src/contracts.ts`); drift tests updated
(`backend/contracts/tests/test_tools.py`, `frontend/src/agent/contracts.test.ts`).

Four new tools, all `runs_on: "frontend"`, **Clean-stage only** (excluded from
`UNDERSTAND_TOOLS`; dispatch backstop rejects them in Understand):

| Tool | Params | Returns |
|------|--------|---------|
| `get_core_bounds` | — | `{min: [x,y,z], max: [x,y,z], count}` — 5th–95th percentile per-axis box (existing `robustBounds`), backend coords |
| `show_box_preview` | `{min, max}` backend coords | `{ok}` — renders persistent SDF dim + wireframe outline until cleared/replaced/run end |
| `adjust_box_preview` | `{grow?: number, grow_axes?: [gx,gy,gz], shift?: [right,up,forward]}` — view-relative, units of box size | `{ok, min, max}` — new box after frontend maps view→world via operator camera basis |
| `propose_decision` | `{kind: 'crop_outside_box'\|'delete_selection'\|'bulk_edit', summary: string}` | `{verdict: 'approved'\|'rejected'\|'adjusted', feedback?: string}` — blocks until operator responds |

## 2. Proposal machinery

- `propose_decision` rides the existing WS command correlation
  (`ConnectionManager.send_command`, `backend/api/ws.py`). The frontend handler
  **parks** the correlated reply instead of auto-replying, and renders a
  **ProposalCard** in the agent panel: agent summary, Approve / Reject buttons,
  free-text adjustment input. Operator action resolves the reply.
- `send_command` gains a per-command timeout override; proposals wait
  indefinitely.
- **Pause-on-manual-input is suppressed while a proposal is pending** —
  operator camera movement during review is expected inspection, not takeover.
- Stop or WS disconnect while pending → verdict resolves as
  rejected/interrupted; previews and tint cleared; run ends cleanly.
- Run banner shows "awaiting your review" while a proposal is pending.

## 3. Visualization layer

- **Persistent selection tint:** `SceneManager` tints selected splats a
  highlight color by writing into `packedSplats` (originals stored, restored on
  deselect). Applies to ALL selections, manual and agent. O(N) per change —
  same cost class as existing selection loops; acceptable at demo scale.
- **Persistent box preview:** existing `showSelectionPreview('box', ...)`
  without the executor's 500 ms auto-clear, PLUS a crisp `LineSegments`
  wireframe box parented to the splat mesh (so it inherits the Y-flip and
  appears in captures).
- No new brush-stroke visual: paced strokes + live tint are the visibility.

## 3b. Percept & scale awareness

- Brush/lasso already take viewport-normalized `[u,v]` — screenshots ARE the
  pointing coordinate system; zoom needs no compensation for pointing.
- **The box is the ruler.** While a box preview is active, `capture_frame`'s
  percept gains a deterministic `box_screen` block: projected on-screen rect
  (`center: [u,v]`, `width`, `height` as fraction of frame) + flags for
  offscreen/behind-camera edges. Observation units == actuation units
  (box-widths), so the model never does projection math.
- Existing `coverage` stays as the too-far/too-close guard.
- Deliberately NOT added: pixels-per-unit / FOV scale figures for the model to
  multiply — deterministic code owns all conversions.

## 4. Good-cube pass

1. `get_core_bounds` → seed; `show_box_preview`.
2. Agent visual check: 1–2 captures (button-nav as needed); if subject clearly
   clipped, `adjust_box_preview` (grow) before proposing.
3. `propose_decision(kind='crop_outside_box', summary=...)`.
4. Verdicts: **approved** → backend `crop_bbox` (keep inside, delete outside)
   + snapshot + count reported; **adjusted** → agent translates feedback to
   `adjust_box_preview` deltas, re-proposes (loop); **rejected** → clear
   preview, ask operator what they'd rather do.
5. Degenerate detector box (empty/absurd) → reported in tool result; agent
   falls back to brush-only cleanup.

## 5. Brush pass

Rounds from the operator-anchored viewpoint:

1. Capture → identify small floater clusters visually.
2. Brush clusters (`select_by_brush`, existing pacing); tint builds live.
3. `propose_decision(kind='delete_selection', summary="N clusters, ~M splats —
   the tinted ones")`.
4. **Approved** → `delete_selection`; **adjusted** → deselect via brush
   remove-mode or clear + re-brush, re-propose; **rejected** → clear
   selection, move on.
5. New vantage via button-nav; repeat. Stop when a round finds nothing, when
   metrics look clean, or at a hard round cap. `silhouette_intact` guard runs
   after every commit.

## 6. Trigger & UX

- No new page — the Clean stage is the surface. New **"Clean this scene"**
  skill pill (in `backend/agent/system_prompt.py` SKILLS) runs the full
  routine: cube → approve → crop → brush rounds.
- Free-text chat on Clean can invoke the same tools for one-off asks.

## 7. History & undo

No changes: `crop_bbox` and `delete_selection` already land in the unified
backend `History` (+ local mirror). One approved edit = one undo step.
Rejected proposals commit nothing.

## 8. Error handling & testing

**Errors:** stop/disconnect during pending proposal → interrupted verdict,
previews/tint cleared; backend edit failure after approval → existing
authoritative-reload + toast; degenerate detector → brush-only fallback.

**Backend tests:** stub-channel verdict round-trips (approved/adjusted/
rejected), proposal timeout exemption, stage gating (all four new tools
rejected in Understand at spec AND dispatch level), loop continuation after
`adjusted`.

**Frontend tests:** contract drift guards (v0.5), `adjust_box_preview`
view→world mapping math, `box_screen` projection math, ProposalCard resolves
the parked WS reply, tint apply/restore round-trip.

**Prompt CI proxies:** cleanup-routine system-prompt assertions in the style
of `backend/agent/tests/test_analyst_prompt.py`.
