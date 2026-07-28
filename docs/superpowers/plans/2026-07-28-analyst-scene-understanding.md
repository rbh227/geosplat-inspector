# Analyst Scene Understanding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the agent reliable scene understanding — say what aerial imagery
shows and count structures honestly — in a separate look-only analyst window
that works on the scene the editor has already cleaned.

**Architecture:** Three independent pieces. (1) `POST /scene` stops computing
k-NN metrics, which currently freezes the viewer for minutes on every load.
(2) The Understand-stage prompt stops instructing multi-angle counting — which
cannot work, because captured frames do not survive across model turns — and
instead counts from one well-framed capture with certainty tiers. (3) A
hash-routed analyst page at `#/analyze?scene=<id>` loads the current alive set
by scene id, sharing scene and agent wiring with the editor through two
extracted hooks.

**Tech Stack:** FastAPI + Pydantic + pytest (backend); React 19 + TypeScript +
Vite + Vitest (frontend); SparkJS/Three for rendering.

**Spec:** `docs/superpowers/specs/2026-07-28-analyst-scene-understanding-design.md`

## Global Constraints

- **Contracts are mirrored.** Any change to `backend/contracts/` or
  `backend/api/schemas.py` shapes must be mirrored in
  `frontend/src/contracts.ts`. Drift guards: `backend/contracts/tests/test_tools.py`
  and `frontend/src/agent/contracts.test.ts`.
- **No new npm dependencies.** Routing is hash-based specifically to avoid
  adding react-router.
- **The Understand stage stays look-only.** Never add editing, selection,
  history, export, or teleport tools (`look_at`, `set_view`, `orbit`,
  `frame_object`, `reset_view`, `capture_orbit`) to `UNDERSTAND_TOOLS`.
- **No hardcoded domain.** Prompt text must not mention disasters, trailers,
  or any expectation about what scenes contain. It teaches how to look.
- **Gate before every commit:** `.venv-api/bin/python -m pytest -q` (backend),
  `npm test` (frontend), `npx tsc --noEmit`, `npm run lint`. Backend baseline
  is 236 passing; frontend baseline is 202 passing across 17 files.
- **Python is `.venv-api/bin/python`** (3.14 in this venv; `pytest` alone is
  not on PATH).

---

### Task 1: Stop computing metrics on upload

`POST /scene` runs full k-NN metrics over every splat on every upload
(`backend/api/routes.py:102`, whose own comment says "minutes on a 2M-splat
scene"). It saturates CPU cores while SparkJS sorts splats on the CPU, so the
viewer renders and then freezes for minutes. The analyst never uses these
metrics. `GET /metrics` already computes them on demand.

**Files:**
- Modify: `backend/api/schemas.py:14-16`
- Modify: `backend/api/routes.py:85-105`
- Modify: `backend/api/tests/test_rest.py:35-56`
- Modify: `src/backend/client.ts:19-22`, `src/backend/client.ts:44-54`
- Modify: `frontend/src/contracts.ts:121`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `UploadResponse{id: str, count: int}` (backend),
  `UploadResult{id: string, count: number}` (frontend).

- [ ] **Step 1: Write the failing test**

Replace the first block of `test_upload_metrics_edit_fetch_roundtrip` in
`backend/api/tests/test_rest.py` and add a new test above it:

```python
def test_upload_returns_count_without_computing_metrics(client, monkeypatch):
    """Upload must not run k-NN metrics — it freezes the viewer for minutes on
    a large scene, and nothing in the upload path needs them.

    Enforced by sabotage: Scene.metrics raises, so any call from the upload
    path fails the test rather than merely slowing it down."""
    from backend.api.engine import Scene

    def _boom(self, *a, **kw):
        raise AssertionError("upload computed metrics — it must not")

    monkeypatch.setattr(Scene, "metrics", _boom)

    with open(MESSY, "rb") as f:
        resp = client.post("/scene", files={"file": ("messy.ply", f, "application/octet-stream")})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] > 0
    assert "metrics" not in body, "upload must not carry metrics"
```

If `Scene.metrics` is not the attribute name on the engine wrapper, check
`backend/api/engine.py` and patch whatever `routes.py:102` actually calls.

Then change the roundtrip test's step 1 so it no longer reads `body["metrics"]`:

```python
def test_upload_metrics_edit_fetch_roundtrip(client):
    assert os.path.exists(MESSY), "examples/messy.ply (Phase 0) is required"

    # 1. upload -> id + count (metrics are computed on demand, not here)
    with open(MESSY, "rb") as f:
        resp = client.post("/scene", files={"file": ("messy.ply", f, "application/octet-stream")})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    scene_id = body["id"]
    assert body["count"] > 0

    # 2. metrics endpoint computes them on demand
    r = client.get("/metrics", params={"scene_id": scene_id})
    assert r.status_code == 200
    m0 = r.json()
    assert m0["gaussianCount"] == body["count"]
    for key in ("opacity", "scale", "spatial", "bounds", "color", "computedAt"):
        assert key in m0
    assert "needleFraction" in m0["scale"]["axisRatio"]
```

Leave the rest of the roundtrip test (steps 3 onward) unchanged — it already
references `m0["gaussianCount"]`, which now comes from `GET /metrics`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv-api/bin/python -m pytest backend/api/tests/test_rest.py -q`
Expected: FAIL — `assert "metrics" not in body` fails because upload still
returns metrics, and `body["count"]` raises `KeyError`.

- [ ] **Step 3: Change the response schema**

In `backend/api/schemas.py`, replace lines 14-16:

```python
class UploadResponse(BaseModel):
    id: str
    count: int
```

- [ ] **Step 4: Stop computing metrics in the handler**

In `backend/api/routes.py`, replace the tail of `upload_scene` (the lines from
the `# Threaded (as is every metrics/edit call...` comment through the
`return`) with:

```python
        # Metrics are NOT computed here: the k-NN pass takes minutes on a
        # 2M-splat scene and saturates the cores SparkJS needs for its
        # CPU-side sort, so the viewer renders and then freezes. Nothing in
        # the upload path needs them — `GET /metrics` computes on demand.
        return UploadResponse(id=state.id, count=state.scene.count())
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv-api/bin/python -m pytest backend/api/tests/test_rest.py -q`
Expected: PASS.

- [ ] **Step 6: Mirror the contract on the frontend**

In `src/backend/client.ts`, replace the `UploadResult` interface (lines 19-22):

```typescript
export interface UploadResult {
  id: string
  count: number
}
```

and update the doc comment above `uploadScene` (line 44):

```typescript
/** POST /scene — upload a .ply, returns its id + alive count. Metrics are NOT
 *  computed here (they cost minutes on a large scene); use getMetrics(). */
```

In `frontend/src/contracts.ts`, update line 121:

```typescript
  /** POST — upload .ply, returns { id, count } */
```

No call-site changes are needed: the only caller, `registerScene` in
`src/App.tsx:315`, destructures `{ id }` and ignores the rest.

- [ ] **Step 7: Run the full gate**

Run each and confirm:
- `.venv-api/bin/python -m pytest -q` → 237 passed (236 baseline + 1 new)
- `npm test` → 202 passed
- `npx tsc --noEmit` → no output
- `npm run lint` → 0 errors

- [ ] **Step 8: Commit**

```bash
git add backend/api/schemas.py backend/api/routes.py backend/api/tests/test_rest.py \
        src/backend/client.ts frontend/src/contracts.ts
git commit -m "fix(api): upload returns a count, not a minutes-long metrics pass"
```

---

### Task 2: Rewrite the analyst prompt to count from one frame

The current prompt instructs: *"For 'how many X' questions: capture 3-4 views
from different angles, count what is visible, and answer with the count."*
That cannot work. `backend/agent/loop.py` clears `_pending_frames` after every
model call and `backend/providers/openai.py` attaches images to the last user
turn only, so the model never holds two views at once. It sees view 1, writes
"4 houses," then sees the same houses from a new angle with no image of view 1
to compare against — it can only add.

**Files:**
- Modify: `backend/agent/system_prompt.py` — `_UNDERSTAND_PROMPT`, and the
  `survey_scene`, `describe_scene`, `count_objects` entries in `SKILLS`
- Modify: `backend/agent/tests/test_analyst_prompt.py`

**Interfaces:**
- Consumes: nothing.
- Produces: no new symbols — `system_prompt_for("understand")` and
  `skills_for("understand")` keep their signatures.

- [ ] **Step 1: Write the failing tests**

Append to `backend/agent/tests/test_analyst_prompt.py`:

```python
from backend.agent.system_prompt import skills_for


def _understand() -> str:
    return system_prompt_for("understand").lower()


def test_prompt_does_not_instruct_multi_angle_counting():
    """Frames do not survive across model turns (loop.py clears _pending_frames
    and the provider attaches images to the last user turn only), so counting
    across viewpoints can only double-count."""
    p = _understand()
    assert "3-4 views" not in p
    assert "different angles" not in p
    recipes = " ".join(s["recipe"] for s in skills_for("understand")).lower()
    assert "3-4 views" not in recipes
    assert "different angles" not in recipes


def test_prompt_states_the_one_frame_counting_rule():
    p = _understand()
    assert "double-count" in p
    assert "never extend" in p


def test_prompt_requires_tiered_certainty_and_modality():
    p = _understand()
    assert "tier" in p
    assert "aerial" in p  # only as a worked EXAMPLE of naming modality


def test_prompt_forbids_unlocatable_and_artifact_damage_claims():
    p = _understand()
    assert "cannot say where" in p
    assert "artifact" in p
    assert "reconstruction" in p


def test_prompt_makes_no_damage_a_valid_answer():
    p = _understand()
    assert "nothing is wrong here" in p


def test_prompt_carries_no_domain_priors():
    """The prompt teaches HOW to look, never what these scenes contain."""
    p = _understand()
    for word in ("disaster", "trailer", "hurricane", "earthquake", "flood"):
        assert word not in p, f"domain prior leaked into the prompt: {word}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv-api/bin/python -m pytest backend/agent/tests/test_analyst_prompt.py -q`
Expected: FAIL — `"3-4 views" not in p` fails (the string is in the prompt
today), and the one-frame/tiering/artifact assertions fail because that text
does not exist yet.

- [ ] **Step 3: Rewrite `_UNDERSTAND_PROMPT`**

In `backend/agent/system_prompt.py`, replace the whole `_UNDERSTAND_PROMPT`
string with:

```python
_UNDERSTAND_PROMPT = """\
You are GeoSplat Inspector's SCENE ANALYST. Your job is to LOOK and DESCRIBE:
move the camera, capture views, and answer questions about what is VISIBLE in
the scene — objects, layout, condition, setting. You have NO editing tools and
you never discuss cleanup unless asked about quality.

You are in a CONVERSATION: the operator chats with you across many short runs
and you remember the previous ones. Match your effort to the question — a
simple question deserves one capture and a direct answer. If the question is
ambiguous, ask ONE short question with answer(text=...) and stop — the
operator's reply arrives as the next message.

Operating rules:
- NAVIGATION (buttons only): you START at the operator's current view — the
  zoom and angle they chose. You have NO teleport and cannot jump to a
  coordinate. Move and look with the buttons: move_camera (forward/back/
  left/right/up/down), turn (look — left/right yaw, up/down pitch), dolly
  (zoom). If you get lost or the view goes empty, call `reframe` to return to
  the operator's starting view, then continue from there.
- FRAME BEFORE YOU COUNT: capture once and read the percept that comes back.
  If `in_view` is false the scene is off-screen or behind you — coverage means
  nothing then; turn toward the scene first. If `coverage` is above 0.75 you
  are too close to see the whole site: dolly back. Below 0.3: dolly in. Aim
  for 0.45-0.75, where the site fills most of the frame with nothing cut off.
  Nudge and re-check; don't guess big jumps.
- COUNT FROM ONE FRAME: your count comes from a SINGLE well-framed capture.
  Moving to a new viewpoint and counting again will DOUBLE-COUNT — the same
  objects seen from another angle look like new ones, and you cannot see the
  earlier frame any more to compare. You may move to resolve one specific
  ambiguity you name out loud ("is that one long building or two?"), and that
  may CORRECT your count. It may NEVER EXTEND it.
- TIER YOUR COUNT BY CERTAINTY: separate what you can resolve clearly from
  what you can only estimate — "8 clearly in the foreground, roughly 5 more
  further back, about 13 in total". One confident number you cannot support is
  worse than an honest tiered estimate.
- SAY WHAT THE IMAGERY IS FIRST: open with modality and setting the way a
  person would — for example "aerial imagery of a low-density residential
  area" — before any count.
- LOCATE BEFORE YOU CLAIM: never report a condition you cannot point to.
  "Some structures are damaged" is not an observation; "the roof on the
  northeast building is missing" is. If you CANNOT SAY WHERE, do not say it.
- ARTIFACTS ARE NOT DAMAGE: holes, smearing, floating fragments and missing
  geometry are RECONSTRUCTION quality problems, not destruction. Name them as
  capture artifacts if they matter. NEVER report them as collapse or damage.
- "NOTHING IS WRONG HERE" IS A REAL ANSWER: if what you see is intact, say so
  plainly. Do not manufacture findings to seem thorough.
- ANSWER FROM PIXELS: your evidence is the frames you captured. Never answer a
  content question with Gaussian counts or metrics — say what the scene shows,
  the way a person describing a photo would.
- NARRATE briefly as you move so the human watching can follow.
- NARRATION IS NOT ACTION: describing a move does nothing — the camera only
  moves when you CALL the tool. Every response must contain a tool call; when
  you are done looking, call `answer`.
- answer() ENDS the run. Call it ONLY with the finished result — never with
  what you are about to do ("Let me capture…" is narrate(), not answer()).
- The scene is read-only for you. If asked to edit or clean, say the operator
  must switch to the Clean stage — do not attempt it.
"""
```

- [ ] **Step 4: Rewrite the three skill recipes**

In the `SKILLS` list in the same file, replace the `recipe` values for these
three entries, leaving `name`, `stage`, and `description` untouched except
where shown:

```python
    {
        "name": "survey_scene",
        "stage": "both",
        "description": "Look around the scene from where you are and get oriented.",
        "recipe": "From the operator's current view, alternate move_camera and turn to sweep; capture_frame every couple of moves; narrate what you see. Use this to get ORIENTED, never to count — counts come from one framed capture (see count_objects).",
    },
```

```python
    {
        "name": "describe_scene",
        "stage": "understand",
        "description": "Say what is visibly in the scene.",
        "recipe": "Frame the site in one capture (in_view true, coverage 0.45-0.75), then answer: what the imagery is (modality and setting) first, then what is in it, then its condition — locating anything you claim. Never Gaussian statistics.",
    },
```

```python
    {
        "name": "count_objects",
        "stage": "understand",
        "description": "Count visible things (buildings, cars, ...) from one framed view.",
        "recipe": "Frame the whole site in ONE capture (in_view true, coverage 0.45-0.75), count from that single frame, and answer with tiered certainty — what you resolve clearly vs what you can only estimate. Do NOT capture extra viewpoints to add to the count; that double-counts.",
    },
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv-api/bin/python -m pytest backend/agent/tests/test_analyst_prompt.py -q`
Expected: PASS (all tests, including the pre-existing structural ones).

- [ ] **Step 6: Run the full backend suite**

Run: `.venv-api/bin/python -m pytest -q`
Expected: all pass. If a test asserts on old prompt wording, update it to the
new text — do not weaken the new assertions.

- [ ] **Step 7: Commit**

```bash
git add backend/agent/system_prompt.py backend/agent/tests/test_analyst_prompt.py
git commit -m "feat(agent): analyst counts from one frame with tiered certainty"
```

---

### Task 3: Hash routing module

Two pages need URLs. A path route would require react-router plus SPA-fallback
config on the dev server and any static host; a hash route needs neither.

**Files:**
- Create: `src/routing.ts`
- Create: `src/routing.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `type Route = { page: 'editor'; sceneId: null } | { page: 'analyst'; sceneId: string | null }`
  - `parseRoute(hash: string): Route`
  - `analystHref(sceneId: string): string`
  - `useRoute(): Route` — React hook, re-renders on `hashchange`

- [ ] **Step 1: Write the failing test**

Create `src/routing.test.ts`:

```typescript
import { describe, it, expect } from 'vitest'
import { parseRoute, analystHref } from './routing'

describe('parseRoute', () => {
  it('defaults to the editor for an empty hash', () => {
    expect(parseRoute('')).toEqual({ page: 'editor', sceneId: null })
  })

  it('defaults to the editor for an unknown hash', () => {
    expect(parseRoute('#/nonsense')).toEqual({ page: 'editor', sceneId: null })
  })

  it('routes #/analyze with a scene id', () => {
    expect(parseRoute('#/analyze?scene=abc123')).toEqual({
      page: 'analyst', sceneId: 'abc123',
    })
  })

  it('routes #/analyze with no scene id', () => {
    expect(parseRoute('#/analyze')).toEqual({ page: 'analyst', sceneId: null })
  })

  it('treats an empty scene param as absent', () => {
    expect(parseRoute('#/analyze?scene=')).toEqual({ page: 'analyst', sceneId: null })
  })
})

describe('analystHref', () => {
  it('builds a hash href', () => {
    expect(analystHref('abc123')).toBe('#/analyze?scene=abc123')
  })

  it('encodes ids that need it', () => {
    expect(analystHref('a b')).toBe('#/analyze?scene=a%20b')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/routing.test.ts`
Expected: FAIL — "Failed to resolve import './routing'".

- [ ] **Step 3: Write the implementation**

Create `src/routing.ts`:

```typescript
/**
 * Hash routing for the two pages (editor, analyst).
 *
 * Hash rather than path on purpose: a path route needs react-router plus
 * SPA-fallback config on the dev server and on any static host. This needs
 * neither, and swapping in a real router later is mechanical.
 */
import { useEffect, useState } from 'react'

export type Route =
  | { page: 'editor'; sceneId: null }
  | { page: 'analyst'; sceneId: string | null }

const EDITOR: Route = { page: 'editor', sceneId: null }

export function parseRoute(hash: string): Route {
  const [path, query] = hash.replace(/^#/, '').split('?')
  if (path !== '/analyze') return EDITOR
  const scene = new URLSearchParams(query ?? '').get('scene')
  return { page: 'analyst', sceneId: scene || null }
}

/** Href for the analyst window on a given backend scene. */
export function analystHref(sceneId: string): string {
  return `#/analyze?scene=${encodeURIComponent(sceneId)}`
}

/** Current route, re-evaluated on every hashchange. */
export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.hash))
  useEffect(() => {
    const onChange = () => setRoute(parseRoute(window.location.hash))
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return route
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/routing.test.ts`
Expected: PASS, 7 tests.

- [ ] **Step 5: Commit**

```bash
git add src/routing.ts src/routing.test.ts
git commit -m "feat(routing): hash routes for the editor and analyst pages"
```

---

### Task 4: Move the editor into its own page component

`src/App.tsx` is 981 lines wiring the editor, the agent, persistence, and
history. A second page cannot be added to it. This task is a **pure move** —
no behavior changes — so that later tasks refactor a file that is already in
its final home.

**Files:**
- Create: `src/pages/EditorPage.tsx` (receives all of today's `App.tsx` body)
- Modify: `src/App.tsx` (becomes a thin router shell)

**Interfaces:**
- Consumes: `useRoute` from Task 3.
- Produces: `EditorPage` — a default-exported component taking no props.

- [ ] **Step 1: Move the file**

```bash
mkdir -p src/pages
git mv src/App.tsx src/pages/EditorPage.tsx
```

- [ ] **Step 2: Rename the component and fix relative imports**

In `src/pages/EditorPage.tsx`:

- Change `export default function App() {` to
  `export default function EditorPage() {`
- Every relative import that starts with `./` now needs `../`. The imports to
  change are on lines 3-4 and 8-28 of the original file: `./types/viewer`,
  `./types/agent`, `./backend/client`, `./backend/bridge`, `./backend/trace`,
  `./persistence`, `./viewer/ViewerCanvas`, `./viewer/SelectionOverlay`,
  `./ui/ViewerErrorBoundary`, `./ui/TopBar`, `./ui/NarrationBar`,
  `./ui/ChatPanel`, `./ui/SettingsPanel`, `./ui/EditorToolbar`, `./ui/MovePad`,
  `./ui/RotatePad`, `./ui/EmptyState`, `./demos`.
- Leave `@agent` alone — it is an alias, not relative.

- [ ] **Step 3: Write the new App shell**

Create `src/App.tsx`:

```typescript
import { useRoute } from './routing'
import EditorPage from './pages/EditorPage'

export default function App() {
  const route = useRoute()
  if (route.page === 'analyst') {
    // Analyst page lands in Task 7; until then the route falls back so the
    // build never references a component that does not exist yet.
    return <EditorPage />
  }
  return <EditorPage />
}
```

- [ ] **Step 4: Verify nothing changed behaviorally**

Run each and confirm:
- `npx tsc --noEmit` → no output
- `npm test` → 209 passed (202 baseline + 7 from Task 3)
- `npm run lint` → 0 errors

- [ ] **Step 5: Commit**

```bash
git add src/App.tsx src/pages/EditorPage.tsx
git commit -m "refactor(app): move the editor into its own page behind a router shell"
```

---

### Task 5: Extract the scene session hook

The analyst needs scene loading, backend registration, persistence, and ID
adoption — all of which live inside `EditorPage`. Extract them so both pages
share one implementation instead of duplicating ~200 lines.

**Files:**
- Create: `src/session/useSceneSession.ts`
- Create: `src/session/useSceneSession.test.ts`
- Modify: `src/pages/EditorPage.tsx`

**Interfaces:**
- Consumes: `UploadResult{id, count}` from Task 1.
- Produces:

```typescript
export interface SceneSession {
  viewerRef: React.RefObject<ViewerHandle | null>
  hasScene: boolean
  viewerState: ViewerState
  backendSceneId: string | null
  baselineCount: number
  status: string | null
  showStatus: (text: string) => void
  setViewerState: (s: ViewerState) => void
  /** Load a local File: render it, then register it with the backend. */
  loadFile: (file: File) => void
  /** Load an already-registered backend scene by id (the analyst's entry). */
  loadBackendScene: (sceneId: string) => Promise<void>
  /** Re-fetch the authoritative scene + ids after a backend-side edit. */
  reloadAuthoritative: (sceneId: string) => Promise<void>
  sceneIdRef: React.RefObject<string | null>
  lastPlyFileRef: React.RefObject<File | null>
  localOnlyEditsRef: React.RefObject<boolean>
  registeringSceneRef: React.RefObject<boolean>
}

export function useSceneSession(): SceneSession
```

- [ ] **Step 1: Write the failing test**

Create `src/session/useSceneSession.test.ts`. This tests the one piece with
real branching logic — `loadBackendScene`'s missing-scene path — without
mounting a renderer:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../backend/client', () => ({
  getAliveIds: vi.fn(),
  scenePlyUrl: (id: string) => `/scene/${id}.ply`,
  uploadScene: vi.fn(),
  isBackendLoadable: (n: string) => n.toLowerCase().endsWith('.ply'),
}))

import { getAliveIds } from '../backend/client'
import { probeBackendScene } from './useSceneSession'

describe('probeBackendScene', () => {
  beforeEach(() => vi.mocked(getAliveIds).mockReset())

  it('reports present when the backend still holds the scene', async () => {
    vi.mocked(getAliveIds).mockResolvedValue([1, 2, 3])
    await expect(probeBackendScene('abc')).resolves.toEqual({ present: true, ids: [1, 2, 3] })
  })

  it('reports absent when the scene 404s', async () => {
    vi.mocked(getAliveIds).mockRejectedValue(new Error('ids fetch failed (404): not found'))
    await expect(probeBackendScene('abc')).resolves.toEqual({ present: false, ids: null })
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/session/useSceneSession.test.ts`
Expected: FAIL — "Failed to resolve import './useSceneSession'".

- [ ] **Step 3: Create the hook module with the probe helper**

Create `src/session/useSceneSession.ts`. Start with the exported helper the
test needs:

```typescript
import { getAliveIds } from '../backend/client'

/** Does the backend still hold this scene? Scenes are in-memory only, so a
 *  restarted backend loses them while a browser tab still holds the id. */
export async function probeBackendScene(
  sceneId: string,
): Promise<{ present: boolean; ids: number[] | null }> {
  try {
    const ids = await getAliveIds(sceneId)
    return { present: true, ids }
  } catch {
    return { present: false, ids: null }
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/session/useSceneSession.test.ts`
Expected: PASS, 2 tests.

- [ ] **Step 5: Move the scene wiring into the hook**

Still in `src/session/useSceneSession.ts`, add `useSceneSession` and move these
members out of `src/pages/EditorPage.tsx` verbatim, changing only their
relative import prefixes (`./x` → `../x`):

State: `viewerRef`, `fileInputRef` stays in the page, `viewerState`,
`hasScene`, `backendSceneId`, `baselineCount`, `status`, `statusTimer`.

Refs: `sceneIdRef`, `hasSceneRef`, `loadGenRef`, `registeringSceneRef`,
`lastPlyFileRef`, `localOnlyEditsRef`.

Callbacks: `showStatus`, `registerScene`, `reloadAuthoritative`, `loadFile`,
`reportLoadError`, and the persistence effects (mount restore, `pagehide`
camera persist).

Return the `SceneSession` shape from the Interfaces block above. Add
`loadBackendScene`, which is new — the analyst's entry point:

```typescript
  /** Load an already-registered backend scene by id. Adopts the backend's ID
   *  space so the two agree after any prior edit. Throws if the scene is gone
   *  so the caller can render its missing-scene state. */
  const loadBackendScene = useCallback(async (sceneId: string) => {
    const gen = ++loadGenRef.current
    const probe = await probeBackendScene(sceneId)
    if (!probe.present) {
      sceneIdRef.current = null
      setBackendSceneId(null)
      setHasScene(false)
      throw new Error(`scene ${sceneId} is no longer loaded`)
    }
    setHasScene(true)
    await viewerRef.current?.loadSplat(scenePlyUrl(sceneId))
    if (gen !== loadGenRef.current) return // a newer load won
    if (probe.ids) viewerRef.current?.adoptIds(probe.ids)
    sceneIdRef.current = sceneId
    setBackendSceneId(sceneId)
    setBaselineCount(viewerRef.current?.getSplatCount() ?? 0)
  }, [])
```

Check the existing `reloadAuthoritative` (around `src/pages/EditorPage.tsx:287`)
for the exact ID-adoption call it uses and match it — if it is not
`adoptIds`, use whatever name the `ViewerHandle` actually exposes.

- [ ] **Step 6: Consume the hook from EditorPage**

In `src/pages/EditorPage.tsx`, replace the moved declarations with:

```typescript
  const scene = useSceneSession()
```

and update every reference to the moved members to read through `scene.`
(e.g. `viewerRef` → `scene.viewerRef`, `showStatus(...)` →
`scene.showStatus(...)`). Leave all editor-only state — `stage`,
`activeTool`, `eraseMode`, `selectionCount`, `cropBoxCount`, `hasCropBox`,
`cropCommitPendingRef`, `settingsOpen`, `modelConfig`, `settingsAttention` —
in the page.

- [ ] **Step 7: Verify no behavior changed**

Run each and confirm:
- `npx tsc --noEmit` → no output
- `npm test` → 211 passed (209 + 2 new)
- `npm run lint` → 0 errors

- [ ] **Step 8: Commit**

```bash
git add src/session/useSceneSession.ts src/session/useSceneSession.test.ts src/pages/EditorPage.tsx
git commit -m "refactor(session): extract the scene session hook for both pages"
```

---

### Task 6: Extract the agent session hook

The analyst needs chat, narration, send/stop, and pause/resume. It does not
need proposals — those are Clean-stage only — so proposals stay an optional
callback the editor supplies.

**Files:**
- Create: `src/session/useAgentSession.ts`
- Modify: `src/pages/EditorPage.tsx`

**Interfaces:**
- Consumes: `SceneSession` from Task 5.
- Produces:

```typescript
export interface AgentSessionOptions {
  scene: SceneSession
  stage: Stage
  /** Clean-stage only; omit in the analyst. */
  onProposal?: (p: ProposalState | null) => void
}

export interface AgentSession {
  messages: ChatMessage[]
  isThinking: boolean
  narration: string
  agentPaused: boolean
  send: (text: string) => void
  stop: () => void
  resume: () => void
  /** Call on any manual camera/tool input so a run pauses at the next
   *  tool-call boundary. */
  onManualInput: () => void
  disposeAgent: () => void
}

export function useAgentSession(opts: AgentSessionOptions): AgentSession
```

- [ ] **Step 1: Move the agent wiring into the hook**

Create `src/session/useAgentSession.ts` and move these out of
`src/pages/EditorPage.tsx` verbatim, changing only relative import prefixes:

State: `messages`, `isThinking`, `narration`, `agentPaused`.

Refs: `agentRef`, `transportRef`, `panelsRef`, `unsubsRef`,
`processedTraceRef`, `runActionsRef`, `stageRef`, `proposalPendingRef`.

Callbacks: `ensureAgent`, `disposeAgent`, `handleSend`, `handleStopAgent`,
`handleResumeAgent`, `handleManualInput`, and the trace-processing effect.

Keep the proposal signal wiring, but route it through `opts.onProposal`
instead of a local `setProposal`:

```typescript
  const handleProposalSignal = useCallback((p: ProposalState | null) => {
    proposalPendingRef.current = p !== null
    opts.onProposal?.(p)
  }, [opts])
```

Return the `AgentSession` shape above, mapping `handleSend` → `send`,
`handleStopAgent` → `stop`, `handleResumeAgent` → `resume`,
`handleManualInput` → `onManualInput`.

- [ ] **Step 2: Consume the hook from EditorPage**

In `src/pages/EditorPage.tsx`:

```typescript
  const [proposal, setProposal] = useState<ProposalState | null>(null)
  const scene = useSceneSession()
  const agent = useAgentSession({ scene, stage, onProposal: setProposal })
```

Update references: `messages` → `agent.messages`, `isThinking` →
`agent.isThinking`, `narration` → `agent.narration`, `agentPaused` →
`agent.agentPaused`, `handleSend` → `agent.send`, `handleStopAgent` →
`agent.stop`, `handleResumeAgent` → `agent.resume`, `handleManualInput` →
`agent.onManualInput`. `proposal` and `handleProposalDecide` stay in the page.

- [ ] **Step 3: Verify no behavior changed**

Run each and confirm:
- `npx tsc --noEmit` → no output
- `npm test` → 211 passed
- `npm run lint` → 0 errors

- [ ] **Step 4: Manual check**

With the backend and Vite running, load a `.ply`, send a chat message, and
confirm the agent still runs, narrates, and can be stopped. This refactor
touches the whole agent path and no automated test covers the wiring
end-to-end.

- [ ] **Step 5: Commit**

```bash
git add src/session/useAgentSession.ts src/pages/EditorPage.tsx
git commit -m "refactor(session): extract the agent session hook"
```

---

### Task 7: The analyst page

**Files:**
- Create: `src/pages/AnalystPage.tsx`
- Create: `src/pages/AnalystPage.test.ts`
- Modify: `src/App.tsx`

**Interfaces:**
- Consumes: `useSceneSession`, `useAgentSession`, `Route` from Tasks 3/5/6.
- Produces: `AnalystPage` — default export, props `{ sceneId: string | null }`.

- [ ] **Step 1: Write the failing test**

Create `src/pages/AnalystPage.test.ts`:

```typescript
import { describe, it, expect } from 'vitest'
import { analystStatus } from './AnalystPage'

describe('analystStatus', () => {
  it('asks for a scene when the URL carries none', () => {
    expect(analystStatus(null, false)).toBe('no-scene')
  })

  it('reports a missing scene when the backend no longer holds it', () => {
    expect(analystStatus('abc', true)).toBe('scene-gone')
  })

  it('is ready when a scene id resolved', () => {
    expect(analystStatus('abc', false)).toBe('ready')
  })
})
```

- [ ] **Step 2: Run it**

Run: `npx vitest run src/pages/AnalystPage.test.ts`
Expected: FAIL — "Failed to resolve import './AnalystPage'".

- [ ] **Step 3: Write the page**

Create `src/pages/AnalystPage.tsx`:

```typescript
import { useEffect, useState } from 'react'
import ViewerCanvas from '../viewer/ViewerCanvas'
import ViewerErrorBoundary from '../ui/ViewerErrorBoundary'
import ChatPanel from '../ui/ChatPanel'
import NarrationBar from '../ui/NarrationBar'
import MovePad from '../ui/MovePad'
import RotatePad from '../ui/RotatePad'
import EmptyState from '../ui/EmptyState'
import { useSceneSession } from '../session/useSceneSession'
import { useAgentSession } from '../session/useAgentSession'

export type AnalystStatus = 'no-scene' | 'scene-gone' | 'ready'

/** Which state the analyst renders. Pure so it can be tested without a DOM. */
export function analystStatus(sceneId: string | null, gone: boolean): AnalystStatus {
  if (!sceneId) return 'no-scene'
  return gone ? 'scene-gone' : 'ready'
}

export default function AnalystPage({ sceneId }: { sceneId: string | null }) {
  const scene = useSceneSession()
  // Understand stage only: this window has no editing surface at all.
  const agent = useAgentSession({ scene, stage: 'understand' })
  const [gone, setGone] = useState(false)
  const { loadBackendScene } = scene

  useEffect(() => {
    if (!sceneId) return
    setGone(false)
    void loadBackendScene(sceneId).catch(() => setGone(true))
  }, [sceneId, loadBackendScene])

  const status = analystStatus(sceneId, gone)

  return (
    <div className="flex h-screen w-screen flex-col bg-neutral-950 text-white">
      <div className="flex items-center gap-3 border-b border-white/10 px-4 py-2">
        <span className="font-mono text-sm text-white/80">Scene Analyst</span>
        <span className="font-mono text-xs text-white/40">look-only</span>
      </div>
      <div className="flex min-h-0 flex-1">
        <div className="relative flex min-w-0 flex-1 flex-col">
          <div className="relative min-h-0 flex-1">
            <ViewerErrorBoundary>
              <ViewerCanvas ref={scene.viewerRef} onStateChange={scene.setViewerState} />
            </ViewerErrorBoundary>

            {status === 'ready' && scene.hasScene && (
              <div className="absolute bottom-3 right-3 z-20 flex items-end gap-2">
                <RotatePad
                  activeRotations={new Set()}
                  onInput={(dir, active) => {
                    if (active) agent.onManualInput()
                    scene.viewerRef.current?.setRotationInput(dir, active)
                  }}
                />
                <MovePad
                  activeDirections={new Set()}
                  onInput={(dir, active) => {
                    if (active) agent.onManualInput()
                    scene.viewerRef.current?.setMovementInput(dir, active)
                  }}
                />
              </div>
            )}

            {status === 'scene-gone' && (
              <div className="absolute inset-0 z-30 flex flex-col items-center justify-center gap-3 bg-black/80 px-6 text-center">
                <p className="font-mono text-sm text-amber-200/90">
                  That scene is no longer loaded on the backend.
                </p>
                <p className="max-w-md font-mono text-xs text-white/50">
                  Scenes live in memory only, so restarting the backend clears
                  them. Re-open this window from the editor, or drop a .ply
                  below to analyze it directly.
                </p>
                <EmptyState onImport={() => {}} onDropFile={scene.loadFile} />
              </div>
            )}

            {status === 'no-scene' && (
              <EmptyState onImport={() => {}} onDropFile={scene.loadFile} />
            )}
          </div>
          <NarrationBar state={scene.viewerState} />
        </div>
        <ChatPanel
          isOpen
          stage="understand"
          messages={agent.messages}
          isThinking={agent.isThinking}
          narration={agent.narration}
          proposal={null}
          onProposalDecide={() => {}}
          onSend={agent.send}
          onStop={agent.stop}
          onClose={() => {}}
        />
      </div>
    </div>
  )
}
```

Check `src/ui/EmptyState.tsx` and `src/ui/ChatPanel.tsx` for their exact prop
types and adjust the calls above if any prop is required that is not passed
(e.g. if `onImport` is optional, drop the no-op).

- [ ] **Step 4: Run it**

Run: `npx vitest run src/pages/AnalystPage.test.ts`
Expected: PASS, 3 tests.

- [ ] **Step 5: Route to it**

Replace `src/App.tsx`:

```typescript
import { useRoute } from './routing'
import EditorPage from './pages/EditorPage'
import AnalystPage from './pages/AnalystPage'

export default function App() {
  const route = useRoute()
  if (route.page === 'analyst') return <AnalystPage sceneId={route.sceneId} />
  return <EditorPage />
}
```

- [ ] **Step 6: Verify**

Run each and confirm:
- `npx tsc --noEmit` → no output
- `npm test` → 214 passed (211 + 3 new)
- `npm run lint` → 0 errors

- [ ] **Step 7: Commit**

```bash
git add src/pages/AnalystPage.tsx src/pages/AnalystPage.test.ts src/App.tsx
git commit -m "feat(analyst): look-only analyst page on a shared backend scene"
```

---

### Task 8: "Analyze scene" handoff from the editor

**Files:**
- Modify: `src/ui/TopBar.tsx`
- Modify: `src/pages/EditorPage.tsx`
- Create: `src/ui/TopBar.analyze.test.ts`

**Interfaces:**
- Consumes: `analystHref` from Task 3.
- Produces: `TopBar` gains props `onAnalyze?: () => void` and
  `canAnalyze?: boolean`.

- [ ] **Step 1: Write the failing test**

Create `src/ui/TopBar.analyze.test.ts`:

A render-mount test, following the precedent set by
`src/ui/EditorToolbar.test.ts` — that one exists because props were silently
dropped inside a `.map()`, and a pure-logic test would not have caught it.

```typescript
import { describe, it, expect, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import TopBar from './TopBar.tsx'
import { analystHref } from '../routing'

let root: Root | null = null
let host: HTMLDivElement | null = null

function render(props: Record<string, unknown>) {
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  act(() => { root!.render(createElement(TopBar, props as never)) })
  return host
}

afterEach(() => {
  act(() => root?.unmount())
  host?.remove()
  root = null
  host = null
})

function analyzeButton(el: HTMLElement): HTMLButtonElement | undefined {
  return Array.from(el.querySelectorAll('button'))
    .find((b) => b.textContent?.includes('Analyze scene')) as HTMLButtonElement | undefined
}

describe('Analyze scene handoff', () => {
  it('renders the action when a handler is supplied', () => {
    const el = render({ onAnalyze: () => {}, canAnalyze: true })
    expect(analyzeButton(el)).toBeTruthy()
  })

  it('is disabled until a scene is registered with the backend', () => {
    const el = render({ onAnalyze: () => {}, canAnalyze: false })
    expect(analyzeButton(el)?.disabled).toBe(true)
  })

  it('fires the handler on click once enabled', () => {
    let fired = 0
    const el = render({ onAnalyze: () => { fired += 1 }, canAnalyze: true })
    act(() => { analyzeButton(el)?.click() })
    expect(fired).toBe(1)
  })

  it('targets the analyst route for the current scene', () => {
    expect(analystHref('scene-42')).toBe('#/analyze?scene=scene-42')
  })
})
```

`TopBar` has required props beyond these — check its props interface and add
whatever the type demands to the `render({...})` calls (the existing
`EditorToolbar.test.ts` does the same).

- [ ] **Step 2: Run it**

Run: `npx vitest run src/ui/TopBar.analyze.test.ts`
Expected: FAIL — no button matches "Analyze scene" because the prop and the
markup do not exist yet.

- [ ] **Step 3: Add the action to TopBar**

In `src/ui/TopBar.tsx`, add to the props interface:

```typescript
  /** Open the analyst window on the current backend scene. */
  onAnalyze?: () => void
  /** False until a scene is registered with the backend. */
  canAnalyze?: boolean
```

and render a button in the same row as the existing stage switcher:

```tsx
      {onAnalyze && (
        <button
          type="button"
          onClick={onAnalyze}
          disabled={!canAnalyze}
          title={canAnalyze
            ? 'Open the scene analyst in a new window'
            : 'Load a .ply first — the analyst needs a registered scene'}
          className="rounded border border-white/20 bg-white/5 px-2 py-1 font-mono text-xs text-white/90 enabled:hover:bg-white/15 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
        >
          Analyze scene
        </button>
      )}
```

- [ ] **Step 4: Wire it from EditorPage**

In `src/pages/EditorPage.tsx`, import `analystHref` from `../routing` and pass
to `<TopBar ...>`:

```tsx
        canAnalyze={scene.backendSceneId !== null}
        onAnalyze={() => {
          if (scene.backendSceneId) {
            window.open(analystHref(scene.backendSceneId), '_blank', 'noopener')
          }
        }}
```

- [ ] **Step 5: Verify**

Run each and confirm:
- `npx tsc --noEmit` → no output
- `npm test` → 218 passed (214 + 4 new)
- `npm run lint` → 0 errors

Manual: load a `.ply`, confirm the button enables once upload completes, click
it, and confirm a new window opens showing the same scene with no tool rail.

- [ ] **Step 6: Commit**

```bash
git add src/ui/TopBar.tsx src/ui/TopBar.analyze.test.ts src/pages/EditorPage.tsx
git commit -m "feat(editor): hand the current scene off to the analyst window"
```

---

### Task 9: Validate on Iona Park

The structural work is testable; answer quality is not. This task is the
manual acceptance run against the spec's answer key (§3).

**Files:**
- Create: `docs/eval/iona-park.md`

**Interfaces:**
- Consumes: everything above.
- Produces: a recorded baseline for future prompt iteration.

- [ ] **Step 1: Bring the stack up**

Requires the local vLLM at `localhost:8001` to be running — it was down on
2026-07-28 and nothing here can be validated without it. Confirm with:

```bash
curl -s -m 5 http://localhost:8001/v1/models
curl -s -X POST http://127.0.0.1:8000/config/test -H 'content-type: application/json' -d '{}'
```

Expected: a model list, and `{"ok":true,...}`.

- [ ] **Step 2: Load and hand off**

Load `public/demos/iona_park.ply` in the editor. Confirm the viewer does NOT
freeze after render (Task 1). Frame the whole site so all structures are
visible, then click **Analyze scene**.

- [ ] **Step 3: Run the two acceptance questions**

In the analyst window, ask in turn:

1. `what am I looking at?`
2. `how many buildings are in this scene?`

- [ ] **Step 4: Score against the answer key**

Ground truth: aerial capture of a low-cost / trailer-park housing area; **13
buildings** (8 clearly resolvable in the main frame, ~5 in the background);
**no major damage**, all structures standing.

Record pass/fail for each:

- [ ] Names the modality and setting (aerial, residential) before counting
- [ ] Foreground count is near 8
- [ ] Background structures acknowledged as approximate rather than omitted or
      counted confidently
- [ ] Total is near 13 — critically, NOT 20+ (that is the double-counting
      failure this plan exists to remove)
- [ ] No invented damage
- [ ] No reconstruction artifact described as collapse or destruction

- [ ] **Step 5: Record the baseline**

Create `docs/eval/iona-park.md` with the ground truth above, the exact
questions asked, the model's verbatim answers, and the pass/fail scoring. This
is the comparison point for future prompt changes — without it, "seems better"
is unfalsifiable.

- [ ] **Step 6: Commit**

```bash
git add docs/eval/iona-park.md
git commit -m "docs: record the Iona Park analyst baseline"
```

---

## Self-Review Notes

**Spec coverage:** §4 → Task 1. §5.1 → Task 3. §5.2 → Tasks 5, 8. §5.3 → Task
7. §5.4 → Task 7 (no editing UI rendered). §5.5 → Tasks 4, 5, 6. §6.1, §6.2,
§6.3 → Task 2. §9 → tests throughout plus Task 9. §10 (open questions) is
deliberately unplanned — deleting the other demo scenes needs the operator's
confirmation, and model availability is an environment precondition, recorded
in Task 9 Step 1.

**Known risk:** Tasks 5 and 6 move a large amount of code out of a 981-line
file. They are specified as verbatim moves with explicit member lists rather
than as full code blocks, because reproducing ~600 lines inside a plan invites
transcription errors. The gate after each (type-check, 211 tests, lint) plus
the Task 6 manual check is what catches a bad move. If a move proves
unworkable, stop and re-plan rather than reshaping behavior mid-refactor.

## Execution Notes (2026-07-28)

Recorded during execution; the tasks above are left as written so the plan and
what actually happened can be compared.

1. **Tasks 5 and 6 were merged into one `useSession` hook.** The two-hook split
   is circular: `registerScene` (scene) must dispose the stale agent, and the
   agent's send path calls `registerScene` to recover from a restarted backend.
   Each would need the other at construction time. The spec says "a hook"
   (singular) — the plan invented the split.
2. **`tsc --noEmit` checks nothing in this repo.** `tsconfig.json` is
   solution-style (`files: []`, project references only), so it silently
   type-checks zero files. Every gate step above should read **`tsc -b`**, which
   is what `npm run build` runs and what caught two real errors in the refactor.
3. **Task 1 Step 1 was wrong** to say the rest of the roundtrip test could stay
   unchanged — a second upload later in that same test also read `["metrics"]`.
4. **Task 8 landed inside the Task 5/6 commit**, since the TopBar props belong
   to the same prop surface the refactor touched.
5. **Task 9 is unfinished**: the local vLLM was down, so the acceptance run
   could not happen. `docs/eval/iona-park.md` holds the answer key, procedure,
   and an empty results section ready for the run.
6. Final gate: backend **243 passed**, frontend **220 passed**, `tsc -b` clean,
   lint 0 errors (1 pre-existing warning), `npm run build` succeeds.

**Deliberately not planned:** visual memory across turns and grounded-box 3D
deduplication, both covered in spec §8 with reasoning.
