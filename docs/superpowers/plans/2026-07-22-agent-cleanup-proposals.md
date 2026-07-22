# Agent Cleanup Proposals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The agent proposes every delete before committing it — a detector-seeded "good cube" crop and batched brush rounds — with a blocking approve/reject/adjust round-trip and full visual preview (persistent box wireframe, selection tint).

**Architecture:** Four new frontend tools (v0.5 contract additions): `get_core_bounds`, `show_box_preview`, `adjust_box_preview`, `propose_decision`. The first three ride the existing `selection_tool` WS command; `propose_decision` gets a new `proposal` WS command whose correlated reply is *parked* by the frontend until the operator acts on a ProposalCard. The backend loop hard-gates `crop_bbox`/`crop_sphere`/`delete_selection`/`keep_selection` behind an approved proposal (consume-on-use). All view-relative math (box adjustment, screen projection) is deterministic frontend code — the model never converts between view and world space.

**Tech Stack:** Python 3.12 + FastAPI + pytest (backend); TypeScript + React + Three.js + SparkJS + vitest (frontend).

**Spec:** `docs/superpowers/specs/2026-07-22-agent-cleanup-proposals-design.md`

## Global Constraints

- Contract sync rule: any change to `backend/contracts/tools.py` MUST be mirrored in `frontend/src/contracts.ts`; the drift guards are `backend/contracts/tests/test_tools.py` and `frontend/src/agent/contracts.test.ts`.
- Version label for all new tools/comments: **v0.5** (v0.3 = `turn`, v0.4 = `reframe` are already taken).
- Coordinates: all tool params/returns are BACKEND coords (mesh-local, pre-Y-flip). PackedSplats centers are already backend coords (see `getSelectionSummary` comment, `src/viewer/SceneManager.ts:916-921`). Render space = backend space with y,z negated (`toRenderSpace` in `frontend/src/agent/camera.ts` — an involution).
- Backend test command: `source .venv-api/bin/activate && pytest backend/ -x -q` (Python 3.12 venv). Frontend: `npm test` (vitest), `npx tsc --noEmit`, `npm run lint`.
- No new dependencies, backend or frontend.
- The Understand stage must NEVER gain any of the four new tools (allow-list `UNDERSTAND_TOOLS` is unchanged; verify in tests).
- Commit after every task with a conventional-commit message.

---

### Task 1: Contract v0.5 — four new tools in both mirrors

**Files:**
- Modify: `backend/contracts/tools.py` (docstring + registry, after the `turn` entry at ~line 200)
- Modify: `frontend/src/contracts.ts` (`FRONTEND_TOOLS` array ~line 86, `WSCommandType` ~line 138)
- Modify: `backend/contracts/tests/test_tools.py` (registry counts/names — read the file first to see its assertions)
- Modify: `frontend/src/agent/contracts.test.ts` (same)
- Modify: `docs/superpowers/specs/2026-07-22-agent-cleanup-proposals-design.md` (retitle "v0.2 → v0.3" to "→ v0.5"; add `crop_sphere` to the gated list in §"Decisions")

**Interfaces:**
- Produces: `TOOL_BY_NAME["get_core_bounds" | "show_box_preview" | "adjust_box_preview" | "propose_decision"]`, all `runs_on="frontend"`. TS `FrontendToolName` includes the four names. `WSCommandType` includes `"proposal"` AND `"rotation_input"` (the latter is an existing drift fix — it's in `ws.py COMMAND_TYPES` and `ws-client.ts` but missing from the TS union).

- [ ] **Step 1: Write the failing drift tests.** Read both test files; extend their name-set/count assertions to include the four new tools (and, TS-side, the two command types). Run `pytest backend/contracts/tests/ -q` and `npm test -- contracts` — both must FAIL on the missing names.

- [ ] **Step 2: Add the registry entries** at the end of the frontend section of `TOOL_REGISTRY` (after `turn`), and update the module docstring with a v0.5 line citing the spec:

```python
    # ── frontend (proposal / good-cube) — v0.5 ──
    # The proposal surface (docs/superpowers/specs/2026-07-22-agent-cleanup-
    # proposals-design.md): preview a region, then BLOCK on the operator's
    # verdict. Clean-stage only; coordinates are backend space.
    ToolEntry("get_core_bounds", "frontend", {
        "type": "object", "properties": {},
    }, "{min, max, count} — robust (5th-95th pct) core box"),
    ToolEntry("show_box_preview", "frontend", {
        "type": "object",
        "properties": {
            "min": _vec3("Box min corner, backend coords"),
            "max": _vec3("Box max corner, backend coords"),
        },
        "required": ["min", "max"],
    }, "{ok, min, max}"),
    ToolEntry("adjust_box_preview", "frontend", {
        "type": "object",
        "properties": {
            "grow": {"type": "number",
                     "description": "Uniform scale about the box center (1.2 = 20% bigger)"},
            "grow_axes": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3,
                          "description": "Per-view-axis scale [right, up, forward]"},
            "shift": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3,
                      "description": "Move by [right, up, forward] in units of the box's own size, "
                                     "relative to the OPERATOR'S current view"},
        },
    }, "{ok, min, max}"),
    ToolEntry("propose_decision", "frontend", {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["crop_outside_box", "delete_selection"]},
            "summary": {"type": "string",
                        "description": "One or two sentences the operator reads before deciding"},
        },
        "required": ["kind", "summary"],
    }, "{verdict: approved|rejected|adjusted, feedback?}"),
```

- [ ] **Step 3: Mirror in `frontend/src/contracts.ts`:** append to `FRONTEND_TOOLS`:

```ts
  // v0.5 — proposal / good-cube (agent-cleanup-proposals spec)
  "get_core_bounds", "show_box_preview", "adjust_box_preview", "propose_decision",
```

and extend `WSCommandType`:

```ts
  // v0.2: rotate-pad input (was missing from this union — drift fix)
  | "rotation_input"
  // v0.5: blocking proposal — reply is parked until the operator decides
  | "proposal";
```

- [ ] **Step 4: Run both drift tests — PASS.** Also `npx tsc --noEmit`.
- [ ] **Step 5: Fix the spec version label** (v0.3 → v0.5; add `crop_sphere` to gated tools).
- [ ] **Step 6: Commit** `feat(contracts): v0.5 — proposal/good-cube tools (get_core_bounds, show/adjust box preview, propose_decision)`

---

### Task 2: WS plumbing — `proposal` command, indefinite timeout, dispatch routing

**Files:**
- Modify: `backend/api/ws.py` (`COMMAND_TYPES` line 28; `ConnectionManager.send_command` line 123; `WSChannel.send_command` line 201)
- Modify: `backend/agent/dispatch.py` (`_FRONTEND_CMD_TYPE` line 62)
- Test: `backend/api/tests/` (find the existing ws test module and extend it; create `test_proposal_ws.py` there if none fits)

**Interfaces:**
- Consumes: Task 1's registry names.
- Produces: `propose_decision` dispatches as `{"type": "proposal", "tool": "propose_decision", "args": {...}}` and awaits its reply with NO timeout; the other three ride `"selection_tool"`. `ConnectionManager.send_command` accepts `timeout: float | None`.

- [ ] **Step 1: Write failing tests:** (a) `WSChannel.send_command({"type": "proposal", ...})` passes `timeout=None` to the manager (assert via a recording fake manager); (b) any other type still passes `DEFAULT_COMMAND_TIMEOUT`; (c) `ToolDispatcher` maps the four new tools to the right command types (instantiate with mocks from `backend/agent/mocks.py`, capture the cmd via a recording channel). Run — FAIL.

- [ ] **Step 2: Implement.** `ws.py`:
  - `COMMAND_TYPES` += `"proposal"`.
  - `ConnectionManager.send_command` signature → `timeout: float | None = DEFAULT_COMMAND_TIMEOUT` (`asyncio.wait_for(fut, timeout=None)` already waits forever — no other change).
  - `WSChannel.send_command`: `timeout = None if ctype == "proposal" else DEFAULT_COMMAND_TIMEOUT`, pass through.

  `dispatch.py` `_FRONTEND_CMD_TYPE` additions:

```python
    # v0.5 — proposal / good-cube
    "get_core_bounds": "selection_tool",
    "show_box_preview": "selection_tool",
    "adjust_box_preview": "selection_tool",
    "propose_decision": "proposal",
```

- [ ] **Step 3: Run tests — PASS.** Then full `pytest backend/ -x -q`.
- [ ] **Step 4: Commit** `feat(api): proposal WS command with indefinite reply timeout`

---

### Task 3: Loop approval gate — no delete without an approved proposal

**Files:**
- Modify: `backend/agent/loop.py`
- Test: `backend/agent/tests/test_proposals.py` (new — model scaffolding on `backend/agent/tests/test_pause_resume.py`, which shows the scripted-provider + stub-channel pattern)

**Interfaces:**
- Consumes: `propose_decision` tool result envelope `{"ok": True, "result": {"verdict": ..., "feedback": ...}}` from dispatch.
- Produces: module-level `_APPROVAL_GATED: dict[str, str]` in `loop.py`; per-run `self._approvals: dict[str, int]`. Gated tools rejected in the clean stage without a banked approval; one approval = one edit.

- [ ] **Step 1: Write failing tests** (scripted provider issues the calls; stub channel returns canned `propose_decision` results):
  - `crop_bbox` with no prior approval → tool result is a rejection mentioning `propose_decision`, executor NOT called.
  - `propose_decision(kind='crop_outside_box')` returning `verdict:'approved'` → subsequent `crop_bbox` dispatches; a SECOND `crop_bbox` without a new proposal → rejected (consumed).
  - `verdict:'adjusted'` (with feedback) → no approval banked; feedback text present in the fed-back tool result.
  - `verdict:'rejected'` → no approval banked.
  - `delete_selection` gated behind `kind='delete_selection'` the same way; `keep_selection` and `crop_sphere` share their respective kinds.
  - Understand stage: the four v0.5 tools are rejected by the existing stage backstop (they're not in `UNDERSTAND_TOOLS`).

- [ ] **Step 2: Implement.** In `loop.py` add at module level:

```python
# Destructive spatial ops locked behind an operator-approved proposal (v0.5).
# One approval unlocks exactly one edit of the matching kind.
_APPROVAL_GATED: dict[str, str] = {
    "crop_bbox": "crop_outside_box",
    "crop_sphere": "crop_outside_box",
    "delete_selection": "delete_selection",
    "keep_selection": "delete_selection",
}
```

  In `run()` reset: `self._approvals = {}` (also init in `__init__`). In `_handle_call`, AFTER the stage backstop and BEFORE the `answer`/vision/destructive branches:

```python
        if self.stage == "clean" and call.name in _APPROVAL_GATED:
            kind = _APPROVAL_GATED[call.name]
            if self._approvals.get(kind, 0) <= 0:
                rejection = {
                    "ok": False,
                    "error": f"{call.name} is locked: get an approved "
                             f"propose_decision(kind='{kind}') first — preview what "
                             "you intend to remove, then propose it to the operator",
                }
                await self._emit(ev_tool_result(call.name, rejection, step))
                self._feed_back(call.name, rejection)
                return False
            self._approvals[kind] -= 1
```

  In the generic dispatch branch (after `result = await self.dispatcher.dispatch(call)`):

```python
        if call.name == "propose_decision" and result.get("ok"):
            payload = result.get("result")
            if isinstance(payload, dict) and payload.get("verdict") == "approved":
                kind = str(call.args.get("kind", ""))
                self._approvals[kind] = self._approvals.get(kind, 0) + 1
```

- [ ] **Step 3: Run — PASS**, then full backend suite (existing loop tests that call gated tools may need a stubbed approval or a config bypass — prefer updating those tests to script a proposal first; do NOT weaken the gate).
- [ ] **Step 4: Commit** `feat(agent): approval gate — destructive spatial ops require an approved proposal`

---

### Task 4: Core box detector — `computeCoreBox` + `getCoreBoundsBox`

**Files:**
- Modify: `src/viewer/framing.ts` (export a box variant of the percentile bounds)
- Modify: `src/viewer/SceneManager.ts` (new public method; reuse the point-sampling used by `coreBounds()` at line 1474-1505 — read it first)
- Modify: `frontend/src/agent/types.ts` (`RendererBridge` + the bridge implementations that must satisfy it: `src/backend/bridge.ts` and the `makeRendererBridge` in `src/App.tsx` — grep for it)
- Test: `src/viewer/framing.test.ts`

**Interfaces:**
- Produces: `computeCoreBox(points: readonly Vec3[]): { min: [number,number,number]; max: [number,number,number] } | null` in framing.ts; `SceneManager.getCoreBoundsBox(): { min: number[]; max: number[]; count: number } | null` (backend coords — sample `packedSplats` centers directly, which are mesh-local/backend space; do NOT use world-transformed points); `RendererBridge.getCoreBoundsBox()` with the same signature.

- [ ] **Step 1: Failing test** in `framing.test.ts`:

```ts
it('computeCoreBox excludes far floaters', () => {
  const pts = []
  for (let i = 0; i < 100; i++) pts.push({ x: i % 10, y: (i / 10) | 0, z: 0 })
  pts.push({ x: 5000, y: 5000, z: 5000 })  // one far floater
  const box = computeCoreBox(pts)!
  expect(box.max[0]).toBeLessThan(20)
  expect(box.max[1]).toBeLessThan(20)
})
```

- [ ] **Step 2: Implement** in framing.ts (next to `computeCoreBounds`):

```ts
export interface CoreBox { min: [number, number, number]; max: [number, number, number] }

/** Robust percentile box (5th-95th per axis) — min/max form for crop/preview. */
export function computeCoreBox(points: readonly Vec3[]): CoreBox | null {
  const b = robustBounds(points)
  if (!b) return null
  const [cx, cy, cz] = b.center
  return {
    min: [cx - b.ex / 2, cy - b.ey / 2, cz - b.ez / 2],
    max: [cx + b.ex / 2, cy + b.ey / 2, cz + b.ez / 2],
  }
}
```

  In SceneManager, add `getCoreBoundsBox()`: sample `packedSplats` centers (same iteration pattern as `getSelectionSummary`, `SceneManager.ts:930-936`), call `computeCoreBox`, then count centers inside the box in a second pass. Return `null` when no mesh. Add the method to `RendererBridge` (types.ts) and both bridge implementations.

- [ ] **Step 3: Run `npm test -- framing` — PASS; `npx tsc --noEmit` clean.**
- [ ] **Step 4: Commit** `feat(viewer): computeCoreBox + getCoreBoundsBox — percentile core box in backend coords`

---

### Task 5: Persistent proposal box — SDF dim + wireframe outline

**Files:**
- Modify: `src/viewer/SceneManager.ts` (new fields + 3 methods, modeled on `showSelectionPreview` at lines 974-1008 but with SEPARATE state so the flash preview and the proposal box can coexist)
- Modify: `frontend/src/agent/types.ts` + `src/backend/bridge.ts` + `makeRendererBridge` in `src/App.tsx`

**Interfaces:**
- Produces: `SceneManager.showProposalBox(min: number[], max: number[]): void`, `clearProposalBox(): void`, `getProposalBox(): { min: number[]; max: number[] } | null` — all backend coords; same three on `RendererBridge`.

- [ ] **Step 1: Implement** (no pure-logic seam worth a unit test here; verification is Task 13's manual QA + tsc):

```ts
  /* ---- Persistent proposal box (v0.5, agent-cleanup-proposals) ---- */
  private proposalEdit: SplatEdit | null = null
  private proposalSdf: SplatEditSdf | null = null
  private proposalWire: THREE.LineSegments | null = null
  private proposalBoxState: { min: number[]; max: number[] } | null = null

  /** Persistent SDF dim + crisp wireframe, parented to the splat mesh so both
   *  live in backend coords and appear in captures. Stays until cleared. */
  showProposalBox(min: number[], max: number[]): void {
    const mesh = this.splatMesh
    if (!mesh) return
    this.clearProposalBox()
    const center = [(min[0]+max[0])/2, (min[1]+max[1])/2, (min[2]+max[2])/2]
    const half = [(max[0]-min[0])/2, (max[1]-min[1])/2, (max[2]-min[2])/2]
    const edit = new SplatEdit({ rgbaBlendMode: SplatEditRgbaBlendMode.MULTIPLY })
    const sdf = new SplatEditSdf({
      type: SplatEditSdfType.BOX,
      opacity: 0.25,
      color: new THREE.Color(1.4, 1.4, 0.6),
    })
    edit.addSdf(sdf); edit.add(sdf); mesh.add(edit)
    sdf.position.set(center[0], center[1], center[2])
    sdf.radius = 0
    sdf.scale.set(Math.max(half[0], 1e-4), Math.max(half[1], 1e-4), Math.max(half[2], 1e-4))
    const geom = new THREE.BoxGeometry(max[0]-min[0], max[1]-min[1], max[2]-min[2])
    const wire = new THREE.LineSegments(
      new THREE.EdgesGeometry(geom),
      new THREE.LineBasicMaterial({ color: 0xffcc44 }),
    )
    geom.dispose()
    wire.position.set(center[0], center[1], center[2])
    mesh.add(wire)
    this.proposalEdit = edit; this.proposalSdf = sdf; this.proposalWire = wire
    this.proposalBoxState = { min: [...min], max: [...max] }
  }

  clearProposalBox(): void {
    if (this.splatMesh) {
      if (this.proposalEdit) this.splatMesh.remove(this.proposalEdit)
      if (this.proposalWire) this.splatMesh.remove(this.proposalWire)
    }
    this.proposalWire?.geometry.dispose()
    this.proposalEdit = null; this.proposalSdf = null; this.proposalWire = null
    this.proposalBoxState = null
  }

  getProposalBox(): { min: number[]; max: number[] } | null {
    return this.proposalBoxState
  }
```

  Also call `clearProposalBox()` wherever the scene is replaced (find where `clearSelectionPreview` or selection state is reset on load — mirror it). Add the three methods to `RendererBridge` and both bridge implementations.

- [ ] **Step 2: `npx tsc --noEmit` + `npm run lint` clean; `npm test` still green.**
- [ ] **Step 3: Commit** `feat(viewer): persistent proposal box — SDF dim + wireframe outline`

---

### Task 6: Selection tint — see what's about to be deleted

**Files:**
- Modify: `src/viewer/SceneManager.ts`
- Test: whatever seam is testable headless; at minimum the bookkeeping (store/restore map) via a small pure helper if you extract one

**Interfaces:**
- Produces: selected splats render visibly tinted (warm highlight) whenever the selection is non-empty, manual or agent; colors restore exactly on deselect/clear. No bridge change (hooks into `emitSelectionChange`).

**Approach (verify against the actual SparkJS API before coding):** read how `deleteByIds` / `keepOnlyIds` mutate `packedSplats` in SceneManager — that is the established per-splat data-write pattern in this codebase. Implement `applySelectionTint()`: iterate packed splats (pattern of `getSelectionSummary`), for each selected id store the original color in a `Map<number, [r,g,b]>` (first time only) and write the highlight color (e.g. lerp 60% toward `[1.0, 0.75, 0.2]`); mark the packed buffer dirty the same way the delete path does. `restoreSelectionTint()` writes originals back and clears the map. Call both from `emitSelectionChange()` (restore-then-apply on every change; restore-only when empty). If SparkJS exposes no per-splat color write and the delete path works by full rebuild, tint via the same rebuild path — correctness over elegance at demo scale.

**If the API genuinely cannot express per-splat recolor without breaking rendering, STOP and report back to the orchestrator rather than shipping a fake.**

- [ ] **Step 1: Read `deleteByIds` and the SparkJS PackedSplats API; pick the write mechanism.**
- [ ] **Step 2: Implement apply/restore + wire into `emitSelectionChange()`; ensure edits (delete/keep) drop stored originals for removed ids (restore BEFORE any delete commits — call restore at the top of `deleteSelection`/`keepSelection`).**
- [ ] **Step 3: Add whatever unit test the seam allows (e.g. original-color map bookkeeping); run `npm test`, `npx tsc --noEmit`.**
- [ ] **Step 4: Commit** `feat(viewer): persistent selection tint — selected splats highlight until deselected`

---

### Task 7: View-relative box adjustment math (pure)

**Files:**
- Create: `frontend/src/agent/proposalBox.ts`
- Test: `frontend/src/agent/proposalBox.test.ts`

**Interfaces:**
- Produces:

```ts
export interface Box { min: [number, number, number]; max: [number, number, number] }
export interface ViewBasis {  // unit vectors in BACKEND coords
  right: [number, number, number]
  up: [number, number, number]
  forward: [number, number, number]
}
export interface AdjustOpts { grow?: number; grow_axes?: [number, number, number]; shift?: [number, number, number] }
export function adjustBox(box: Box, basis: ViewBasis, opts: AdjustOpts): Box
export function viewBasisFromCamera(cam: THREE.PerspectiveCamera): ViewBasis  // extract render-space basis, negate y,z → backend coords
```

**Semantics (deterministic, keeps the box axis-aligned):** each view direction snaps to its dominant world axis (`argmax |component|`, sign of that component). `shift[i]` translates the box along that world axis by `shift[i] * extent[axis] * sign`. `grow` scales all extents uniformly about the center. `grow_axes[i]` scales the extent of the world axis dominant for view axis i. Degenerate case (two view axes snapping to one world axis) — last write wins; document in a comment.

- [ ] **Step 1: Failing tests:** axis-aligned camera (right=+x, up=+y, forward=-z): `shift:[1,0,0]` moves the box +x by exactly its x-extent; `shift:[0,0,1]` moves it -z by its z-extent; `grow:2` doubles every extent about a fixed center; `grow_axes:[2,1,1]` doubles only the x-extent; a camera yawed 40° still snaps right→x. Run — FAIL.
- [ ] **Step 2: Implement both functions.** `viewBasisFromCamera`: `cam.updateMatrixWorld()`, columns of `cam.matrixWorld` give right/up, forward = negated third column; then negate y,z components of each to convert render→backend coords, normalize.
- [ ] **Step 3: Run — PASS.**
- [ ] **Step 4: Commit** `feat(agent): pure view-relative box adjustment (dominant-axis snapping)`

---### Task 8: Executors — get_core_bounds / show_box_preview / adjust_box_preview

**Files:**
- Modify: `frontend/src/agent/executors.ts` (`runSelectionTool`, before the volume-tool branch)
- Test: extend the executor coverage in `frontend/src/agent/ws-client.test.ts` or the executors' own test file if one exists (check first)

**Interfaces:**
- Consumes: Task 4 `bridge.getCoreBoundsBox()`, Task 5 `bridge.showProposalBox/clearProposalBox/getProposalBox`, Task 7 `adjustBox`/`viewBasisFromCamera`.
- Produces: three new cases inside `runSelectionTool` (they arrive as `selection_tool` commands with `tool` set to the new names).

- [ ] **Step 1: Failing tests** with a stub bridge: `get_core_bounds` returns `{ok:true, min, max, count}`; `show_box_preview` calls `showProposalBox` and echoes the box; `adjust_box_preview` without an active box returns `{ok:false, error:...}`; with one active, returns the adjusted box and re-shows it.
- [ ] **Step 2: Implement** in `runSelectionTool`:

```ts
    // v0.5 — proposal / good-cube surface
    if (tool === 'get_core_bounds') {
      const box = this.bridge.getCoreBoundsBox()
      return box ? { ok: true, ...box } : { ok: false, error: 'no scene loaded' }
    }
    if (tool === 'show_box_preview') {
      const mn = args.min as number[], mx = args.max as number[]
      if (!Array.isArray(mn) || !Array.isArray(mx) || mn.length !== 3 || mx.length !== 3) {
        return { ok: false, error: 'min/max must be [x,y,z]' }
      }
      this.bridge.showProposalBox(mn, mx)
      await sleep(350)  // paced so the operator sees it land (SC2)
      return { ok: true, min: mn, max: mx }
    }
    if (tool === 'adjust_box_preview') {
      const cur = this.bridge.getProposalBox()
      if (!cur) return { ok: false, error: 'no box preview active — call show_box_preview first' }
      const basis = viewBasisFromCamera(this.bridge.getCamera())
      const next = adjustBox(
        { min: cur.min as Box['min'], max: cur.max as Box['max'] },
        basis,
        args as AdjustOpts,
      )
      this.bridge.showProposalBox(next.min, next.max)
      await sleep(350)
      return { ok: true, min: next.min, max: next.max }
    }
```

  (import `adjustBox`, `viewBasisFromCamera`, and the types from `./proposalBox.ts`.)

- [ ] **Step 3: Run tests — PASS; tsc clean.**
- [ ] **Step 4: Commit** `feat(agent): executors for core-bounds seed and box preview/adjust`

---

### Task 9: `box_screen` percept — the box as on-screen ruler

**Files:**
- Modify: `frontend/src/agent/proposalBox.ts` (add the pure projection helper)
- Modify: `frontend/src/agent/executors.ts` (`capture_frame`, lines ~288-303)
- Modify: `frontend/src/agent/types.ts` (`PerceptTag`)
- Test: `frontend/src/agent/proposalBox.test.ts`

**Interfaces:**
- Produces:

```ts
export interface BoxScreen {
  center: [number, number]   // viewport-normalized [u,v]
  width: number              // fraction of frame width
  height: number
  offscreen_edges: Array<'left' | 'right' | 'top' | 'bottom'>
  behind_camera: boolean
}
export function projectBoxToScreen(
  boxBackend: Box,
  viewProj: number[],        // 4x4 column-major, render space (same as executors.projectCenters)
  w: number, h: number,
): BoxScreen | null
```

  `PerceptTag` gains `box_screen?: BoxScreen`.

**Semantics:** convert the 8 backend-coord corners to render space (negate y,z), project each through viewProj; if all 8 are behind the camera return `{...behind_camera: true}` with zeroed rect; otherwise take the 2D bounding rect of the in-front corners, normalize by w/h, clamp to [0,1] for `center`, and report `offscreen_edges` for every frame edge the unclamped rect crosses.

- [ ] **Step 1: Failing tests:** camera at +z looking at origin, unit box at origin → center ≈ [0.5, 0.5], no offscreen edges; box shifted far left → `offscreen_edges` contains `'left'`; camera looking away → `behind_camera: true`.
- [ ] **Step 2: Implement**; in `capture_frame`, after building `percept`, add:

```ts
    const pbox = this.bridge.getProposalBox()
    if (pbox) {
      const proj = this.projectCenters()  // reuses the same camera matrices
      if (proj) {
        const cam = this.bridge.getCamera()
        const viewProj = composeMatrices(
          Array.from(cam.projectionMatrix.elements),
          Array.from(cam.matrixWorldInverse.elements),
        )
        const bs = projectBoxToScreen({ min: pbox.min, max: pbox.max } as Box, viewProj, proj.w, proj.h)
        if (bs) (percept as PerceptTag).box_screen = bs
      }
    }
```

  (Adapt to the actual local variable names in `capture_frame` — the percept object is built inline at lines 294-302; extract it to a local first.)

- [ ] **Step 3: Run — PASS.**
- [ ] **Step 4: Commit** `feat(agent): box_screen percept — projected proposal box in every capture`

---

### Task 10: Frontend proposal handling — parked reply + PanelBus signal

**Files:**
- Modify: `frontend/src/agent/ws-client.ts` (COMMAND_TYPES set line 24; new case in `handleCommand`; `handleTrace` complete-cleanup)
- Modify: `frontend/src/agent/panels.ts` (PanelBus)
- Test: `frontend/src/agent/ws-client.test.ts`

**Interfaces:**
- Consumes: `WSCommandType 'proposal'` (Task 1).
- Produces:

```ts
export interface ProposalState {
  kind: string
  summary: string
  resolve: (verdict: 'approved' | 'rejected' | 'adjusted', feedback?: string) => void
}
// PanelBus:
readonly proposal = new Signal<ProposalState | null>(null)
setProposal(p: ProposalState): void
clearProposal(): void
```

**Behavior:** the `proposal` command does NOT auto-reply. It parks a resolver that (a) sends `{type:'tool_result', id, payload:{ok:true, verdict, feedback?}}` and (b) clears the signal. On a `complete` trace event, any still-pending proposal is cleared WITHOUT sending (the run is already over) and `bridge.clearProposalBox()` + `bridge.clearSelection()` are called defensively.

- [ ] **Step 1: Failing tests** (follow the existing ws-client.test.ts fake-transport pattern): proposal command → no reply sent, `panels.proposal.get()` populated with kind/summary; calling `resolve('adjusted', 'bigger')` → exactly one `tool_result` reply with `{verdict:'adjusted', feedback:'bigger'}` and signal cleared; `complete` trace with a pending proposal → signal cleared, no reply sent, `clearProposalBox` called.
- [ ] **Step 2: Implement:** add `'proposal'` to the client's COMMAND_TYPES set; new case:

```ts
        case 'proposal': {
          const { args } = p as unknown as { args: { kind: string; summary: string } }
          const id = cmd.id
          this.panels.setProposal({
            kind: args?.kind ?? '',
            summary: args?.summary ?? '',
            resolve: (verdict, feedback) => {
              this.transport.send({
                type: 'tool_result', id,
                payload: { ok: true, verdict, ...(feedback ? { feedback } : {}) },
              } as WSResponse)
              this.panels.clearProposal()
            },
          })
          break  // reply parked — resolved by the operator via the ProposalCard
        }
```

  In `handleTrace`, on `'complete'`: if `panels.proposal.get()` non-null → `panels.clearProposal()`; also `this.bridge.clearProposalBox()` and `this.bridge.clearSelection()` (wrap in try/catch — bridge may lack a scene).
- [ ] **Step 3: Run — PASS.**
- [ ] **Step 4: Commit** `feat(agent): parked proposal replies + PanelBus proposal signal`

---

### Task 11: ProposalCard UI + App wiring (pause suppression, stop, banner)

**Files:**
- Create: `src/ui/ProposalCard.tsx`
- Modify: `src/App.tsx` (subscribe to the proposal signal; `handleManualInput` line 222; `handleStopAgent` line 234; render the card in the right panel next to/inside `ChatPanel`; run banner)
- Modify: `src/ui/ChatPanel.tsx` only if the card must nest inside it (prefer rendering the card as a sibling above the chat input — read ChatPanel's layout first)

**Interfaces:**
- Consumes: `ProposalState` from `panels.ts` (Task 10).
- Produces: `ProposalCard({ proposal, onDecide })` where `onDecide(verdict, feedback?)` calls `proposal.resolve`.

**Behavior requirements:**
1. Card shows the agent's `summary`, a kind-specific title ("Crop to this box?" for `crop_outside_box`, "Delete the highlighted splats?" for `delete_selection`), an **Approve** button, a **Reject** button, and a free-text input with a **Send adjustment** action (Enter submits; resolves as `'adjusted'` with the text).
2. While a proposal is pending: `handleManualInput` does NOT send `agent_pause` (camera inspection is expected review behavior) — track via a `proposalPendingRef` updated from the signal subscription.
3. `handleStopAgent` first resolves any pending proposal as `('rejected', 'operator stopped the run')`, then sends `user_interrupt` as today.
4. While pending, the running-state banner shows "Awaiting your review" (find where the thinking/paused banner renders — follow the `agentPaused` state's render path).
5. Match the existing UI idiom: look at `ActionCard.tsx` / `CleanupDrawer.tsx` for styling conventions before writing JSX.

- [ ] **Step 1: Wire the signal into App state** (`const [proposal, setProposal] = useState<ProposalState | null>(null)` + effect subscribing to `panelsRef.current?.proposal` — note the PanelBus is created per-scene in the effect at App.tsx:480-499, so subscribe there).
- [ ] **Step 2: Build ProposalCard + render it; implement behaviors 2-4.**
- [ ] **Step 3: Verify:** `npx tsc --noEmit`, `npm run lint`, `npm test` all clean. Manual check deferred to Task 13.
- [ ] **Step 4: Commit** `feat(ui): ProposalCard — approve/reject/adjust with pause suppression`

---

### Task 12: Prompt, skills, and prompt-CI tests

**Files:**
- Modify: `backend/agent/system_prompt.py` (`_DESCRIPTIONS`, `_CLEAN_PROMPT`, `SKILLS`)
- Test: `backend/agent/tests/test_cleanup_prompt.py` (new — model on `backend/agent/tests/test_analyst_prompt.py`)

**Interfaces:**
- Consumes: v0.5 tool names (Task 1); the gate semantics (Task 3).
- Produces: clean-stage prompt teaches the proposal flow; new `cleanup_scene` skill pill; updated `clean_floaters` / `trim_background` recipes.

- [ ] **Step 1: Failing tests:** `build_tool_specs('understand')` contains none of the four v0.5 tools; `build_tool_specs('clean')` contains all four; `system_prompt_for('clean')` mentions `propose_decision`, `get_core_bounds`, and "Awaiting"-free (i.e. the flow text below); `system_prompt_for('understand')` does NOT mention `propose_decision`; `skills_for('clean')` includes `cleanup_scene`, `skills_for('understand')` does not.
- [ ] **Step 2: Implement.** `_DESCRIPTIONS` additions:

```python
    # v0.5 — proposal / good-cube
    "get_core_bounds": "Get the detector's robust core box (5th-95th pct bounds) — the floater-excluding seed for the good cube.",
    "show_box_preview": "Render a persistent highlighted box (dim + wireframe) the operator and your captures both see.",
    "adjust_box_preview": "Grow/shift the previewed box RELATIVE TO THE OPERATOR'S VIEW (units = the box's own size). No coordinates.",
    "propose_decision": "Ask the operator to approve a pending edit. BLOCKS until they answer: approved / rejected / adjusted (+feedback).",
```

  `_CLEAN_PROMPT` — add after the "PREFER the selection grammar" bullet:

```
- PROPOSE BEFORE DELETING: crop_bbox / crop_sphere / delete_selection /
  keep_selection are LOCKED until the operator approves a matching
  propose_decision (kind 'crop_outside_box' unlocks the crops, kind
  'delete_selection' unlocks the selection deletes). One approval = one edit.
  If the verdict is 'adjusted', apply the feedback (adjust_box_preview for the
  cube; re-brush for selections) and propose again. If 'rejected', clear the
  preview/selection and ask what they'd rather do.
- GOOD-CUBE ROUTINE (coarse cleanup): get_core_bounds -> show_box_preview ->
  capture_frame to CHECK the subject sits fully inside (the percept's
  box_screen tells you where the box lands on screen; the box is your ruler —
  "the roof sticks out half a box-width" means shift/grow by 0.5) ->
  adjust_box_preview if clipped -> propose_decision(kind='crop_outside_box')
  -> on approval, crop_bbox with the approved box. Cropping to the good core
  is the POINT of this pass — the "never crop TO a problem region" rule means
  never crop to a FLOATER cluster, not never crop.
- BRUSH ROUNDS (fine cleanup): from the current view, brush every floater
  cluster you can see (they tint as you select), then ONE
  propose_decision(kind='delete_selection') for the batch. After the verdict,
  move to a new vantage with the buttons and repeat. Stop when a round finds
  nothing new.
```

  `SKILLS` — update `clean_floaters`'s recipe to end `-> propose_decision(kind='delete_selection') -> delete_selection once approved -> verify`, update `trim_background`'s recipe to route through the good-cube routine, and add:

```python
    {
        "name": "cleanup_scene",
        "stage": "clean",
        "description": "Full reviewed cleanup: good-cube crop, then brush rounds — every delete needs your approval.",
        "recipe": "get_core_bounds -> show_box_preview -> capture_frame to verify the subject is inside -> adjust_box_preview if needed -> propose_decision(kind='crop_outside_box') -> crop_bbox on approval. Then brush rounds: select_by_brush the visible floater clusters -> propose_decision(kind='delete_selection') -> delete_selection on approval -> new vantage, repeat until a round finds nothing.",
    },
```

- [ ] **Step 3: Run new tests + full backend suite — PASS.**
- [ ] **Step 4: Commit** `feat(agent): proposal-flow prompt rules, cleanup_scene skill, v0.5 descriptions`

---

### Task 13: Integration verification + docs

**Files:**
- Modify: `CLAUDE.md` ("What Works" section — add the proposal flow; drop any stale claim it contradicts)
- No new code except fixes surfaced by verification.

- [ ] **Step 1: Full suites:** `source .venv-api/bin/activate && pytest backend/ -q` AND `npm test` AND `npx tsc --noEmit` AND `npm run lint` AND `npm run build` — all green, paste outputs.
- [ ] **Step 2: Manual smoke (mock-friendly):** `npm run dev`, load `examples/messy.ply`, Clean stage, click the `cleanup_scene` pill (requires the backend: `source .venv-api/bin/activate && python -m uvicorn backend.server:app --port 8000` — check README/server.py for the exact run incantation first). Verify: box appears with wireframe → ProposalCard shows → type "bigger" → box grows → Approve → crop commits and history/undo works → brush round tints → batch proposal → Approve deletes. Verify moving the camera during review does NOT pause the run, and Stop during a proposal cleanly ends it. If no live model key is configured, verify the machinery instead via the mock provider path used by existing integration tests (`backend/agent/mocks.py`) and exercise the frontend with `frontend/src/agent/mock-backend.ts`.
- [ ] **Step 3: Update CLAUDE.md; commit** `docs: record proposal-flow cleanup in What Works`

---

## Execution notes for the orchestrator

- Dependency order: 1 → 2 → 3 (backend chain); 4, 5, 6, 7 independent after 1 (frontend); 8 needs 4+5+7; 9 needs 5+7; 10 needs 1; 11 needs 10; 12 needs 1-3; 13 last.
- Parallel-safe batches: {4, 6, 7} after 1; {5} touches SceneManager like 6 — run 5 and 6 SEQUENTIALLY (same file). 2 and 3 sequential (backend), can overlap the frontend batch.
- Task 6 (tint) is the highest-risk task (SparkJS API uncertainty) — schedule it early so a surprise surfaces with slack left.
