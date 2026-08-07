# Subject-First Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the cleanup run's crop-box phase with subject lock-on: code finds the dense connected subject as nested keep-levels, the VL model votes per-view on whether the tinted highlight matches the real structure, and one approve/reject/slider card executes `keep_only_ids`.

**Architecture:** A new pure-numpy subject finder (`backend/analysis/subject.py`) produces ~5 nested keep-sets (tight→loose). `CleanupController._phase1_subject` tints the default level, reuses the phase-4 frame/orbit/capture pattern for up to 2 forced `judge_subject` voting rounds that nudge the level, then parks one `keep_only_subject` proposal whose card has a looser↔tighter slider (levels pre-shipped to the frontend, re-tint is local). Approve runs `keep_only_ids` through `_guarded_edit`. Contracts bump v0.7 → v0.8 in both mirrors.

**Tech Stack:** Python 3.12 / numpy / pytest (backend), TypeScript / React / vitest (frontend).

## Global Constraints

- Contracts are frozen within a phase: every contract change lands in BOTH `backend/contracts/tools.py` and `frontend/src/contracts.ts` in the same task, with `backend/contracts/tests/test_tools.py` and `frontend/src/agent/contracts.test.ts` updated. Tag additions `v0.8`.
- The model is consulted ONLY via `ask_forced` one-shot calls; every model failure degrades one datum to a safe default (keep / default level). The run must never stall.
- `show_subject_preview` is controller-dispatched only, never offered to the model (same as `select_by_ids` — copy its registry comment).
- Backend coordinates everywhere in tool args (COLMAP Y-down); the frontend flips.
- Frontend type-check is `npx tsc -b` (NEVER `tsc --noEmit`). Backend tests run with the `.venv-api` venv: `source .venv-api/bin/activate`.
- The freeform Clean chat keeps `crop_outside_box` / `show_box_preview` / `adjust_box_preview` untouched; only the cleanup run stops using the box.

---

### Task 1: Subject finder (`backend/analysis/subject.py`)

**Files:**
- Create: `backend/analysis/subject.py`
- Test: `backend/analysis/tests/test_subject.py`

**Interfaces:**
- Consumes: nothing new (pure numpy; mirrors `clusters.py` conventions).
- Produces: `find_subject(means, opacity, ids, *, cell_frac=0.03, levels=5, min_splats=100) -> SubjectLevels | None` and `@dataclass SubjectLevels` with fields `level_ids: list[np.ndarray]` (cumulative, tight→loose, sorted int64), `counts: list[int]`, `default_level: int`, `bbox_min: list[float]`, `bbox_max: list[float]` (bbox of the default level, for `frame_object`).

- [ ] **Step 1: Write failing tests**

```python
"""backend/analysis/tests/test_subject.py"""
import numpy as np

from backend.analysis.subject import find_subject


def _sphere_plus_floaters(n_core=600, n_junk=40, seed=7):
    rng = np.random.default_rng(seed)
    v = rng.normal(size=(n_core, 3))
    core = v / np.linalg.norm(v, axis=1, keepdims=True)  # unit shell
    d = rng.normal(size=(n_junk, 3))
    junk = d / np.linalg.norm(d, axis=1, keepdims=True) * rng.uniform(5, 8, (n_junk, 1))
    means = np.vstack([core, junk])
    opacity = np.full(len(means), 0.9)
    ids = np.arange(len(means), dtype=np.int64)
    return means, opacity, ids


def test_levels_are_nested_and_monotonic():
    s = find_subject(*_sphere_plus_floaters())
    assert s is not None
    assert len(s.level_ids) == 5 and s.default_level == 2
    for a, b in zip(s.level_ids, s.level_ids[1:]):
        assert np.isin(a, b).all()          # tight ⊂ loose
    assert s.counts == [len(l) for l in s.level_ids]


def test_subject_captures_core_and_excludes_floaters():
    means, opacity, ids = _sphere_plus_floaters()
    s = find_subject(means, opacity, ids)
    core_ids = ids[:600]
    junk_ids = ids[600:]
    got = s.level_ids[s.default_level]
    assert np.isin(core_ids, got).mean() >= 0.95     # keeps the sphere
    assert not np.isin(junk_ids, s.level_ids[-1]).any()  # loosest still excludes junk


def test_degenerate_scene_returns_none():
    means = np.random.default_rng(0).normal(size=(10, 3))
    assert find_subject(means, np.full(10, 0.9), np.arange(10)) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `source .venv-api/bin/activate && pytest backend/analysis/tests/test_subject.py -v`
Expected: FAIL — `ModuleNotFoundError: backend.analysis.subject`

- [ ] **Step 3: Implement**

```python
"""Subject lock-on for the cleanup run (subject-first cleanup, 2026-08-07).

Finds THE subject — the largest dense connected component of occupied
voxels — and returns nested keep-levels (tight -> loose) formed by dilating
that component into surrounding occupied voxels. Pure numpy, headless.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

_OFFSETS = [
    (dx, dy, dz)
    for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)
    if (dx, dy, dz) != (0, 0, 0)
]


@dataclass
class SubjectLevels:
    level_ids: list[np.ndarray]   # cumulative id sets, tight -> loose
    counts: list[int]
    default_level: int
    bbox_min: list[float]         # bbox of the default level (for framing)
    bbox_max: list[float]


def find_subject(
    means: np.ndarray,
    opacity: np.ndarray,
    ids: np.ndarray,
    *,
    cell_frac: float = 0.03,
    levels: int = 5,
    min_splats: int = 100,
) -> SubjectLevels | None:
    means = np.asarray(means, dtype=np.float64)
    ids = np.asarray(ids)
    if len(means) < min_splats:
        return None

    scene_radius = float(np.linalg.norm(means.max(axis=0) - means.min(axis=0))) / 2.0
    cell = max(scene_radius * cell_frac, 1e-6)
    keys = np.floor(means / cell).astype(np.int64)

    buckets: dict[tuple[int, int, int], list[int]] = {}
    for i, k in enumerate(map(tuple, keys)):
        buckets.setdefault(k, []).append(i)

    # Dense = at least the mean occupancy (and >= 2): junk voxels are sparse.
    mean_occ = float(np.mean([len(v) for v in buckets.values()]))
    dense_min = max(2, int(round(mean_occ)))
    dense = {k for k, v in buckets.items() if len(v) >= dense_min}
    if not dense:
        return None

    # Largest dense connected component by SPLAT count (26-connectivity).
    seen: set[tuple[int, int, int]] = set()
    best: set[tuple[int, int, int]] = set()
    best_n = 0
    for start in dense:
        if start in seen:
            continue
        comp: set[tuple[int, int, int]] = set()
        q = deque([start])
        seen.add(start)
        while q:
            v = q.popleft()
            comp.add(v)
            for off in _OFFSETS:
                nb = (v[0] + off[0], v[1] + off[1], v[2] + off[2])
                if nb in dense and nb not in seen:
                    seen.add(nb)
                    q.append(nb)
        n = sum(len(buckets[v]) for v in comp)
        if n > best_n:
            best, best_n = comp, n
    if best_n < min_splats:
        return None

    # Level k = component dilated k voxel-steps into ANY occupied voxel.
    ring = set(best)
    level_ids: list[np.ndarray] = []
    for _ in range(levels):
        rows = np.asarray(sorted(i for v in ring for i in buckets[v]), dtype=np.int64)
        level_ids.append(np.sort(ids[rows]))
        grown = set(ring)
        for v in ring:
            for off in _OFFSETS:
                nb = (v[0] + off[0], v[1] + off[1], v[2] + off[2])
                if nb in buckets:
                    grown.add(nb)
        ring = grown

    default_level = levels // 2
    pos_of = {int(i): n for n, i in enumerate(ids)}
    rows = np.asarray([pos_of[int(i)] for i in level_ids[default_level]], dtype=np.int64)
    p = means[rows]
    return SubjectLevels(
        level_ids=level_ids,
        counts=[int(len(l)) for l in level_ids],
        default_level=default_level,
        bbox_min=[float(v) for v in p.min(axis=0)],
        bbox_max=[float(v) for v in p.max(axis=0)],
    )


__all__ = ["SubjectLevels", "find_subject"]
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest backend/analysis/tests/test_subject.py -v`
Expected: 3 PASS. If `test_subject_captures_core_and_excludes_floaters` fails on the 0.95 assertion, lower `dense_min` to `max(2, int(round(mean_occ * 0.5)))` — the sphere shell must land in `dense`.

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/subject.py backend/analysis/tests/test_subject.py
git commit -m "feat(analysis): nested-level subject finder for subject-first cleanup"
```

---

### Task 2: Contracts v0.8 — both mirrors + drift tests

**Files:**
- Modify: `backend/contracts/tools.py` (registry ~line 211, `propose_decision` kind enum ~line 265, `PROPOSAL_DECISION_FIELDS` ~line 416, `CONTROLLER_CHOICE_SPECS` ~line 448)
- Modify: `frontend/src/contracts.ts` (FRONTEND_TOOLS list ~line 103, `PROPOSAL_DECISION_FIELDS` ~line 169, proposal kinds ~line 171)
- Modify: `backend/contracts/tests/test_tools.py`, `frontend/src/agent/contracts.test.ts`

**Interfaces:**
- Produces: registry entry `show_subject_preview` (frontend) with args `{base_ids: int[], deltas: int[][], counts: int[], level: int}` — all optional except `level`, so a level-only re-tint call is valid; `propose_decision` kind `keep_only_subject`; decision field `level`; `CONTROLLER_CHOICE_SPECS["judge_subject"]` with verdict enum `["good", "clipping_structure", "including_junk"]` + required `reason`.

- [ ] **Step 1: Add failing drift-test expectations**

In `backend/contracts/tests/test_tools.py`, extend the existing name/spec assertions (follow the file's current style) to require: `"show_subject_preview" in FRONTEND_TOOLS`; `"keep_only_subject"` in the `propose_decision` kind enum; `"level" in PROPOSAL_DECISION_FIELDS`; `CONTROLLER_CHOICE_SPECS["judge_subject"]["parameters"]["properties"]["verdict"]["enum"] == ["good", "clipping_structure", "including_junk"]`. Mirror the same three checks in `frontend/src/agent/contracts.test.ts` against the TS constants.

- [ ] **Step 2: Run to verify failure**

Run: `pytest backend/contracts/tests/test_tools.py -v` and `cd frontend 2>/dev/null; npx vitest run src/agent/contracts.test.ts` (run vitest from wherever the existing test scripts run it — see `package.json`).
Expected: both FAIL on the new assertions.

- [ ] **Step 3: Implement backend side**

In `backend/contracts/tools.py`, after the `select_by_ids` entry (~line 211):

```python
    # v0.8 — subject-first cleanup: ship nested keep-levels to the viewer and
    # tint one. Controller-dispatched only; never offered to the model.
    ToolEntry("show_subject_preview", "frontend", {
        "type": "object",
        "properties": {
            "base_ids": {"type": "array", "items": {"type": "integer"},
                         "description": "Level-0 (tightest) stable splat ids"},
            "deltas": {"type": "array",
                       "items": {"type": "array", "items": {"type": "integer"}},
                       "description": "Ids ADDED by each successive level"},
            "counts": {"type": "array", "items": {"type": "integer"}},
            "level": {"type": "integer",
                      "description": "Level to tint now (0 = tightest)"},
        },
        "required": ["level"],
    }, "{ok, count}"),
```

In the `propose_decision` kind enum add `"keep_only_subject"` (and extend the description: `"keep_only_subject (v0.8) is the subject lock-on card — its reply may carry the slider's level"`). Change:

```python
PROPOSAL_DECISION_FIELDS: tuple[str, ...] = ("verdict", "feedback", "box", "level")
```

Append to `CONTROLLER_CHOICE_SPECS`:

```python
    "judge_subject": {
        "name": "judge_subject",
        "description": "Judge whether the bright-tinted keep-region matches "
                       "the real structure.",
        "parameters": {
            "type": "object",
            "properties": {
                "verdict": {"type": "string",
                            "enum": ["good", "clipping_structure", "including_junk"]},
                "reason": {"type": "string", "description": "One short sentence"},
            },
            "required": ["verdict", "reason"],
        },
    },
```

- [ ] **Step 4: Implement TS mirror**

In `frontend/src/contracts.ts`: add `"show_subject_preview"` to the frontend tool-name list (line ~103, next to `select_by_ids`); `PROPOSAL_DECISION_FIELDS = ['verdict', 'feedback', 'box', 'level'] as const`; add `'keep_only_subject'` to the proposal-kind list/union at ~line 171.

- [ ] **Step 5: Run to verify pass, then commit**

Run: `pytest backend/contracts/tests/ -v && npx vitest run src/agent/contracts.test.ts && npx tsc -b`
Expected: PASS / PASS / clean.

```bash
git add backend/contracts/tools.py backend/contracts/tests/test_tools.py frontend/src/contracts.ts frontend/src/agent/contracts.test.ts
git commit -m "feat(contracts): v0.8 subject-first cleanup — show_subject_preview, keep_only_subject, judge_subject, level field"
```

---

### Task 3: Frontend subject preview store + executor + ws-client level plumbing

**Files:**
- Create: `frontend/src/agent/subjectPreview.ts`
- Test: `frontend/src/agent/subjectPreview.test.ts`
- Modify: `frontend/src/agent/executors.ts` (add branch next to `select_by_ids`, ~line 89), `frontend/src/agent/panels.ts` (`ProposalState`), `frontend/src/agent/ws-client.ts` (proposal case ~line 175 and decide payload ~line 232)
- Modify: `frontend/src/agent/ws-client.test.ts`

**Interfaces:**
- Consumes: `RendererBridge.updateSelection(ids, mode)` / `clearSelection()` (frontend/src/agent/types.ts:47-48).
- Produces: `subjectPreview` module — `setSubject(bridge, {baseIds, deltas, counts, level}): number`, `applyLevel(bridge, level): number` (returns tinted count), `getState(): {counts: number[], level: number} | null`, `clear(bridge): void`. `ProposalState` gains `subject?: { counts: number[]; level: number; onLevel: (k: number) => void }`.

- [ ] **Step 1: Write failing tests**

`subjectPreview.test.ts`: with a mock bridge (record `updateSelection`/`clearSelection` calls), assert (a) `setSubject` with base `[1,2]`, deltas `[[3],[4,5]]`, level 1 tints exactly `[1,2,3]`; (b) `applyLevel(2)` re-tints `[1,2,3,4,5]` with a `clearSelection` first; (c) `applyLevel` clamps out-of-range; (d) `clear` empties state and selection.
`ws-client.test.ts`: add a case — park a `propose_decision` with `kind: 'keep_only_subject'` after a `show_subject_preview` executed with level 1; decide `approved`; assert the correlated tool_result payload contains `level: <current level>` and that subject state is cleared after the decision.

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run src/agent/subjectPreview.test.ts src/agent/ws-client.test.ts`
Expected: FAIL (module missing / payload lacks level).

- [ ] **Step 3: Implement**

`subjectPreview.ts`:

```typescript
/** Subject lock-on preview state (v0.8). The controller ships nested
 *  keep-levels ONCE; the card's slider re-tints locally with zero round trips
 *  (the run is blocked on the parked proposal, so no dispatch could serve it). */
import type { RendererBridge } from './types.ts'

interface SubjectState { cumulative: number[][]; counts: number[]; level: number }
let state: SubjectState | null = null

export function setSubject(
  bridge: RendererBridge,
  args: { baseIds: number[]; deltas: number[][]; counts: number[]; level: number },
): number {
  const cumulative: number[][] = [args.baseIds]
  for (const d of args.deltas) cumulative.push([...cumulative[cumulative.length - 1], ...d])
  state = { cumulative, counts: args.counts, level: 0 }
  return applyLevel(bridge, args.level)
}

export function applyLevel(bridge: RendererBridge, level: number): number {
  if (!state) return 0
  state.level = Math.max(0, Math.min(state.cumulative.length - 1, level))
  bridge.clearSelection()
  return bridge.updateSelection(state.cumulative[state.level], 'add')
}

export function getState(): { counts: number[]; level: number } | null {
  return state ? { counts: state.counts, level: state.level } : null
}

export function clear(bridge: RendererBridge): void {
  state = null
  bridge.clearSelection()
}
```

`executors.ts` branch (after `select_by_ids`):

```typescript
    // v0.8 — subject lock-on preview (CleanupController-dispatched only)
    if (tool === 'show_subject_preview') {
      if (Array.isArray(args.base_ids)) {
        const count = subjectPreview.setSubject(this.bridge, {
          baseIds: args.base_ids as number[],
          deltas: (args.deltas as number[][]) ?? [],
          counts: (args.counts as number[]) ?? [],
          level: Number(args.level ?? 0),
        })
        await sleep(350)  // paced so the operator sees the highlight land (SC2)
        return { ok: true, count }
      }
      const count = subjectPreview.applyLevel(this.bridge, Number(args.level ?? 0))
      await sleep(350)
      return { ok: true, count }
    }
```

`panels.ts`: add to `ProposalState`:

```typescript
  /** For keep_only_subject (v0.8): slider state — counts per level, current
   *  level, and the local re-tint callback (no round trip while parked). */
  subject?: { counts: number[]; level: number; onLevel: (k: number) => void }
```

`ws-client.ts` proposal case: when `kind === 'keep_only_subject'`, populate `subject` from `subjectPreview.getState()` with `onLevel: (k) => subjectPreview.applyLevel(this.bridge, k)`. In the decide path (where `box` is attached, ~line 232): on any verdict for that kind, read `const lvl = subjectPreview.getState()?.level`, attach `...(lvl !== undefined ? { level: lvl } : {})` to the payload for `approved`, then `subjectPreview.clear(this.bridge)` — a DECIDED subject preview comes down with the card, same rule as the box.

- [ ] **Step 4: Run to verify pass, then commit**

Run: `npx vitest run src/agent && npx tsc -b`
Expected: all PASS, type-check clean.

```bash
git add frontend/src/agent/subjectPreview.ts frontend/src/agent/subjectPreview.test.ts frontend/src/agent/executors.ts frontend/src/agent/panels.ts frontend/src/agent/ws-client.ts frontend/src/agent/ws-client.test.ts
git commit -m "feat(agent-fe): subject lock-on preview with local level re-tint"
```

---

### Task 4: ProposalCard slider

**Files:**
- Modify: `src/ui/ProposalCard.tsx`, `src/ui/proposalTitle.ts`

**Interfaces:**
- Consumes: `ProposalState.subject` from Task 3.

- [ ] **Step 1: Implement (small UI change — no new test file; proposalTitle is covered by its existing unit test if one exists, extend it)**

`proposalTitle.ts`: add `case 'keep_only_subject': return 'Keep the highlighted subject — delete everything else?'`.

`ProposalCard.tsx`: add `keep_only_subject: Focus` to `KIND_ICONS`. After the summary paragraph, render the slider when `proposal.subject` exists:

```tsx
      {proposal.subject && (
        <div className="flex items-center gap-2 text-xs text-text-secondary">
          <span>tighter</span>
          <input
            type="range"
            min={0}
            max={proposal.subject.counts.length - 1}
            step={1}
            value={level}
            onChange={(e) => {
              const k = Number(e.target.value)
              setLevel(k)
              proposal.subject!.onLevel(k)
            }}
            className="flex-1 accent-accent-amber"
            aria-label="Keep-region size"
          />
          <span>looser</span>
          <span className="w-16 text-right font-mono text-text-primary">
            {proposal.subject.counts[level]?.toLocaleString() ?? ''}
          </span>
        </div>
      )}
```

with `const [level, setLevel] = useState(proposal.subject?.level ?? 0)` alongside the existing `feedback` state.

- [ ] **Step 2: Verify and commit**

Run: `npx tsc -b && npm run lint && npx vitest run`
Expected: clean, all PASS.

```bash
git add src/ui/ProposalCard.tsx src/ui/proposalTitle.ts
git commit -m "feat(ui): looser/tighter slider on the keep_only_subject card"
```

---

### Task 5: Controller — replace `_phase1_crop` with `_phase1_subject`

**Files:**
- Modify: `backend/agent/cleanup_controller.py` (config ~line 37, instruction consts ~line 49, `run()` ~line 224, replace `_phase1_crop` ~lines 248-274)
- Test: `backend/agent/tests/test_cleanup_controller.py` (rewrite phase-1 cases; follow the file's existing mock channel/dispatcher/provider pattern from `backend/agent/mocks.py`)

**Interfaces:**
- Consumes: `find_subject`/`SubjectLevels` (Task 1), `show_subject_preview` + `keep_only_subject` + `judge_subject` (Task 2), `executor.keep_only_ids(ids)` (backend/analysis/editing.py:165), existing `_dispatch`/`_ask`/`_guarded_edit`/`_resync_renderer`/`_checkpoint`.
- Produces: `CleanupConfig` fields `subject_levels: int = 5`, `subject_judge_frames: int = 3`, `subject_judge_rounds: int = 2`.

- [ ] **Step 1: Write failing tests**

Replace the phase-1 crop tests with (using the existing mock style — scripted dispatcher results and scripted `ask_forced` replies):

```python
def test_subject_votes_loosen_then_card(...):
    # 3 judge_subject replies all "clipping_structure" -> controller re-dispatches
    # show_subject_preview with level 3 (default 2 + 1), then parks keep_only_subject.

def test_subject_model_unavailable_degrades_to_default_level(...):
    # ask_forced -> None for every frame: no level change, card still parked,
    # run continues to phase 2 (never stalls).

def test_subject_approve_executes_keep_only_with_reply_level(...):
    # decision reply {"verdict": "approved", "level": 4} -> executor.keep_only_ids
    # called with subject.level_ids[4]; _edits_applied == 1; resync sent.

def test_subject_reject_skips_edit(...):
    # {"verdict": "rejected"} -> keep_only_ids never called, phase 2 still runs.

def test_no_subject_found_skips_phase(...):
    # find_subject returns None (tiny scene) -> no preview, no card, phase 2 runs.
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest backend/agent/tests/test_cleanup_controller.py -v`
Expected: new tests FAIL; old crop tests removed in the same edit.

- [ ] **Step 3: Implement**

Config additions:

```python
    subject_levels: int = 5
    subject_judge_frames: int = 3
    subject_judge_rounds: int = 2
```

Instruction:

```python
_SUBJECT_INSTRUCTION = (
    "The bright-tinted splats are the region I plan to KEEP; everything dim "
    "will be DELETED. Call judge_subject: 'good' if the tint covers exactly "
    "the real structure, 'clipping_structure' if any real scenery is dim "
    "(keep-region too tight), or 'including_junk' if floating debris or "
    "disconnected fragments are tinted (too loose)."
)
```

Replace `_phase1_crop` (and its call in `run()`) with:

```python
    # ---- phase 1: subject lock-on ----------------------------------------- #
    async def _phase1_subject(self) -> None:
        means, opacity, ids = self._arrays()
        subject = find_subject(
            means, opacity, ids,
            cell_frac=self.config.cell_frac, levels=self.config.subject_levels,
        )
        if subject is None:
            await self._say("Could not isolate a subject — skipping the keep-only pass.")
            return
        level = subject.default_level
        await self._say("Locking onto the subject — bright is what I plan to keep.")
        await self._dispatch("show_subject_preview", {
            "base_ids": [int(i) for i in subject.level_ids[0]],
            "deltas": [
                [int(i) for i in np.setdiff1d(b, a)]
                for a, b in zip(subject.level_ids, subject.level_ids[1:])
            ],
            "counts": subject.counts,
            "level": level,
        })
        level = await self._judge_subject_rounds(subject, level)

        n_total = len(ids)
        n_keep = subject.counts[level]
        reply = await self._dispatch("propose_decision", {
            "kind": "keep_only_subject",
            "summary": f"Keep the highlighted subject ({n_keep} splats) and delete "
                       f"the {n_total - n_keep} splats outside it. Slide "
                       "looser/tighter to adjust before approving.",
        })
        verdict = (reply.get("result") or {}) if reply.get("ok") else {}
        if isinstance(verdict, dict) and verdict.get("verdict") == "approved":
            try:
                lvl = int(verdict.get("level", level))
            except (TypeError, ValueError):
                lvl = level
            lvl = max(0, min(len(subject.level_ids) - 1, lvl))
            out = await self._guarded_edit(
                "keep_only_ids", [int(i) for i in subject.level_ids[lvl]],
            )
            if out["ok"]:
                self.crop_result = out["result"]
                await self._say("Kept the subject — everything outside it is gone.")
            await self._resync_renderer()
        else:
            await self._say("Keep-only skipped — moving on to the noise survey.")
        await self._dispatch("clear_selection", {})

    async def _judge_subject_rounds(self, subject: SubjectLevels, level: int) -> int:
        """Up to subject_judge_rounds voting rounds; each frames the subject,
        orbits between captures, and takes one forced judge_subject vote per
        frame. Model failures are abstentions — the level never moves on them."""
        max_level = len(subject.level_ids) - 1
        for _ in range(self.config.subject_judge_rounds):
            await self._checkpoint()
            framed = await self._dispatch("frame_object", {
                "bbox": {"min": subject.bbox_min, "max": subject.bbox_max},
                "duration_ms": 900,
            })
            if not framed.get("ok"):
                return level          # fail closed: never judge an unframed view
            votes: list[str] = []
            center = [(a + b) / 2 for a, b in zip(subject.bbox_min, subject.bbox_max)]
            for j in range(self.config.subject_judge_frames):
                if j:
                    await self._dispatch("orbit", {
                        "center": center,
                        "deg": 360 // self.config.subject_judge_frames,
                        "axis": "y", "duration_ms": 700,
                    })
                cap = await self._dispatch("capture_frame", {})
                frames = cap.get("frames") or []
                if not frames:
                    continue
                args = await self._ask(_SUBJECT_INSTRUCTION, "judge_subject", frames[0])
                v = (args or {}).get("verdict")
                if v in ("good", "clipping_structure", "including_junk"):
                    votes.append(v)
            loosen = votes.count("clipping_structure")
            tighten = votes.count("including_junk")
            if loosen > tighten and level < max_level:
                level += 1
                await self._say("The model says the highlight clips real structure — loosening one step.")
            elif tighten > loosen and level > 0:
                level -= 1
                await self._say("The model says the highlight includes junk — tightening one step.")
            else:
                break
            await self._dispatch("show_subject_preview", {"level": level})
        return level
```

Add `from backend.analysis.subject import SubjectLevels, find_subject` to the imports and change `run()`'s first phase call to `await self._phase1_subject()`. Delete `_phase1_crop`.

- [ ] **Step 4: Run to verify pass**

Run: `pytest backend/agent/tests/ -v`
Expected: all PASS (including untouched phase 2-6 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/agent/cleanup_controller.py backend/agent/tests/test_cleanup_controller.py
git commit -m "feat(agent): subject lock-on phase replaces the crop-box card"
```

---

### Task 6: Full verification + live demo pass

- [ ] **Step 1: Full suites**

Run: `pytest && npx tsc -b && npm run lint && npx vitest run`
Expected: all green.

- [ ] **Step 2: Restart backend + live check**

The running backend predates these changes — restart it (`./scripts/dev.sh` after killing the old uvicorn on :8000). Load `examples/messy.ply`, run `cleanup_scene`: expect the tinted subject (sphere bright, floaters dim), up to 2 short judged orbit rounds, the slider card, and on approve a scene with the floaters outside the subject gone, then the normal survey/tour on what remains.

- [ ] **Step 3: Commit any live-found fixes; done**
