# App-Owned Survey Analyst Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Understand-stage runs answer "what does this scene show" from an app-flown, deterministically framed multi-view survey; the model never navigates, and survey frames persist across the conversation.

**Architecture:** A new `survey_capture` frontend tool captures the operator's view plus three framed poses (top-down + two obliques) computed from the live scene core. The agent loop dispatches it app-side before the model's first turn in Understand runs, attaches the frames to every model call, and offers the model only `answer` + `narrate`. `real_engine` persists frames + scene revision per scene; the executor skips re-flying when the revision is unchanged.

**Tech Stack:** Python 3.12 / FastAPI backend, TypeScript + Three.js frontend, pytest, vitest.

**Spec:** `docs/superpowers/specs/2026-08-03-app-owned-survey-analyst-design.md`

## Global Constraints

- Contract change is ADDITIVE only: new tool `survey_capture`, contract bump to **v0.6**, both mirrors updated (`backend/contracts/tools.py`, `frontend/src/contracts.ts`), drift tests green on both sides.
- Clean-stage behavior untouched: all Clean tools, percepts, proposals stay as they are.
- Backend tests: `pytest` from repo root (Python 3.12 venv `.venv-api`). Frontend: `npx vitest run <file>`; type-check with `npx tsc -b` (NEVER `tsc --noEmit` — solution-style tsconfig makes it a no-op).
- Commit after each task; message style follows repo history (`feat(agent): …`, `feat(contracts): …`).

---

### Task 1: Contract v0.6 — `survey_capture` registered on both sides

**Files:**
- Modify: `backend/contracts/tools.py` (registry entry + version-history docstring)
- Modify: `backend/agent/dispatch.py:63-94` (`_FRONTEND_CMD_TYPE`)
- Modify: `backend/agent/types.py:34` (`VISION_TOOLS`)
- Modify: `frontend/src/contracts.ts:86-100` (`FRONTEND_TOOLS`)
- Test: `backend/contracts/tests/test_tools.py`, `frontend/src/agent/contracts.test.ts` (existing drift tests — update expectations)

**Interfaces:**
- Produces: registry entry `survey_capture` (`runs_on="frontend"`, params `{if_revision_not?: integer}`), WS cmd type `capture_request`, membership in `VISION_TOOLS` (so `dispatch._extract_frames` populates `frames`).

- [ ] **Step 1: Run both drift tests to see the current green baseline**

Run: `pytest backend/contracts/tests/test_tools.py -q` and `npx vitest run frontend/src/agent/contracts.test.ts`
Expected: PASS (baseline).

- [ ] **Step 2: Add the registry entry**

In `backend/contracts/tools.py`, after the `capture_orbit` entry in the `── frontend (capture) ──` section:

```python
    # v0.6 — app-owned survey (app dispatches it; never offered to the model):
    # operator's view + framed top-down/oblique views in one round trip.
    ToolEntry("survey_capture", "frontend", {
        "type": "object",
        "properties": {
            "if_revision_not": {
                "type": "integer",
                "description": "Skip the flight and return {unchanged} if the "
                               "scene revision still equals this value",
            },
        },
    }, "image bytes[] + labels + revision"),
```

Extend the module docstring's version history: `v0.6 adds survey_capture — the app-owned analyst survey (docs/superpowers/specs/2026-08-03-app-owned-survey-analyst-design.md).`

- [ ] **Step 3: Route it in the dispatcher and count it as a vision tool**

`backend/agent/dispatch.py` — add to `_FRONTEND_CMD_TYPE` next to the capture entries:

```python
    "survey_capture": "capture_request",
```

`backend/agent/types.py` — extend `VISION_TOOLS`:

```python
VISION_TOOLS: frozenset[str] = frozenset({"capture_frame", "capture_orbit", "survey_capture"})
```

- [ ] **Step 4: Mirror in TypeScript**

`frontend/src/contracts.ts` — append inside `FRONTEND_TOOLS`:

```typescript
  // v0.6 — app-owned survey (app dispatches; never offered to the model)
  "survey_capture",
```

- [ ] **Step 5: Update drift-test expectations and run them**

Run: `pytest backend/contracts/tests/test_tools.py -q` — if a count/name assertion fails, add `survey_capture` to the expected frontend-tool set (follow how `reframe` was added for v0.4).
Run: `npx vitest run frontend/src/agent/contracts.test.ts` — same.
Expected: both PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/contracts/tools.py backend/agent/dispatch.py backend/agent/types.py frontend/src/contracts.ts backend/contracts/tests/test_tools.py
git commit -m "feat(contracts): v0.6 — survey_capture app-owned analyst survey tool"
```

---

### Task 2: Survey pose math (`surveyPoses`)

**Files:**
- Modify: `frontend/src/agent/camera.ts` (new exported function; reuse `DEFAULT_FRAME_MARGIN`)
- Test: `frontend/src/agent/camera.test.ts`

**Interfaces:**
- Produces: `surveyPoses(camera: THREE.PerspectiveCamera, core: {center: [number,number,number]; radius: number}): {label: string; position: THREE.Vector3; target: THREE.Vector3}[]` — exactly 3 poses: `'top-down'`, `'oblique view from the north-east'`, `'oblique view from the south-west'`, all targeting the core center.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/agent/camera.test.ts` (match its existing imports/style):

```typescript
import * as THREE from 'three'
import { surveyPoses } from './camera.ts'

describe('surveyPoses', () => {
  const camera = new THREE.PerspectiveCamera(60, 16 / 9)
  const core = { center: [10, 2, -5] as [number, number, number], radius: 4 }

  it('returns three labeled poses, all targeting the core center', () => {
    const poses = surveyPoses(camera, core)
    expect(poses.map((p) => p.label)).toEqual([
      'top-down',
      'oblique view from the north-east',
      'oblique view from the south-west',
    ])
    for (const p of poses) {
      expect(p.target.toArray()).toEqual(core.center)
    }
  })

  it('places every pose at the same framing distance from the center', () => {
    const poses = surveyPoses(camera, core)
    const c = new THREE.Vector3(...core.center)
    const dists = poses.map((p) => p.position.distanceTo(c))
    for (const d of dists) {
      expect(d).toBeGreaterThan(core.radius) // outside the core sphere
      expect(Math.abs(d - dists[0])).toBeLessThan(1e-6)
    }
  })

  it('top-down sits high above the center; obliques at moderate elevation', () => {
    const [top, ne, sw] = surveyPoses(camera, core)
    const elevation = (p: THREE.Vector3) => {
      const dy = p.y - core.center[1]
      const dh = Math.hypot(p.x - core.center[0], p.z - core.center[2])
      return (Math.atan2(dy, dh) * 180) / Math.PI
    }
    expect(elevation(top.position)).toBeGreaterThan(80)
    expect(elevation(ne.position)).toBeCloseTo(35, 0)
    expect(elevation(sw.position)).toBeCloseTo(35, 0)
    // opposite azimuths: NE and SW horizontal offsets point opposite ways
    const h = (p: THREE.Vector3) =>
      new THREE.Vector2(p.x - core.center[0], p.z - core.center[2]).normalize()
    expect(h(ne.position).dot(h(sw.position))).toBeLessThan(-0.99)
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `npx vitest run frontend/src/agent/camera.test.ts`
Expected: FAIL — `surveyPoses` is not exported.

- [ ] **Step 3: Implement**

In `frontend/src/agent/camera.ts`, near `framingDistance`:

```typescript
/**
 * Deterministic analyst-survey poses around the scene core (spec
 * 2026-08-03-app-owned-survey-analyst): a near-top-down view plus two
 * opposite obliques, all at the distance that frames the core in the
 * camera's limiting FOV. Top-down is 85°, not 90° — a straight-down
 * lookAt with +Y up is degenerate.
 */
export function surveyPoses(
  camera: THREE.PerspectiveCamera,
  core: { center: [number, number, number]; radius: number },
): { label: string; position: THREE.Vector3; target: THREE.Vector3 }[] {
  const c = new THREE.Vector3(core.center[0], core.center[1], core.center[2])
  const dist = framingDistance(camera, core.radius)
  const DEG = Math.PI / 180
  const pose = (label: string, elevationDeg: number, azimuthDeg: number) => {
    const el = elevationDeg * DEG
    const az = azimuthDeg * DEG
    return {
      label,
      position: new THREE.Vector3(
        c.x + dist * Math.cos(el) * Math.cos(az),
        c.y + dist * Math.sin(el),
        c.z + dist * Math.cos(el) * Math.sin(az),
      ),
      target: c.clone(),
    }
  }
  return [
    pose('top-down', 85, 45),
    pose('oblique view from the north-east', 35, 45),
    pose('oblique view from the south-west', 35, 225),
  ]
}
```

If `framingDistance` is module-private, keep it private and call it directly (same module). Export `surveyPoses` from `frontend/src/agent/index.ts` only if other agent modules import via the barrel — follow how `sceneCoverage` is exported.

- [ ] **Step 4: Run tests + type-check**

Run: `npx vitest run frontend/src/agent/camera.test.ts` → PASS. `npx tsc -b` → clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/agent/camera.ts frontend/src/agent/camera.test.ts
git commit -m "feat(agent-fe): deterministic survey poses around the scene core"
```

---

### Task 3: `survey_capture` executor + WS routing

**Files:**
- Modify: `frontend/src/agent/executors.ts` (new method near `capture_frame`, `executors.ts:325`)
- Modify: `frontend/src/agent/ws-client.ts:79-88` (`capture_request` case)
- Test: `frontend/src/agent/executors.survey.test.ts` (new file)

**Interfaces:**
- Consumes: `surveyPoses` (Task 2), existing `animateTo`, `sleep`, `capturePNG`, `dataUrlToBase64`, `RendererBridge.getSceneRevision()`, `getSceneCore()`, `getCamera()`.
- Produces: `survey_capture(args: {if_revision_not?: number}): Promise<ToolResult>` returning either `{unchanged: true, revision}` or `{frames_base64: string[], labels: string[], revision: number}`. Backend `ws.py:_decode_frames` already converts `frames_base64` → `frames: list[bytes]` — no backend WS change needed.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/agent/executors.survey.test.ts`:

```typescript
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as THREE from 'three'

// capturePNG needs a real WebGL canvas — mock the capture module.
vi.mock('./capture.ts', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./capture.ts')>()
  return {
    ...mod,
    capturePNG: vi.fn(async () => 'data:image/png;base64,QUJD'), // "ABC"
  }
})

import { capturePNG } from './capture.ts'
import { FrontendExecutors } from './executors.ts'

function makeBridge(revision = 7) {
  const camera = new THREE.PerspectiveCamera(60, 16 / 9)
  camera.position.set(0, 10, 20)
  return {
    getSceneRevision: () => revision,
    getSceneCore: () => ({ center: [0, 0, 0] as [number, number, number], radius: 5 }),
    getCamera: () => camera,
    getCameraPose: () => ({
      position: camera.position.clone(),
      target: new THREE.Vector3(0, 0, 0),
    }),
    setCameraPose: vi.fn(),
    renderOnce: vi.fn(),
    getRenderer: () => ({}) as never,
  }
}

describe('survey_capture', () => {
  beforeEach(() => vi.clearAllMocks())

  it('short-circuits when the revision is unchanged', async () => {
    const ex = new FrontendExecutors(makeBridge() as never)
    const result = await ex.survey_capture({ if_revision_not: 7 })
    expect(result).toMatchObject({ unchanged: true, revision: 7 })
    expect(capturePNG).not.toHaveBeenCalled()
  })

  it('captures operator view + three survey poses with labels', async () => {
    const ex = new FrontendExecutors(makeBridge() as never)
    const result = (await ex.survey_capture({})) as {
      frames_base64: string[]
      labels: string[]
      revision: number
    }
    expect(result.frames_base64).toHaveLength(4)
    expect(result.labels).toEqual([
      "operator's view",
      'top-down',
      'oblique view from the north-east',
      'oblique view from the south-west',
    ])
    expect(result.revision).toBe(7)
    expect(result.frames_base64.every((f) => f === 'QUJD')).toBe(true)
  })

  it('returns only the operator view when there is no scene core', async () => {
    const bridge = { ...makeBridge(), getSceneCore: () => null }
    const ex = new FrontendExecutors(bridge as never)
    const result = (await ex.survey_capture({})) as { frames_base64: string[]; labels: string[] }
    expect(result.frames_base64).toHaveLength(1)
    expect(result.labels).toEqual(["operator's view"])
  })
})
```

Adjust the `FrontendExecutors` constructor call to its real signature (see how `executors.ts` is instantiated in `index.ts` / existing tests — pass the extra collaborators as stubs the same way existing executor tests do). If pose animation goes through `animateTo` internals that need more bridge methods, stub them as no-op `vi.fn()`s in `makeBridge`.

- [ ] **Step 2: Run to verify it fails**

Run: `npx vitest run frontend/src/agent/executors.survey.test.ts`
Expected: FAIL — `survey_capture` is not a function.

- [ ] **Step 3: Implement the executor**

In `frontend/src/agent/executors.ts`, after `capture_frame` (line ~355), add (import `surveyPoses` from `./camera.ts`):

```typescript
  /** App-owned analyst survey (spec 2026-08-03): capture the operator's view,
   *  then fly framed top-down + oblique poses and capture each. The model
   *  never calls this — the agent loop dispatches it before the first model
   *  turn of an Understand run. `if_revision_not` lets the loop skip the
   *  flight when the scene hasn't changed since the stored survey. */
  async survey_capture(args: { if_revision_not?: number }): Promise<ToolResult> {
    const revision = this.bridge.getSceneRevision()
    if (args.if_revision_not !== undefined && args.if_revision_not === revision) {
      return { unchanged: true, revision }
    }
    const frames_base64: string[] = []
    const labels: string[] = []

    // Frame 1 — the operator's current view ("the angle I just put in").
    frames_base64.push(dataUrlToBase64(await capturePNG(this.bridge)))
    labels.push("operator's view")

    const core = this.bridge.getSceneCore()
    if (core && core.radius > 0) {
      for (const pose of surveyPoses(this.bridge.getCamera(), core)) {
        await animateTo(this.bridge, pose.position, pose.target, 600)
        await sleep(250) // let Spark's async depth-sort settle at the new pose
        frames_base64.push(dataUrlToBase64(await capturePNG(this.bridge)))
        labels.push(pose.label)
      }
    }
    this.breadcrumb()
    return { frames_base64, labels, revision }
  }
```

(`capturePNG` / `dataUrlToBase64` are already imported for `capture_frame`; `animateTo` / `sleep` for the camera tools — reuse the same imports.)

- [ ] **Step 4: Route it in the WS client**

`frontend/src/agent/ws-client.ts`, `capture_request` case (~line 79):

```typescript
        case 'capture_request': {
          const result =
            tool === 'survey_capture'
              ? await this.executors.survey_capture(args ?? {})
              : tool === 'capture_orbit'
                ? await this.executors.capture_orbit(args ?? {})
                : await this.executors.capture_frame()
```

(Keep the existing orbit/frame lines exactly as they are — only add the survey branch.)

- [ ] **Step 5: Run tests + type-check**

Run: `npx vitest run frontend/src/agent/executors.survey.test.ts` → PASS. `npx vitest run` (full frontend suite) → no regressions. `npx tsc -b` → clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/agent/executors.ts frontend/src/agent/ws-client.ts frontend/src/agent/executors.survey.test.ts
git commit -m "feat(agent-fe): survey_capture executor — operator view + framed survey flight"
```

---

### Task 4: Analyst loop rework — survey-first, answer-only model surface

**Files:**
- Modify: `backend/agent/system_prompt.py` (UNDERSTAND_TOOLS, `_UNDERSTAND_PROMPT`, the two understand-stage skill recipes)
- Modify: `backend/agent/loop.py` (survey phase, per-call frame attach, `run()` signature)
- Test: `backend/agent/tests/test_survey.py` (new file)

**Interfaces:**
- Consumes: dispatcher routing for `survey_capture` (Task 1); frontend result shape `{frames_base64/labels/revision}` decoded by ws.py into `frames: list[bytes]` + `result: {labels, revision, ...}`.
- Produces: `AgentLoop.run(prompt, history=None, ledger=None, survey=None)` where `survey` is `{"frames": list[bytes], "labels": list[str], "revision": int|None} | None`; after an Understand run, `loop.survey_out` holds the same shape for persistence (Task 5).

- [ ] **Step 1: Write the failing tests**

Create `backend/agent/tests/test_survey.py`:

```python
"""App-owned survey phase (spec 2026-08-03-app-owned-survey-analyst)."""
from __future__ import annotations

import base64

import pytest

from backend.agent.loop import AgentLoop
from backend.agent.dispatch import ToolDispatcher
from backend.agent.mocks import MockBackendExecutor  # reuse existing mock executor
from backend.contracts import ModelResponse, ToolCall

PNG = b"\x89PNG-fake"
PNG_B64 = base64.b64encode(PNG).decode()


class SurveyChannel:
    """FrontendChannel fake: answers survey_capture like ws.py would (decoded
    frames), records every command."""

    def __init__(self, *, unchanged_at: int | None = None, fail: bool = False):
        self.commands: list[dict] = []
        self.events: list[dict] = []
        self.unchanged_at = unchanged_at
        self.fail = fail

    async def send_command(self, cmd: dict) -> dict:
        self.commands.append(cmd)
        if cmd.get("tool") == "survey_capture":
            if self.fail:
                return {"frames": [], "labels": [], "revision": None}
            args = cmd.get("args") or {}
            if self.unchanged_at is not None and args.get("if_revision_not") == self.unchanged_at:
                return {"unchanged": True, "revision": self.unchanged_at}
            return {
                "frames": [PNG, PNG, PNG, PNG],
                "labels": ["operator's view", "top-down",
                           "oblique view from the north-east",
                           "oblique view from the south-west"],
                "revision": 3,
            }
        return {"ok": True}

    async def emit_event(self, event: dict) -> None:
        self.events.append(event)


class RecordingProvider:
    """Answers immediately; records the images passed to every generate call."""

    def __init__(self):
        self.image_batches: list[list[bytes] | None] = []
        self.messages_seen: list[list[dict]] = []

    def generate(self, messages, tools, images=None):
        self.image_batches.append(list(images) if images else None)
        self.messages_seen.append([dict(m) for m in messages])
        return ModelResponse(
            text=None,
            tool_calls=[ToolCall("answer", {"text": "Aerial imagery of a settlement."})],
            raw=None,
        )


def make_loop(channel, provider):
    dispatcher = ToolDispatcher(MockBackendExecutor(), channel)
    return AgentLoop(provider, dispatcher, channel, stage="understand")


@pytest.mark.asyncio
async def test_survey_runs_before_first_model_call_and_attaches_frames():
    channel, provider = SurveyChannel(), RecordingProvider()
    loop = make_loop(channel, provider)
    result = await loop.run("what does this scene show?")
    assert result.status == "answered"
    # survey was dispatched before any model call
    assert channel.commands[0]["tool"] == "survey_capture"
    # all four frames attached to the (single) model call
    assert provider.image_batches[0] == [PNG, PNG, PNG, PNG]
    # labels are described to the model in a user turn
    joined = " ".join(str(m.get("content")) for m in provider.messages_seen[0])
    assert "top-down" in joined and "operator's view" in joined
    # survey_out exposed for persistence
    assert loop.survey_out and loop.survey_out["revision"] == 3
    assert len(loop.survey_out["frames"]) == 4


@pytest.mark.asyncio
async def test_frames_attach_to_every_call_not_just_the_first():
    channel = SurveyChannel()

    class TwoTurnProvider(RecordingProvider):
        def generate(self, messages, tools, images=None):
            self.image_batches.append(list(images) if images else None)
            self.messages_seen.append([dict(m) for m in messages])
            if len(self.image_batches) == 1:
                return ModelResponse(text=None,
                                     tool_calls=[ToolCall("narrate", {"text": "Looking."})],
                                     raw=None)
            return ModelResponse(text=None,
                                 tool_calls=[ToolCall("answer", {"text": "A settlement."})],
                                 raw=None)

    provider = TwoTurnProvider()
    loop = make_loop(channel, provider)
    result = await loop.run("how many buildings?")
    assert result.status == "answered"
    assert len(provider.image_batches) == 2
    assert provider.image_batches[0] == [PNG, PNG, PNG, PNG]
    assert provider.image_batches[1] == [PNG, PNG, PNG, PNG]  # re-attached


@pytest.mark.asyncio
async def test_unchanged_revision_reuses_stored_frames_without_reflight():
    channel, provider = SurveyChannel(unchanged_at=3), RecordingProvider()
    loop = make_loop(channel, provider)
    stored = {"frames": [PNG], "labels": ["operator's view"], "revision": 3}
    result = await loop.run("and the roads?", survey=stored)
    assert result.status == "answered"
    assert channel.commands[0]["args"] == {"if_revision_not": 3}
    assert provider.image_batches[0] == [PNG]  # stored frame reused


@pytest.mark.asyncio
async def test_survey_failure_finishes_with_error_not_answer():
    channel, provider = SurveyChannel(fail=True), RecordingProvider()
    loop = make_loop(channel, provider)
    result = await loop.run("what does this scene show?")
    assert result.status == "error"
    assert "survey" in (result.error or "").lower()
    assert provider.image_batches == []  # model never called


@pytest.mark.asyncio
async def test_understand_offers_only_answer_and_narrate():
    from backend.agent.system_prompt import stage_tools
    assert stage_tools("understand") == frozenset({"answer", "narrate"})


@pytest.mark.asyncio
async def test_model_navigation_call_is_rejected_at_backstop():
    channel = SurveyChannel()

    class NavProvider(RecordingProvider):
        def generate(self, messages, tools, images=None):
            self.image_batches.append(list(images) if images else None)
            self.messages_seen.append([dict(m) for m in messages])
            if len(self.image_batches) == 1:
                return ModelResponse(text=None,
                                     tool_calls=[ToolCall("move_camera", {"direction": "forward"})],
                                     raw=None)
            return ModelResponse(text=None,
                                 tool_calls=[ToolCall("answer", {"text": "A settlement."})],
                                 raw=None)

    provider = NavProvider()
    loop = make_loop(channel, provider)
    result = await loop.run("what does this scene show?")
    assert result.status == "answered"
    # the hallucinated navigation call never reached the frontend
    assert all(c.get("tool") != "move_camera" for c in channel.commands)
```

Align the `MockBackendExecutor` import with the actual name in `backend/agent/mocks.py` (open it; use whatever the existing loop tests construct — copy their fixture pattern if they don't use mocks.py directly).

- [ ] **Step 2: Run to verify failures**

Run: `pytest backend/agent/tests/test_survey.py -q`
Expected: FAIL — `run()` has no `survey` kwarg, `stage_tools("understand")` still returns the navigation set, no `survey_out`.

- [ ] **Step 3: Shrink the Understand tool surface + rewrite the prompt**

`backend/agent/system_prompt.py`:

```python
UNDERSTAND_TOOLS: frozenset[str] = frozenset({"narrate", "answer"})
```

Replace `_UNDERSTAND_PROMPT` with:

```python
_UNDERSTAND_PROMPT = """\
You are GeoSplat Inspector's SCENE ANALYST. Before your first turn the app
flew a camera survey of the scene and captured labeled views — the
operator's own view plus framed top-down and oblique views. Those images
are attached to this conversation and they are your ONLY evidence. You do
not navigate: there are no camera tools, and the views you have are the
views there are.

You are in a CONVERSATION: the operator chats with you across many short
runs and you remember the previous ones. The survey images stay available
in every run.

Operating rules:
- SAY WHAT THE IMAGERY IS FIRST: open with modality and setting the way a
  person would — "aerial imagery of a low-density residential area" —
  before any detail.
- ANSWER FROM PIXELS: describe what the views show, the way a person
  describing photos would. Never answer with Gaussian counts or metrics.
- USE ALL THE VIEWS: the same object appears in several views — that is
  ONE object, not several. Count on the best single view for the question
  (usually the top-down) and use the obliques to resolve ambiguities.
- TIER YOUR COUNTS BY CERTAINTY: separate what you can resolve clearly
  from what you can only estimate — "8 clearly visible, roughly 5 more
  partially occluded, about 13 total".
- LOCATE BEFORE YOU CLAIM: never report a condition you cannot point to
  in a named view ("in the top-down view, the north-east building…"). If
  you cannot say where, do not say it.
- ARTIFACTS ARE NOT DAMAGE: holes, smearing, floating fragments and
  missing geometry are RECONSTRUCTION quality problems, not destruction.
  Name them as capture artifacts if they matter; never report them as
  collapse or damage.
- "NOTHING IS WRONG HERE" IS A REAL ANSWER: if what you see is intact,
  say so plainly. Do not manufacture findings to seem thorough.
- If a question cannot be answered from the available views, say exactly
  that and tell the operator to point the camera at the thing and ask
  again — do not guess.
- Use narrate() for short progress remarks; finish with answer(). Every
  response must contain a tool call. answer() ENDS the run — call it only
  with the finished result, formatted as clean markdown.
- The scene is read-only for you. If asked to edit or clean, say the
  operator must switch to the Clean stage.
"""
```

Update the two understand-stage `SKILLS` recipes (`describe_scene`, `count_objects`) to match reality — e.g. `describe_scene` recipe becomes: `"The app has already surveyed the scene. Answer from the attached views: modality and setting first, then contents, then condition — locating anything you claim in a named view."` and `count_objects`: `"Count on the best single view (usually the top-down); use the obliques only to resolve ambiguities you name. Tier the count by certainty."`

- [ ] **Step 4: Implement the survey phase in the loop**

`backend/agent/loop.py` changes:

a. `run()` signature and per-run state:

```python
    async def run(
        self,
        prompt: str,
        history: list[dict] | None = None,
        ledger: GroundingLedger | None = None,
        survey: dict | None = None,
    ) -> LoopResult:
```

In the per-run reset block add:

```python
        self._survey_frames: list[bytes] = []
        self.survey_out: dict | None = None
```

b. After `await self._seed_grounding()`:

```python
        if self.stage == "understand":
            if not await self._run_survey(survey):
                return self._result  # finished with an error already
```

c. The provider call — replace the `images` argument:

```python
                response = await asyncio.to_thread(
                    self.provider.generate,
                    self._messages,
                    self.tools,
                    ([*self._survey_frames, *self._pending_frames] or None),
                )
```

d. New method (place after `_seed_grounding`):

```python
    # -- app-owned survey (Understand stage; spec 2026-08-03) ---------------
    async def _run_survey(self, stored: dict | None) -> bool:
        """Dispatch survey_capture app-side and attach the frames for the
        whole run. Returns False after finishing the run with an error."""
        args: dict = {}
        if stored and stored.get("revision") is not None and stored.get("frames"):
            args["if_revision_not"] = stored["revision"]
        await self._emit(ev_tool_call("survey_capture", args, 0))
        result = await self.dispatcher.dispatch(ToolCall("survey_capture", args))
        payload = result.get("result") if isinstance(result.get("result"), dict) else {}
        frames = result.get("frames") or []

        if result.get("ok") and payload.get("unchanged") and stored:
            frames = list(stored["frames"])
            labels = [str(x) for x in (stored.get("labels") or [])]
            revision = stored.get("revision")
        elif result.get("ok") and frames:
            labels = [str(x) for x in (payload.get("labels") or [])]
            revision = payload.get("revision")
        elif stored and stored.get("frames"):
            # Re-survey failed (viewer busy/gone) but we still hold an older
            # survey of this scene — answer from it rather than dying.
            frames = list(stored["frames"])
            labels = [str(x) for x in (stored.get("labels") or [])]
            revision = stored.get("revision")
        else:
            await self._emit(ev_tool_result("survey_capture", result, 0))
            await self._finish_error(
                "error",
                "survey failed: could not capture the scene — check that a "
                "scene is loaded and the viewer is connected, then ask again.",
            )
            return False

        await self._emit(ev_tool_result("survey_capture", {"n_frames": len(frames)}, 0))
        self._survey_frames = frames
        self.survey_out = {"frames": frames, "labels": labels, "revision": revision}
        self._frames_this_run = len(frames)   # satisfies the look-before-assert gate
        self._ledger.record_frame()
        lines = [
            f"View {i + 1}: {labels[i] if i < len(labels) else 'additional view'}"
            for i in range(len(frames))
        ]
        self._nudge_sync(
            "the app surveyed the scene; the attached images are, in order: "
            + "; ".join(lines)
            + ". Answer the operator's question from these views."
        )
        return True
```

Note `ev_tool_call`/`ev_tool_result` with `step=0` — the survey shows up in the trace panel before step 1, so the operator sees the flight is agent-run activity.

- [ ] **Step 5: Run the new tests and the whole backend suite**

Run: `pytest backend/agent/tests/test_survey.py -v` → all PASS.
Run: `pytest backend/agent -q` → pre-existing understand-stage tests in `test_analyst_prompt.py` that assert navigation tooling will now FAIL — update them to the new reality (understand tool surface is `{answer, narrate}`, prompt contains "SAY WHAT THE IMAGERY IS FIRST" and "your ONLY evidence", no capture instructions). Delete assertions that no longer apply rather than contorting them; keep the artifacts-not-damage and tiered-count assertions, which still hold.
Expected after updates: full `pytest backend` PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/agent/system_prompt.py backend/agent/loop.py backend/agent/tests/test_survey.py backend/agent/tests/test_analyst_prompt.py
git commit -m "feat(agent): survey-first analyst — app flies the camera, model only answers"
```

---

### Task 5: Persist the survey across the conversation

**Files:**
- Modify: `backend/api/real_engine.py:58-70` (`RealScene.__init__`) and `:203-236` (`RealAgentRunner.run`)
- Test: `backend/api/tests/test_survey_persistence.py` (new file)

**Interfaces:**
- Consumes: `AgentLoop.run(..., survey=...)` + `loop.survey_out` (Task 4).
- Produces: `RealScene.survey_store: dict | None` carried between runs of the same scene.

- [ ] **Step 1: Write the failing test**

Create `backend/api/tests/test_survey_persistence.py`:

```python
"""Survey frames persist on the scene between Understand runs."""
from __future__ import annotations

import pytest

from backend.api.real_engine import RealAgentRunner


class FakeLoop:
    def __init__(self, *args, **kwargs):
        self.survey_out = {"frames": [b"png"], "labels": ["operator's view"], "revision": 5}
        self.captured_survey = None

    async def run(self, prompt, history=None, ledger=None, survey=None):
        self.captured_survey = survey
        from backend.agent.types import LoopResult
        return LoopResult(status="answered", answer="ok")

    def transcript(self):
        return []

    @property
    def ledger(self):
        return None


@pytest.mark.asyncio
async def test_survey_store_round_trips(monkeypatch):
    import backend.agent as agent_pkg

    created: list[FakeLoop] = []

    def fake_loop(*args, **kwargs):
        loop = FakeLoop()
        created.append(loop)
        return loop

    monkeypatch.setattr(agent_pkg, "AgentLoop", fake_loop)

    class Scene:  # minimal RealScene stand-in
        chat_history: list = []
        agent_ledger = None
        survey_store = None

    scene = Scene()
    runner = RealAgentRunner()

    class Channel:
        async def send_command(self, cmd):
            return {}
        async def emit_event(self, event):
            pass

    # Provider construction needs settings — monkeypatch get_provider to a stub.
    import backend.providers as providers_pkg
    monkeypatch.setattr(providers_pkg, "get_provider", lambda *a, **k: object())

    await runner.run("what does this show?", scene, Channel(), stage="understand")
    assert scene.survey_store == {"frames": [b"png"], "labels": ["operator's view"], "revision": 5}

    await runner.run("how many?", scene, Channel(), stage="understand")
    assert created[1].captured_survey == scene.survey_store
```

If `RealAgentRunner.run` imports `AgentLoop` from `backend.agent` inside the function (it does — lazy import), the monkeypatch target above is correct. If settings resolution (`get_store().resolve()`) needs env, monkeypatch `backend.api.settings.get_store` with a stub returning an object whose `.resolve()` yields a namespace with `provider/model/api_key/base_url` attributes — copy the pattern from existing `backend/api/tests` that exercise `RealAgentRunner`, if one exists; otherwise use `types.SimpleNamespace`.

- [ ] **Step 2: Run to verify it fails**

Run: `pytest backend/api/tests/test_survey_persistence.py -q`
Expected: FAIL — `RealScene`/runner don't know `survey_store` / don't pass `survey=`.

- [ ] **Step 3: Implement**

`backend/api/real_engine.py` — in `RealScene.__init__` (next to `chat_history` / `agent_ledger`):

```python
        # Understand-stage survey (spec 2026-08-03): frames + labels +
        # scene revision from the last app-flown survey, reused across runs
        # until the revision changes.
        self.survey_store: dict | None = None
```

In `RealAgentRunner.run`, thread it through:

```python
        try:
            await loop.run(
                prompt,
                history=history,
                ledger=getattr(scene, "agent_ledger", None),
                survey=getattr(scene, "survey_store", None) if resolved == "understand" else None,
            )
        finally:
            if history is not None:
                history[:] = loop.transcript()[-_CHAT_HISTORY_LIMIT:]
            if hasattr(scene, "agent_ledger"):
                scene.agent_ledger = loop.ledger
            if resolved == "understand" and getattr(loop, "survey_out", None) is not None:
                scene.survey_store = loop.survey_out
```

- [ ] **Step 4: Run tests**

Run: `pytest backend/api/tests/test_survey_persistence.py -q` → PASS. `pytest backend -q` → full suite PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/api/real_engine.py backend/api/tests/test_survey_persistence.py
git commit -m "feat(api): persist analyst survey frames per scene conversation"
```

---

### Task 6: Live end-to-end check (manual, demo rehearsal)

**Files:** none (manual QA against the running stack).

- [ ] **Step 1: Bring the stack up**

Run: `./scripts/local-model.sh status` (32B must be READY on :8001), then `./scripts/dev.sh`. Open `http://localhost:5173/#/analyze`.

- [ ] **Step 2: The exact failure scenario from 2026-08-03**

Load the Iona Park scene, crop/keep-only in the editor, switch to Understand, put the camera at a close-in angle (inside the scene), and ask: *"what does this scene show?"*
Expected: the camera visibly flies operator-view → top-down → two obliques (~3 s), then a markdown answer describing the settlement. **No reframe loops, no "the scene is not visible."**

- [ ] **Step 3: Follow-up + revision invalidation**

Ask *"how many buildings do you see?"* — expected: no new flight (revision unchanged), answer arrives faster, count is tiered by certainty. Then delete a few splats in Clean, return to Understand, ask again — expected: the camera re-flies the survey (revision bumped) before answering.

- [ ] **Step 4: Failure honesty**

Ask a question the views cannot answer (e.g. "what color is the smallest car's interior?") — expected: the agent says it cannot tell from the available views and invites the operator to point the camera, rather than guessing.

- [ ] **Step 5: Record results**

Note pass/fail per step in the PR description (or hand to Codex review). Bring the model server down afterwards: `./scripts/local-model.sh down`.
