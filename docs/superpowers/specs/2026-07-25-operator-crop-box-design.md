# Operator-Edited Crop Box + Tool Descriptions — Design

**Date:** 2026-07-25
**Status:** approved, ready for planning
**Supersedes:** §5 (`CropController`) and §6 (candidate geometry) of
`docs/superpowers/specs/2026-07-24-constrained-cleanup-controllers-design.md`.
The analyst half of that spec (§7) and its guard/serving fixes (already landed)
stand unchanged.

---

## 1. Problem

Every crop failure observed so far has the same shape: the *model* made the
semantic call — "which part of this is the real scene" — and got it wrong. The
last run "cropped the main part of the scene" away.

The 2026-07-24 spec tried to constrain that judgment: deterministic geometry
proposes three candidate boxes, the model picks one from captures and may nudge
it once. That is still the model deciding, just with a smaller menu.

The operator knows the answer instantly and is never wrong about it. Give them
direct control of the box and the entire failure class disappears — not
mitigated, removed.

**Consequence worth stating plainly: the crop needs zero model calls.** The
model's role in the Clean stage drops to nothing, which also makes the crop
immune to rate limits, provider outages, and instruction-following quality.
The model does what it is good at — the Understand-stage read of the cleaned
scene — and nothing else.

## 2. Goals

1. A **crop-box tool** in the editor rail: place a 3D box, move it, resize it,
   orbit freely to check it, then delete everything outside it. Works with no
   agent involved.
2. The **agent can seed** that box (from `get_core_bounds`) and, when the
   operator confirms, crop to the operator's final box rather than the seed.
3. **Tool descriptions** in the rail, so what each tool does is discoverable.

Non-goals: rectangle-drag/frustum seeding (explicitly dropped — the gizmo does
the same job without the depth ambiguity); model-chosen candidate boxes; brush
rounds in the cleanup path.

## 3. The crop-box tool

A new entry in the left rail (`src/ui/EditorToolbar.tsx`), alongside
brush/lasso/polygon/sphere/box.

**Placement.** Activating the tool shows a box seeded from
`computeTightCoreBox` — the same "good cube" the agent uses today — so the
operator starts from a reasonable guess rather than nothing. If no scene is
loaded the tool is disabled.

**Manipulation.** Three.js `TransformControls` attached to the box:
- translate mode: drag the body to move
- scale mode: drag a handle to resize
- keyboard toggle between modes; `Escape` cancels the tool

`TransformControls` emits `dragging-changed`; orbit is disabled for the duration
of a handle drag and restored after. This is the one sanctioned exception to the
"mouse always orbits" rule from the nav fix — it is scoped to an active drag on
a handle, so there is no mode to get trapped in.

**Feedback.** The existing proposal-box visuals are reused: wireframe plus the
SDF dim of everything outside it, so "what will be deleted" is visible the whole
time. A live count of splats inside the box updates as the box moves.

**Commit.** A "Crop to box" button deletes everything outside. It goes through
the same `/edit` path as every other destructive edit, so it lands in the shared
history and Undo works normally.

**Live-count performance.** An exact count is O(N) per frame — unusable while
dragging a 2M-splat scene. The live readout is computed from the existing
strided 100k sample (`SceneManager.getCoreBoundsBox` already builds one) and
labelled as approximate; the exact count is computed once on commit. This
mirrors how `getCoreBoundsBox` already reports `count`.

## 4. Agent handoff

Today `propose_decision(kind='crop_outside_box')` binds **the box the agent
previewed**, and `loop.py` runs the crop on that box "regardless of what you
pass". That binding is what makes an approval mean something — but it also means
operator edits are discarded.

The approval payload gains the operator's final box:

```
proposal_decision {
  verdict: 'approved' | 'rejected' | 'adjusted',
  feedback?: string,
  box?: { min: [x,y,z], max: [x,y,z] }   // NEW — operator's edited box
}
```

When `box` is present on an `approved` verdict, the backend rebinds the approval
to that box and the crop runs on it. The safety property is preserved: the crop
still runs on exactly one reviewed box, and that box is now the one the operator
actually looked at. When `box` is absent, behaviour is unchanged.

This is a contract change: **v0.6**, mirrored in `backend/contracts/tools.py`
and `frontend/src/contracts.ts`, with the existing drift tests
(`backend/contracts/tests/test_tools.py`, `frontend/src/agent/contracts.test.ts`)
as the guard.

**Coordinate space.** The gizmo works in render space; the viewer applies
`mesh.rotation.x = Math.PI`. The box travels back to the backend in backend
coordinates, using the same conversion `show_box_preview` already performs —
flipping corners can swap per-axis min/max, so the box is rebuilt from
componentwise min/max rather than transformed corners (the bug
`select_by_box` already guards against in `executors.ts`).

## 5. Tool descriptions

The rail currently relies on the native `title` attribute
(`EditorToolbar.tsx:39-43`): slow to appear, dismissed on click, and it cannot
show a shortcut hint legibly.

**Design:** a single `?` toggle button pinned at the bottom of the rail. Off (the
default) the rail looks exactly as it does now, with improved hover tooltips —
custom, instant, showing name + one-line description + shortcut. On, the rail
expands to show each tool's name and one-line description inline, and stays
that way until toggled off.

One `?` rather than a per-tool info button: the rail's buttons are 7x7 icons and
a second button on each would double the rail's density for something the
operator needs once. The toggle is discoverable, reversible, and gives the
descriptions real room.

Descriptions live in the existing `TOOLS` array as a `description` field beside
`title`, so there is exactly one place to edit them.

| tool | description |
|---|---|
| brush | Paint over splats to select them. `[` / `]` resize. |
| lasso | Draw a freehand outline; everything inside is selected. |
| polygon | Click points to outline a region; double-click to close. |
| sphere | Drag out a sphere; splats inside are selected. |
| box | Drag out a box; splats inside are selected. |
| crop box | Place a box and delete everything outside it. |

Erase mode and the action buttons (delete / keep / invert / clear / undo / redo)
get the same treatment.

## 6. Files touched

| File | Change |
|---|---|
| `src/viewer/CropBoxGizmo.ts` | **new** — TransformControls wrapper, orbit suspend/restore, box state |
| `src/viewer/SceneManager.ts` | mount/unmount the gizmo; live sampled count; expose the current box |
| `src/ui/EditorToolbar.tsx` | crop-box tool entry; `description` field; `?` toggle; custom tooltips |
| `src/App.tsx` | wire the tool + "Crop to box" through the existing `/edit` path |
| `src/ui/ProposalCard.tsx` | send the operator's edited box with an `approved` verdict |
| `frontend/src/contracts.ts` | v0.6 `proposal_decision.box` |
| `backend/contracts/tools.py` | v0.6 mirror |
| `backend/agent/loop.py` | rebind an approved crop to the operator's box when supplied |
| `backend/agent/system_prompt.py` | cleanup recipe: seed the box, hand to the operator, stop |

Reused unchanged: proposal box visuals, SDF dim preview, history/undo, stable
IDs, the `/edit` route.

## 7. Error handling

| Situation | Behaviour |
|---|---|
| Tool activated with no scene | Tool disabled in the rail |
| Box dragged fully outside the scene | "Crop to box" disabled; count reads 0 |
| Box contains everything | Crop is a no-op; say so rather than making an empty history entry |
| Operator approves with an edited box while the agent moved on | Approval is latched per proposal (existing behaviour); a stale box is rejected with a message |
| `box` present on a `rejected` verdict | Ignored |
| Gizmo drag interrupted (tool switch, Escape) | Orbit restored; box left where it was |

## 8. Testing

- `CropBoxGizmo` unit tests: orbit is disabled on `dragging-changed` true and
  restored on false, including when the drag is interrupted by a tool switch.
- Box round-trip test: render-space box → backend coords → back, with the
  `rotation.x = PI` flip, asserting per-axis min/max never invert.
- Sampled-vs-exact count test: the live count is within tolerance of the exact
  count on a synthetic scene, and the committed crop uses the exact set.
- Contract drift tests (existing) cover the v0.6 `box` field.
- Backend test: an `approved` verdict carrying a box crops to THAT box, not the
  previewed one; without a box, the previewed box is still used.
- `EditorToolbar` test: every entry in `TOOLS` has a non-empty description; the
  `?` toggle shows and hides them.

## 9. The agent's role (resolved 2026-07-25)

The agent stays in every beat except the one that destroys data. Operator
decision: keep the agent in the flow; author's call on where exactly.

| beat | actor | can it fail destructively? |
|---|---|---|
| Inspect: `get_metrics`, `capture_frame`, narrate what it sees | agent | no |
| Seed the box: `get_core_bounds` → `show_box_preview` | agent | no — the operator edits it next |
| Adjust the box and confirm | **operator** | this is the only irreversible decision |
| Crop to the confirmed box | agent (bound to the operator's box, §4) | no — the box is the operator's |
| Verify: re-measure, recapture, report before/after | agent | no |
| Read the cleaned scene (Understand stage) | agent | no |

The model therefore inspects, proposes, executes, verifies and explains — it
simply never decides what to destroy. That is a stronger agentic story than
"the model chose a box", not a weaker one: it is the difference between an agent
that could be pointed at real data and one that could not. It also means no beat
in the demo can fail destructively, whatever the model does.

Practical consequence: §4's handoff is **kept**. A bad seed costs the operator a
drag; it cannot cost them the scene. The Clean stage still makes no model call
that gates an edit.
