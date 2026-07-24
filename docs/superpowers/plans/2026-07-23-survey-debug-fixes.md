# Survey Debug Fixes (P1s + quick P2s) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the seven verified deterministic bugs behind the survey-run failure: post-run camera yank, WS lifecycle stranding, direction-blind coverage, missing perception barrier, broken command envelopes, plus provider timeout parity and system-prompt duplication.

**Architecture:** Backend (FastAPI/Python) owns the agent loop, WS connection manager, and providers; frontend has two trees — `src/` (live editor app) and `frontend/src/agent/` (agent WS client/executors, aliased as `@agent`). Each fix is a vertical slice: failing test → minimal change → green → commit.

**Tech Stack:** Python 3.12 + pytest (backend), TypeScript + vitest (frontend), Three.js, FastAPI, WebSocket.

## Global Constraints

- Contracts are frozen within a phase: do NOT touch `backend/contracts/tools.py` or `frontend/src/contracts.ts` (no task here needs a registry change; new event/percept fields are additive payload fields, not registry entries).
- Backend tests: `source .venv-api/bin/activate && pytest <path> -x -v` from the repo root (Python 3.12 venv per CLAUDE.md).
- Frontend tests: `npm test -- --run <path>`; type gate `npx tsc --noEmit`; lint `npm run lint`.
- Work on the current branch `feat/agent-cleanup-proposals`. Do NOT commit `.claude/settings.json`.
- Every commit message ends with the two standard trailers (Co-Authored-By: Claude Fable 5 / Claude-Session) per harness rules.

---

### Task 0: Commit the pre-existing uncommitted work

The working tree already holds three related, reviewed changes this plan builds on. Land them as two commits so later tasks diff cleanly.

**Files:**
- Commit (a): `backend/providers/openai.py`, `backend/providers/tests/test_openai_timeout.py`
- Commit (b): `src/viewer/framing.ts`, `src/viewer/framing.test.ts`, `frontend/src/agent/camera.test.ts`, `src/backend/trace.ts`, `src/backend/trace.test.ts`

- [ ] **Step 1: Verify the tree state matches expectations**

Run: `git status --short`
Expected: exactly the files above modified (plus `.claude/settings.json` and `tasks/` — leave both alone).

- [ ] **Step 2: Run the touched suites**

Run: `source .venv-api/bin/activate && pytest backend/providers/tests/ -x -q`
Expected: PASS (openai timeout test needs `openai` installed; skip is acceptable).
Run: `npm test -- --run src/viewer/framing.test.ts frontend/src/agent/camera.test.ts src/backend/trace.test.ts`
Expected: PASS.

- [ ] **Step 3: Commit in two slices**

```bash
git add backend/providers/openai.py backend/providers/tests/test_openai_timeout.py
git commit -m "fix(providers): bound the OpenAI client timeout (120s) so a half-dead tunnel surfaces as an error"
git add src/viewer/framing.ts src/viewer/framing.test.ts frontend/src/agent/camera.test.ts src/backend/trace.ts src/backend/trace.test.ts
git commit -m "fix(viewer): median/80th-percentile scene core + honest non-answer completion text"
```

---

### Task 1: Frontend WS envelope fixes (P1 — drop_marker / narrate / capture_request / reset_trail)

The dispatcher wraps EVERY frontend command as `{type, tool, args}` (`backend/agent/dispatch.py:160-164`), but three `ws-client.ts` cases read fields from the payload root, and `reset_trail` maps to `camera_move` with no frontend case. One caveat: the loop's own `ev_narrate` events arrive as `{type:'narrate', payload:{text}}` (root shape, no `args`, no meaningful reply) — narrate must accept BOTH shapes.

**Files:**
- Modify: `frontend/src/agent/ws-client.ts:79-112` (capture_request, drop_marker, narrate cases)
- Modify: `frontend/src/agent/executors.ts:370-389` (CameraTool union, reset_trail executor, runCameraTool default)
- Modify: `frontend/src/agent/types.ts:80-92` (ToolResult failure variant, CameraMovePayload union)
- Modify: `frontend/src/agent/mock-backend.ts` (align narrate/capture envelopes with the dispatcher)
- Test: `frontend/src/agent/ws-client.test.ts`

**Interfaces:**
- Produces: `FrontendExecutors.reset_trail(args): Promise<ToolResult>`; `ToolResult` gains `| { ok: false; error: string }`; `runCameraTool` returns a rejection (not `undefined`) for unknown tools.

- [ ] **Step 1: Write the failing tests** (append to `ws-client.test.ts`; reuse its existing `FakeTransport`)

```ts
class FakeOverlay {
  markers: Array<{ position: [number, number, number]; label: string }> = []
  trailResets = 0
  dropMarker(position: [number, number, number], label: string): void { this.markers.push({ position, label }) }
  resetTrail(): void { this.trailResets += 1 }
}

class FakePanels {
  narrations: string[] = []
  setNarration(text: string): void { this.narrations.push(text) }
  pushTrace(): void {}
}

describe('ws-client command envelopes (dispatcher wraps everything as {tool, args})', () => {
  let transport: FakeTransport
  let overlay: FakeOverlay
  let panels: FakePanels

  beforeEach(() => {
    transport = new FakeTransport()
    overlay = new FakeOverlay()
    panels = new FakePanels()
    void new AgentWSClient(
      transport as unknown as Transport,
      {} as unknown as RendererBridge,
      overlay as unknown as Overlay,
      panels as unknown as PanelBus,
    )
  })

  function lastReplyPayload(): Record<string, unknown> {
    const msg = transport.sent[transport.sent.length - 1] as { payload?: Record<string, unknown> }
    return msg?.payload ?? {}
  }

  it('drop_marker reads position/label from p.args (the dispatcher envelope)', async () => {
    await transport.handler!({ type: 'drop_marker', id: 'c1', payload: { tool: 'drop_marker', args: { position: [1, 2, 3], label: 'floaters' } } })
    expect(overlay.markers).toEqual([{ position: [1, 2, 3], label: 'floaters' }])
    expect(lastReplyPayload().ok).toBe(true)
  })

  it('drop_marker rejects a malformed payload instead of throwing into a generic error', async () => {
    await transport.handler!({ type: 'drop_marker', id: 'c2', payload: { position: [1, 2, 3] } })
    expect(overlay.markers).toEqual([])
    expect(lastReplyPayload().ok).toBe(false)
  })

  it('narrate reads text from p.args and reports failure when both shapes are absent', async () => {
    await transport.handler!({ type: 'narrate', id: 'c3', payload: { tool: 'narrate', args: { text: 'scanning the ridge' } } })
    expect(panels.narrations).toEqual(['scanning the ridge'])
    expect(lastReplyPayload().ok).toBe(true)

    await transport.handler!({ type: 'narrate', id: 'c4', payload: { tool: 'narrate', args: {} } })
    expect(panels.narrations).toEqual(['scanning the ridge']) // no blank narration
    expect(lastReplyPayload().ok).toBe(false)
  })

  it('narrate still accepts the loop-event root shape {text} (ev_narrate has no args)', async () => {
    await transport.handler!({ type: 'narrate', payload: { text: 'Paused — the operator has control.' } })
    expect(panels.narrations).toEqual(['Paused — the operator has control.'])
  })

  it('reset_trail routed as camera_move actually resets the trail', async () => {
    await transport.handler!({ type: 'camera_move', id: 'c5', payload: { tool: 'reset_trail', args: {} } })
    expect(overlay.trailResets).toBe(1)
    expect(lastReplyPayload().ok).toBe(true)
  })

  it('an unknown camera tool is rejected, not silently succeeded', async () => {
    await transport.handler!({ type: 'camera_move', id: 'c6', payload: { tool: 'warp_drive', args: {} } })
    expect(lastReplyPayload().ok).toBe(false)
  })
})
```

- [ ] **Step 2: Run to verify they fail**

Run: `npm test -- --run frontend/src/agent/ws-client.test.ts`
Expected: FAIL — markers empty (root read), narration missing, trailResets 0, unknown-tool reply `undefined`.

- [ ] **Step 3: Implement**

In `frontend/src/agent/types.ts`, extend `ToolResult` and `CameraMovePayload`:

```ts
export type ToolResult =
  | { ok: true }
  | { ok: false; error: string }
  | { png_base64: string; percept?: PerceptTag }  // capture_frame
  | { frames_base64: string[] }   // capture_orbit

export interface CameraMovePayload {
  tool: Extract<
    FrontendToolName,
    'look_at' | 'set_view' | 'orbit' | 'dolly' | 'frame_object' | 'reset_view' | 'scan_pause' | 'reframe' | 'reset_trail'
  >
  args: Record<string, unknown>
}
```

In `frontend/src/agent/executors.ts`, add the executor (next to `scan_pause`), extend the union, and reject unknowns:

```ts
  /** Clear the breadcrumb trail — routed as a camera_move (dispatch.py maps it). */
  async reset_trail(_args: Record<string, never>): Promise<ToolResult> {
    void _args
    this.overlay.resetTrail()
    return { ok: true }
  }
```

Note: `FrontendExecutors` currently takes `(private bridge, private overlay)` — `overlay` is already a field.

```ts
export type CameraTool =
  | 'look_at' | 'set_view' | 'orbit' | 'dolly' | 'frame_object' | 'reset_view' | 'scan_pause' | 'reframe' | 'reset_trail'

export function runCameraTool(
  ex: FrontendExecutors,
  tool: CameraTool,
  args: Record<string, unknown>,
): Promise<ToolResult> {
  switch (tool) {
    case 'look_at': return ex.look_at(args as never)
    case 'set_view': return ex.set_view(args as never)
    case 'orbit': return ex.orbit(args as never)
    case 'dolly': return ex.dolly(args as never)
    case 'frame_object': return ex.frame_object(args as never)
    case 'reset_view': return ex.reset_view(args as never)
    case 'reframe': return ex.reframe(args as never)
    case 'scan_pause': return ex.scan_pause(args as never)
    case 'reset_trail': return ex.reset_trail(args as never)
    default:
      // Malformed/unknown payloads must be rejected at the boundary, never
      // silently "succeed" (the old switch returned undefined here).
      return Promise.resolve({ ok: false, error: `unknown camera tool: ${String(tool)}` })
  }
}
```

In `frontend/src/agent/ws-client.ts`, replace the three cases:

```ts
        case 'capture_request': {
          // Dispatcher envelope: {tool: 'capture_frame'|'capture_orbit', args}.
          const { tool, args } = p as unknown as {
            tool?: string
            args?: { center: number[]; n: number; radius?: number }
          }
          const result = tool === 'capture_orbit' && args
            ? await this.executors.capture_orbit(args)
            : await this.executors.capture_frame()
          this.reply(cmd.id, result as Record<string, unknown>)
          break
        }
        case 'drop_marker': {
          const { args } = p as unknown as { args?: { position?: unknown; label?: unknown } }
          const position = args?.position
          if (!Array.isArray(position) || position.length !== 3 || position.some((v) => typeof v !== 'number')) {
            this.reply(cmd.id, { ok: false, error: 'drop_marker: args.position must be [x,y,z]' })
            break
          }
          this.overlay.dropMarker(
            position as [number, number, number],
            typeof args?.label === 'string' ? args.label : '',
          )
          this.reply(cmd.id, { ok: true })
          break
        }
        case 'narrate': {
          // Two legitimate shapes: the dispatcher command {tool, args:{text}}
          // and the loop's ev_narrate EVENT {text} (no args, no correlation id).
          const maybe = p as { args?: { text?: unknown }; text?: unknown }
          const text = typeof maybe.args?.text === 'string'
            ? maybe.args.text
            : typeof maybe.text === 'string' ? maybe.text : ''
          if (!text) {
            if (cmd.id) this.reply(cmd.id, { ok: false, error: 'narrate: args.text missing' })
            break
          }
          this.panels.setNarration(text)
          if (cmd.id) this.reply(cmd.id, { ok: true })
          break
        }
```

In `frontend/src/agent/mock-backend.ts`, align the mock with the dispatcher's shape (the mock claims to mirror the real loop):
- `command('narrate', { text: … })` → `command('narrate', { tool: 'narrate', args: { text: … } })` (all narrate call sites, lines ~47/59/84)
- `command('capture_request', {})` → `command('capture_request', { tool: 'capture_frame', args: {} })` (line ~66)
- the orbit capture (line ~76) → `command('capture_request', { tool: 'capture_orbit', args: { center: [0, 0, 0], n: 4, radius: 2.2 } })` keeping its current numeric values.

- [ ] **Step 4: Run tests + gates**

Run: `npm test -- --run frontend/src/agent/` then `npx tsc --noEmit && npm run lint`
Expected: PASS (fix any mock-backend test fallout — the shapes above are the contract).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/agent/ws-client.ts frontend/src/agent/ws-client.test.ts frontend/src/agent/executors.ts frontend/src/agent/types.ts frontend/src/agent/mock-backend.ts
git commit -m "fix(agent-fe): parse the {tool,args} command envelope for drop_marker/narrate/capture; wire reset_trail; reject unknown camera tools"
```

---

### Task 2: Backend WS — identity-aware disconnect + renderer precondition on /agent/run (P1)

`connect()` replaces socket A with B, then A's route cleanup calls `disconnect(scene_id)` which evicts B (`backend/api/ws.py:52-72`, `backend/api/routes.py:279-282`). And `/agent/run` starts with no renderer check while `emit_event` silently drops `complete` events (`ws.py:183-184`) — the zombie-spinner state.

**Files:**
- Modify: `backend/api/ws.py:64-72` (disconnect signature), `ws.py:181-188` (emit_event failure path)
- Modify: `backend/api/routes.py:241-282` (agent_run precondition; scene_ws passes its socket)
- Test: `backend/api/tests/test_ws.py`, `backend/api/tests/test_run_exclusion.py`

**Interfaces:**
- Produces: `ConnectionManager.disconnect(scene_id: str, websocket: Any | None = None)` — with a socket given, removal happens only if that socket is still registered. `/agent/run` → HTTP 409 `"no renderer connected …"` when `not manager.is_connected(scene_id)`.

- [ ] **Step 1: Write the failing manager test** (append to `test_ws.py`; `MockWS` already exists there)

```python
@pytest.mark.anyio
async def test_stale_socket_cleanup_does_not_evict_replacement():
    """The reconnect race: connect() swaps A→B, then A's route cleanup fires.
    Keyed-by-scene disconnect used to evict B, leaving no renderer registered."""
    mgr = ConnectionManager()
    a, b = MockWS(), MockWS()
    await mgr.connect("s1", a)
    await mgr.connect("s1", b)   # one-renderer-per-scene: closes and replaces a
    mgr.disconnect("s1", a)      # stale route cleanup for the OLD socket
    assert mgr.is_connected("s1"), "replacement socket must survive stale cleanup"
    mgr.disconnect("s1", b)      # the CURRENT socket's cleanup still removes
    assert not mgr.is_connected("s1")


@pytest.mark.anyio
async def test_disconnect_without_socket_still_removes():
    mgr = ConnectionManager()
    await mgr.connect("s1", MockWS())
    mgr.disconnect("s1")
    assert not mgr.is_connected("s1")
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest backend/api/tests/test_ws.py -x -v -k stale_socket`
Expected: FAIL — `disconnect() takes 2 positional arguments but 3 were given`.

- [ ] **Step 3: Implement the manager + route changes**

`backend/api/ws.py` — replace `disconnect`:

```python
    def disconnect(self, scene_id: str, websocket: Any | None = None) -> None:
        """Remove a scene's renderer. With `websocket` given, remove it only if
        it is STILL the registered socket: connect() swaps in a replacement
        before the old socket's route cleanup runs, and that stale cleanup must
        never evict the replacement (observed reconnect race)."""
        if websocket is not None and self._conns.get(scene_id) is not websocket:
            return
        self._conns.pop(scene_id, None)
        # fail any in-flight commands for this scene
        for corr_id, sid in list(self._pending_scene.items()):
            if sid == scene_id:
                fut = self._pending.pop(corr_id, None)
                self._pending_scene.pop(corr_id, None)
                if fut and not fut.done():
                    fut.set_exception(ConnectionError("renderer disconnected"))
```

`ws.py` `emit_event` except-branch: `self.disconnect(scene_id)` → `self.disconnect(scene_id, ws)`.

`backend/api/routes.py` `scene_ws`: both `manager.disconnect(scene_id)` calls → `manager.disconnect(scene_id, websocket)`.

`routes.py` `agent_run`, after the existing already-active 409:

```python
        if not manager.is_connected(req.scene_id):
            raise HTTPException(
                status_code=409,
                detail="no renderer connected for this scene — completion events "
                       "would be dropped silently; open the viewer first",
            )
```

- [ ] **Step 4: Write the route-level tests**

`test_run_exclusion.py` — add a fake renderer and connect it in the existing test (its POSTs would now 409), plus a new test:

```python
class FakeRenderer:
    async def accept(self) -> None: ...
    async def send_json(self, message: dict) -> None: ...
    async def close(self) -> None: ...
```

In `test_second_concurrent_run_is_rejected_with_409`, after `scene_id = up.json()["id"]`, add:

```python
        await app.state.manager.connect(scene_id, FakeRenderer())
```

New test in the same file:

```python
@pytest.mark.anyio
async def test_run_without_renderer_is_rejected_with_409(monkeypatch):
    runner = BlockingRunner()
    monkeypatch.setattr(server_mod, "_select_runner", lambda: runner)
    app = server_mod.create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with open(MESSY, "rb") as f:
            up = await client.post(
                "/scene", files={"file": ("messy.ply", f, "application/octet-stream")}
            )
        scene_id = up.json()["id"]
        r = await client.post(
            "/agent/run", json={"scene_id": scene_id, "prompt": "clean", "stage": "clean"}
        )
        assert r.status_code == 409
        assert "no renderer" in r.json()["detail"]
```

- [ ] **Step 5: Run the API suite**

Run: `pytest backend/api/tests/ -x -q`
Expected: PASS. If any other test POSTs `/agent/run` without a WS (check `test_rest.py`), connect a `FakeRenderer` the same way.

- [ ] **Step 6: Commit**

```bash
git add backend/api/ws.py backend/api/routes.py backend/api/tests/test_ws.py backend/api/tests/test_run_exclusion.py
git commit -m "fix(api): stale-socket cleanup can no longer evict a replacement renderer; /agent/run requires a connected renderer"
```

---

### Task 3: Frontend transport lifecycle — close/error surfaces instead of stranding (P1)

`WebSocketTransport` has no close/error handling and `App.ensureAgent` trusts a cached `agentRef` forever. A dead socket leaves `isThinking` stuck true, which ALSO blocks all future runs (`src/App.tsx:571`).

**Files:**
- Modify: `frontend/src/agent/transport.ts` (Transport.onClose?, WebSocketTransport implementation)
- Modify: `src/App.tsx:525-545` (`ensureAgent` registers onClose → teardown + visible state reset)
- Test: `frontend/src/agent/transport.test.ts` (new)

**Interfaces:**
- Produces: `Transport.onClose?(handler: () => void): void` (optional — mocks may omit). WebSocketTransport fires handlers exactly once on UNEXPECTED close/error; a deliberate `close()` never fires them; handlers registered after death fire immediately.

- [ ] **Step 1: Write the failing test** (`frontend/src/agent/transport.test.ts`)

```ts
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { WebSocketTransport } from './transport.ts'

class FakeWS {
  static last: FakeWS | null = null
  readyState = 0 // CONNECTING
  binaryType = ''
  private listeners = new Map<string, Array<(ev?: unknown) => void>>()
  constructor(public url: string) { FakeWS.last = this }
  addEventListener(type: string, cb: (ev?: unknown) => void): void {
    const arr = this.listeners.get(type) ?? []
    arr.push(cb)
    this.listeners.set(type, arr)
  }
  fire(type: string, ev: unknown = {}): void {
    ;(this.listeners.get(type) ?? []).forEach((cb) => cb(ev))
  }
  send(_m: string): void {}
  close(): void { this.readyState = 3 }
}

describe('WebSocketTransport lifecycle', () => {
  beforeEach(() => {
    vi.stubGlobal('WebSocket', Object.assign(FakeWS, { OPEN: 1, CONNECTING: 0, CLOSED: 3 }))
  })

  it('fires onClose exactly once when the socket dies unexpectedly (close then error)', () => {
    const t = new WebSocketTransport('ws://x')
    let fired = 0
    t.onClose(() => { fired += 1 })
    FakeWS.last!.fire('close')
    FakeWS.last!.fire('error')
    expect(fired).toBe(1)
  })

  it('a deliberate close() does not fire onClose (scene switch is not a failure)', () => {
    const t = new WebSocketTransport('ws://x')
    let fired = 0
    t.onClose(() => { fired += 1 })
    t.close()
    FakeWS.last!.fire('close')
    expect(fired).toBe(0)
  })

  it('a handler registered after death fires immediately', () => {
    const t = new WebSocketTransport('ws://x')
    FakeWS.last!.fire('close')
    let fired = 0
    t.onClose(() => { fired += 1 })
    expect(fired).toBe(1)
  })

  it('send() on a non-open socket drops without throwing', () => {
    const t = new WebSocketTransport('ws://x')
    expect(() => t.send({ type: 'user_interrupt', id: 'i', payload: {} })).not.toThrow()
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- --run frontend/src/agent/transport.test.ts`
Expected: FAIL — `t.onClose is not a function`.

- [ ] **Step 3: Implement** (`frontend/src/agent/transport.ts`)

Add to the interface:

```ts
export interface Transport {
  /** Frontend → backend (frame / user_interrupt). */
  send(msg: WSResponse): void
  /** Register the handler for backend → frontend messages (commands + trace). */
  onMessage(handler: (data: unknown) => void): void
  /** Optional: fired once if the channel dies UNEXPECTEDLY (close/error).
   *  A deliberate close() never fires it. Mocks may omit. */
  onClose?(handler: () => void): void
  close(): void
}
```

In `WebSocketTransport`:

```ts
export class WebSocketTransport implements Transport {
  private ws: WebSocket
  private handler: ((data: unknown) => void) | null = null
  private closeHandlers: Array<() => void> = []
  private died = false        // unexpected close/error observed
  private closedByUs = false  // deliberate close() — not a failure

  constructor(url: string) {
    this.ws = new WebSocket(url)
    this.ws.binaryType = 'arraybuffer'
    this.ws.addEventListener('message', (ev) => {
      let data: unknown
      try {
        data = typeof ev.data === 'string' ? JSON.parse(ev.data) : ev.data
      } catch {
        data = ev.data
      }
      this.handler?.(data)
    })
    const fireClose = () => {
      if (this.closedByUs || this.died) return
      this.died = true
      this.closeHandlers.forEach((h) => h())
    }
    this.ws.addEventListener('close', fireClose)
    this.ws.addEventListener('error', fireClose)
  }

  onClose(handler: () => void): void {
    this.closeHandlers.push(handler)
    if (this.died) handler()
  }

  close(): void {
    this.closedByUs = true
    this.ws.close()
  }
  // send / onMessage / whenOpen unchanged
}
```

- [ ] **Step 4: Wire App teardown** (`src/App.tsx` `ensureAgent`, after `await transport.whenOpen()`)

```ts
    // The socket can die out from under a cached agent (backend restart,
    // network drop). Without this, `complete` never arrives, isThinking stays
    // true forever, and handleSend refuses every future run.
    transport.onClose?.(() => {
      disposeAgent()
      setIsThinking(false)
      setAgentPaused(false)
      setAgentStep(0)
      showStatus('Agent connection lost — the run was stopped. Send again to reconnect.')
    })
```

Update the `useCallback` dependency array: `[processTrace, handleProposalSignal, disposeAgent, showStatus]`.

- [ ] **Step 5: Run gates**

Run: `npm test -- --run frontend/src/agent/ && npx tsc --noEmit && npm run lint`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/agent/transport.ts frontend/src/agent/transport.test.ts src/App.tsx
git commit -m "fix(agent-fe): surface unexpected WS death — tear down the cached agent and unstick the run state"
```

---

### Task 4: Backend — `complete` carries `scene_changed` (P1)

The completion event (`backend/agent/types.py:57-58`) has no edit signal, so the frontend reloads (and reframes) after every run. Count successful scene-mutating tool executions in the dispatcher and stamp the flag on every `complete`.

**Files:**
- Modify: `backend/agent/types.py:57-58` (ev_complete), `backend/agent/dispatch.py:101-156` (counter), `backend/agent/loop.py:486,586,592` (all three ev_complete emissions)
- Test: `backend/agent/tests/test_scene_changed.py` (new)

**Interfaces:**
- Produces: `ev_complete(status, *, answer=None, error=None, scene_changed=False)` → payload key `scene_changed: bool`; `ToolDispatcher.edits_applied: int`.

- [ ] **Step 1: Write the failing test** (`backend/agent/tests/test_scene_changed.py`; agent tests use plain `asyncio.run`, no anyio marker)

```python
"""`complete` must say whether the scene actually changed: the frontend gates
its reload-and-reframe on it, so a read-only survey must never yank the
operator's camera when the run ends."""

from __future__ import annotations

import asyncio

from backend.agent import AgentLoop, ToolDispatcher
from backend.agent.mocks import MockBackendExecutor, MockFrontendChannel, MockProvider, tool_turn


def _run(coro):
    return asyncio.run(coro)


def _complete(channel: MockFrontendChannel) -> dict:
    return [e for e in channel.events if e.get("type") == "complete"][-1]


def test_lookonly_run_completes_with_scene_changed_false():
    channel = MockFrontendChannel()
    provider = MockProvider([
        tool_turn(("capture_frame", {})),
        tool_turn(("answer", {"text": "Two rooftops visible."})),
    ])
    loop = AgentLoop(provider, ToolDispatcher(MockBackendExecutor(), channel), channel, stage="understand")
    _run(loop.run("what do you see?"))
    assert _complete(channel)["scene_changed"] is False


def test_undo_marks_scene_changed_true():
    channel = MockFrontendChannel()
    executor = MockBackendExecutor()
    executor.snapshot()  # give undo something to restore
    provider = MockProvider([
        tool_turn(("undo", {})),
        tool_turn(("answer", {"text": "reverted"})),
    ])
    loop = AgentLoop(provider, ToolDispatcher(executor, channel), channel, stage="clean")
    _run(loop.run("undo that"))
    assert _complete(channel)["scene_changed"] is True
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest backend/agent/tests/test_scene_changed.py -x -v`
Expected: FAIL — `KeyError: 'scene_changed'`.

- [ ] **Step 3: Implement**

`backend/agent/types.py`:

```python
def ev_complete(
    status: str,
    *,
    answer: str | None = None,
    error: str | None = None,
    scene_changed: bool = False,
) -> dict:
    return {
        "type": "complete", "status": status, "answer": answer,
        "error": error, "scene_changed": scene_changed, "t": _now(),
    }
```

`backend/agent/dispatch.py` — module level (after `_SELECTION_EDIT_TOOLS`):

```python
# Tools whose success means the served scene differs from what the renderer
# has loaded: destructive edits plus history restores. Drives the `complete`
# event's scene_changed flag (the frontend gates its reload on it).
_SCENE_MUTATORS = DESTRUCTIVE_TOOLS | frozenset({"undo", "redo"})
```

In `ToolDispatcher.__init__`: `self.edits_applied = 0`.
In `_dispatch_backend`, before the final `return {"ok": True, ...}`:

```python
        if call.name in _SCENE_MUTATORS:
            self.edits_applied += 1
        return {"ok": True, "name": call.name, "result": result, "snapshotted": snapshotted}
```

`backend/agent/loop.py` — helper next to `_finish_status`:

```python
    def _scene_changed(self) -> bool:
        return getattr(self.dispatcher, "edits_applied", 0) > 0
```

Thread it through all three emissions:
- `loop.py:486`: `await self._emit(ev_complete("answered", answer=text, scene_changed=self._scene_changed()))`
- `_finish_status`: `await self._emit(ev_complete(status, scene_changed=self._scene_changed()))`
- `_finish_error`: `await self._emit(ev_complete(status, error=error, scene_changed=self._scene_changed()))`

Also reset the counter per run — in `AgentLoop.run()` alongside the other per-run resets (after `self._result = LoopResult(status="running")`):

```python
        if hasattr(self.dispatcher, "edits_applied"):
            self.dispatcher.edits_applied = 0
```

- [ ] **Step 4: Run the agent suite**

Run: `pytest backend/agent/tests/ -x -q`
Expected: PASS. If any test compares a full `complete` dict by equality, add `"scene_changed": <expected>` to its expectation.

- [ ] **Step 5: Commit**

```bash
git add backend/agent/types.py backend/agent/dispatch.py backend/agent/loop.py backend/agent/tests/test_scene_changed.py
git commit -m "feat(agent): complete events report scene_changed so read-only runs don't trigger a reload"
```

---

### Task 5: Frontend — completion-gated reload that keeps the camera (P1)

`src/App.tsx:512-516` reloads on EVERY non-error complete, and `loadSplat` unconditionally reframes (`SceneManager.ts:709`). Gate on `scene_changed` and make authoritative reloads keep the operator's pose (this also stops undo/redo from yanking the camera).

**Files:**
- Modify: `src/backend/trace.ts` (sceneChanged helper), `src/App.tsx:285-293,512-516` (gate + keepCamera), `src/types/viewer.ts:65` (loadSplat opts), `src/viewer/SceneManager.ts:681-714` (honor keepCamera), `src/viewer/ViewerCanvas.tsx:66` (pass-through)
- Test: `src/backend/trace.test.ts`

**Interfaces:**
- Produces: `sceneChanged(detail: Record<string, unknown> | undefined): boolean`; `ViewerHandle.loadSplat(url: string, opts?: { keepCamera?: boolean }): Promise<void>`.

- [ ] **Step 1: Write the failing test** (append to `src/backend/trace.test.ts`)

```ts
describe('sceneChanged (completion-gated reload)', () => {
  it('is true only when the payload explicitly records a backend edit', () => {
    expect(sceneChanged({ scene_changed: true })).toBe(true)
    expect(sceneChanged({ scene_changed: false })).toBe(false)
    expect(sceneChanged({})).toBe(false)        // absent field: never reload-yank
    expect(sceneChanged(undefined)).toBe(false)
  })
})
```

(Add `sceneChanged` to the existing import from `./trace`.)

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- --run src/backend/trace.test.ts`
Expected: FAIL — `sceneChanged` not exported.

- [ ] **Step 3: Implement**

`src/backend/trace.ts`:

```ts
/** True when a `complete` payload records a real backend edit this run.
 *  Gates the authoritative reload: reloading reframes the scene, and a
 *  read-only survey must not yank the operator's camera the moment it ends. */
export function sceneChanged(detail: Record<string, unknown> | undefined): boolean {
  return detail?.scene_changed === true
}
```

`src/types/viewer.ts:65`: `loadSplat(url: string, opts?: { keepCamera?: boolean }): Promise<void>`

`src/viewer/ViewerCanvas.tsx:66`: `loadSplat: (url, opts) => mgr().loadSplat(url, opts),`

`src/viewer/SceneManager.ts` — signature `async loadSplat(url: string, opts?: { keepCamera?: boolean }): Promise<void>` and replace the `this.frameScene()` call (line 709):

```ts
      if (opts?.keepCamera) {
        // Authoritative reload of the SAME scene: hold the operator's pose.
        // Still refresh the core cache — the alive set may have changed.
        this.cacheSceneCore()
      } else {
        this.frameScene()
      }
```

`src/App.tsx` — `reloadAuthoritative` keeps the camera:

```ts
  const reloadAuthoritative = useCallback(async (sceneId: string) => {
    await viewerRef.current?.loadSplat(scenePlyUrl(sceneId), { keepCamera: true })
    ...
```

`src/App.tsx` `processTrace` complete-branch — import `sceneChanged` from `./backend/trace` and gate:

```ts
        // Reload the served .ply ONLY when the run actually edited the backend
        // model (scene_changed) — a read-only survey must not reload/reframe.
        if (!hadError && sceneIdRef.current && sceneChanged(e.detail)) {
          void reloadAuthoritative(sceneIdRef.current)
        }
```

- [ ] **Step 4: Run gates**

Run: `npm test -- --run src/ && npx tsc --noEmit && npm run lint`
Expected: PASS.

- [ ] **Step 5: Manual verification note** (record result in the commit body if run)

Understand-stage survey → camera must NOT move when the run completes. Clean-stage run with an approved edit → splat count updates AND the camera stays where the operator left it.

- [ ] **Step 6: Commit**

```bash
git add src/backend/trace.ts src/backend/trace.test.ts src/App.tsx src/types/viewer.ts src/viewer/SceneManager.ts src/viewer/ViewerCanvas.tsx
git commit -m "fix(app): reload the authoritative scene only after real edits, preserving the operator's camera"
```

---

### Task 6: Coverage percept gains `in_view`; framing frames the same core (P1)

`sceneCoverage` is pure distance — facing away still reads "well framed" (`frontend/src/agent/camera.ts:132`). And `computeFraming` still frames the 5/95 box while the percept uses the median/80th core, so the two disagree.

**Files:**
- Modify: `frontend/src/agent/camera.ts` (coreInView), `frontend/src/agent/executors.ts:318-348` (percept), `frontend/src/agent/types.ts:68-78` (PerceptTag), `src/viewer/framing.ts:158-196` (computeFraming), `backend/agent/system_prompt.py:159-161,235-237` (both coverage stanzas)
- Test: `frontend/src/agent/camera.test.ts`, `src/viewer/framing.test.ts`

**Interfaces:**
- Produces: `coreInView(camera: THREE.PerspectiveCamera, core: { center: [number,number,number]; radius: number } | null): boolean`; `PerceptTag.in_view: boolean`.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/agent/camera.test.ts`:

```ts
describe('coreInView (direction-aware coverage companion)', () => {
  const core = { center: [0, 0, 0] as [number, number, number], radius: 1 }
  function cam(pos: [number, number, number], look: [number, number, number]): THREE.PerspectiveCamera {
    const c = new THREE.PerspectiveCamera(60, 1.6)
    c.position.set(...pos)
    c.lookAt(new THREE.Vector3(...look))
    c.updateMatrixWorld()
    return c
  }

  it('true when the camera faces the core', () => {
    expect(coreInView(cam([0, 0, 10], [0, 0, 0]), core)).toBe(true)
  })
  it('false when the core is behind the camera (coverage alone still reads well-framed)', () => {
    expect(coreInView(cam([0, 0, 10], [0, 0, 20]), core)).toBe(false)
  })
  it('false when the core is outside the frustum', () => {
    expect(coreInView(cam([0, 0, 10], [30, 0, 10]), core)).toBe(false)
  })
  it('false with no core', () => {
    expect(coreInView(cam([0, 0, 10], [0, 0, 0]), null)).toBe(false)
  })
})
```

(Add `coreInView` to the import from `./camera.ts`.)

Append to `src/viewer/framing.test.ts`:

```ts
import * as THREE from 'three'
import { sceneCoverage } from '../../frontend/src/agent/camera.ts'

describe('computeFraming agrees with the coverage percept', () => {
  it('frames the median/80th core: the framed pose reads well-framed, aimed at the dense mass', () => {
    let seed = 42
    const rand = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 2 ** 32 }
    const pts: { x: number; y: number; z: number }[] = []
    for (let i = 0; i < 900; i++) pts.push({ x: rand() * 2 - 1, y: rand() * 2 - 1, z: rand() * 2 - 1 })
    for (let i = 0; i < 100; i++) {
      const r = 80 + rand() * 400
      const u = rand() * 2 - 1
      const phi = rand() * 2 * Math.PI
      const s = Math.sqrt(1 - u * u)
      pts.push({ x: r * s * Math.cos(phi), y: r * u, z: r * s * Math.sin(phi) })
    }
    const fov = 60
    const framing = computeFraming(pts, fov, 1.6)!
    const core = computeCoreBounds(pts)!
    const cov = sceneCoverage(new THREE.Vector3(...framing.position), fov, core)
    expect(cov).toBeGreaterThan(0.3)   // not a speck in the void
    expect(cov).toBeLessThan(0.85)     // not buried in the mass
    const dTarget = Math.hypot(
      framing.target[0] - core.center[0],
      framing.target[1] - core.center[1],
      framing.target[2] - core.center[2],
    )
    expect(dTarget).toBeLessThan(1e-9) // aimed at the dense-mass center, not the box midpoint
  })
})
```

(Ensure `computeCoreBounds` is in the existing import from `./framing`.)

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- --run frontend/src/agent/camera.test.ts src/viewer/framing.test.ts`
Expected: FAIL — `coreInView` not exported; framing coverage far below 0.3 on the floater scene (5/95 box distance) and target ≠ core center.

- [ ] **Step 3: Implement**

`frontend/src/agent/camera.ts` (after `sceneCoverage`):

```ts
/**
 * Is the scene core in front of the camera and inside the frustum?
 * `coverage` is pure distance — it reads "well framed" even facing away from
 * the scene. The capture percept pairs it with this flag so the model knows
 * when the number is meaningless and it should turn toward the scene first.
 */
export function coreInView(
  camera: THREE.PerspectiveCamera,
  core: { center: [number, number, number]; radius: number } | null,
): boolean {
  if (!core || core.radius <= 0) return false
  const center = new THREE.Vector3(core.center[0], core.center[1], core.center[2])
  camera.updateMatrixWorld()
  const inCam = center.clone().applyMatrix4(camera.matrixWorldInverse)
  if (inCam.z >= 0) return false // behind the camera plane
  const ndc = center.clone().project(camera)
  return Math.abs(ndc.x) <= 1.1 && Math.abs(ndc.y) <= 1.1 // small margin off-center
}
```

`frontend/src/agent/types.ts` `PerceptTag` — add after `coverage`:

```ts
  /** False when the scene core is behind the camera or outside the frustum —
   *  coverage is meaningless then; turn toward the scene before judging zoom. */
  in_view: boolean
```

`frontend/src/agent/executors.ts` `capture_frame` — import `coreInView`, and build the percept as:

```ts
    const cam = this.bridge.getCamera()
    const coverage = sceneCoverage(position.clone(), cam.fov, this.bridge.getSceneCore())
    const percept: PerceptTag = {
      position: [position.x, position.y, position.z],
      target: [target.x, target.y, target.z],
      revision: this.bridge.getSceneRevision(),
      coverage: Math.round(coverage * 100) / 100,
      in_view: coreInView(cam, this.bridge.getSceneCore()),
    }
```

`src/viewer/framing.ts` `computeFraming` — frame the SAME core the percept measures:

```ts
export function computeFraming(
  points: readonly Vec3[],
  fovYDeg: number,
  aspect: number,
  azimuthDeg = 35,
): Framing | null {
  if (points.length < 2) return null
  const b = robustBounds(points)
  const core = computeCoreBounds(points)
  if (!b || !core) return null

  const [cx, cy, cz] = core.center // aim at the dense mass, not the box midpoint
  const horizontal = Math.hypot(b.ex, b.ez)
  const vertical = b.ey
  const ratio = horizontal > 1e-6 ? vertical / horizontal : 1

  // Flat/wide scenes (small ratio) get a high elevation so the ground plane
  // isn't viewed edge-on; tall scenes (large ratio) get a low elevation.
  const elevationDeg = clamp(35 + 22 * (1 - ratio), 22, 55)
  const elevation = elevationDeg * DEG
  const azimuth = azimuthDeg * DEG

  // Frame the SAME core sphere the agent's coverage percept measures
  // (computeCoreBounds): the 80th-percentile radius is tighter than the old
  // 5/95 half-diagonal, so pad more (1.5 vs 1.15) to land inside the
  // percept's well-framed band (~0.4-0.7) instead of edge-to-edge.
  const boundingRadius = Math.max(core.radius, 1e-3)
  const vfov = fovYDeg * DEG
  const hfov = 2 * Math.atan(Math.tan(vfov / 2) * aspect)
  const limitingFov = Math.min(vfov, hfov)
  const distance = (boundingRadius / Math.sin(limitingFov / 2)) * 1.5

  const dir = {
    x: Math.cos(elevation) * Math.sin(azimuth),
    y: Math.sin(elevation),
    z: Math.cos(elevation) * Math.cos(azimuth),
  }

  return {
    target: [cx, cy, cz],
    position: [cx + dir.x * distance, cy + dir.y * distance, cz + dir.z * distance],
  }
}
```

`backend/agent/system_prompt.py` — in BOTH stanzas (~line 160 and ~line 236), after the sentence ending `above ~0.9 too close (back off).` insert:

```
Each capture also reports `in_view`: when false the scene core is off-screen
  or behind you — coverage means nothing then; turn toward the scene first.
```

- [ ] **Step 4: Run gates**

Run: `npm test -- --run frontend/src/agent/ src/viewer/ && npx tsc --noEmit && npm run lint`
Expected: PASS — if existing framing tests pinned the old box-midpoint target or 1.15 distance, update those expectations to the core-sphere behavior (that change is the point of this task).
Run: `pytest backend/agent/tests/test_analyst_prompt.py backend/agent/tests/test_cleanup_prompt.py -x -q`
Expected: PASS (prompt-content tests may assert on the coverage stanza; extend, don't fight).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/agent/camera.ts frontend/src/agent/camera.test.ts frontend/src/agent/executors.ts frontend/src/agent/types.ts src/viewer/framing.ts src/viewer/framing.test.ts backend/agent/system_prompt.py
git commit -m "fix(agent): direction-aware in_view percept + frame the same median/80th core the coverage percept measures"
```

---

### Task 7: Loop — capture is a perception barrier; Stop/Pause honored BEFORE actions (P1)

`loop.py:159-165` executes a whole tool-call batch: actions queued after a capture run blind (the frame reaches the model only on the NEXT generate), and pause/interrupt is checked only after each call.

**Files:**
- Modify: `backend/agent/loop.py:159-165` (batch loop), `loop.py:31-40` (import VISION_TOOLS from `.types`)
- Test: `backend/agent/tests/test_capture_barrier.py` (new)

**Interfaces:**
- Consumes: `VISION_TOOLS` from `backend/agent/types.py:34`.
- Produces: after a capture with queued calls remaining, the loop drops the rest of the batch and feeds back `[system] capture taken — dropped N queued action(s) (...)`.

- [ ] **Step 1: Write the failing test** (`backend/agent/tests/test_capture_barrier.py`)

```python
"""capture_frame must be a perception barrier: tool calls queued after a
capture in the same model response would run blind (the frame reaches the
model only on the NEXT generate), so the loop drops them and says so. And
Stop/Pause must be honored BEFORE an action executes, not one action late."""

from __future__ import annotations

import asyncio

from backend.agent import AgentLoop, ToolDispatcher
from backend.agent.mocks import MockBackendExecutor, MockFrontendChannel, MockProvider, text_then_tools, tool_turn


def _run(coro):
    return asyncio.run(coro)


def test_calls_after_a_capture_in_the_same_batch_are_dropped():
    channel = MockFrontendChannel()
    provider = MockProvider([
        text_then_tools(
            "Capturing, then moving.",
            ("capture_frame", {}),
            ("move_camera", {"direction": "forward", "duration_ms": 400}),
            ("turn", {"direction": "left", "duration_ms": 300}),
        ),
        tool_turn(("answer", {"text": "done"})),
    ])
    loop = AgentLoop(provider, ToolDispatcher(MockBackendExecutor(), channel), channel, stage="understand")
    _run(loop.run("survey"))

    types = [c.get("type") for c in channel.commands]
    assert types.count("capture_request") == 1
    assert "movement_input" not in types, "post-capture moves must not run blind"
    assert "rotation_input" not in types
    note = [m for m in loop._messages if "dropped 2 queued action(s)" in str(m.get("content", ""))]
    assert note, "the model must be told its queued actions were dropped"


def test_interrupt_is_honored_before_the_first_action():
    class InterruptedChannel(MockFrontendChannel):
        def __init__(self):
            super().__init__()
            self._flag = True

        @property
        def interrupted(self) -> bool:  # consume-once, like the real channel
            v = self._flag
            self._flag = False
            return v

    channel = InterruptedChannel()
    provider = MockProvider([
        tool_turn(("move_camera", {"direction": "forward", "duration_ms": 400})),
    ])
    loop = AgentLoop(provider, ToolDispatcher(MockBackendExecutor(), channel), channel, stage="understand")
    result = _run(loop.run("survey"))

    assert result.status == "interrupted"
    assert "movement_input" not in [c.get("type") for c in channel.commands], (
        "Stop must prevent the NEXT action, not fire one more"
    )
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest backend/agent/tests/test_capture_barrier.py -x -v`
Expected: FAIL — movement_input present in both tests.

- [ ] **Step 3: Implement** (`backend/agent/loop.py`)

Add `VISION_TOOLS` to the existing `from .types import (...)` block. Replace the batch loop (lines 159-165):

```python
            calls = list(response.tool_calls)
            for idx, call in enumerate(calls):
                # Honor Stop/Pause BEFORE the action, not one action late.
                verdict = await self._pause_checkpoint()
                if verdict:
                    return await self._finish_status(verdict)
                returned = await self._handle_call(call, step)
                if returned:  # answer() fired
                    return self._result
                # Perception barrier: anything queued after a capture in this
                # same response would execute before the model ever sees the
                # frame. Drop the tail and tell the model why.
                if call.name in VISION_TOOLS and idx < len(calls) - 1:
                    dropped = [c.name for c in calls[idx + 1:]]
                    self._nudge_sync(
                        f"capture taken — dropped {len(dropped)} queued action(s) "
                        f"({', '.join(dropped)}): look at the frame before acting again."
                    )
                    break
            verdict = await self._pause_checkpoint()
            if verdict:
                return await self._finish_status(verdict)
```

- [ ] **Step 4: Run the agent suite**

Run: `pytest backend/agent/tests/ -x -q`
Expected: PASS. Existing scripted tests that batch actions AFTER a capture in one turn (check `test_loop.py`, `test_closed_loops.py`, `test_proposals.py`) must be split into separate turns — the barrier is the new intended behavior, so adjust the scripts, not the loop.

- [ ] **Step 5: Commit**

```bash
git add backend/agent/loop.py backend/agent/tests/test_capture_barrier.py
git commit -m "fix(agent): make capture a perception barrier and honor stop/pause before each action"
```

---

### Task 8: Provider timeout parity — Gemini + Anthropic (P2 quick win)

The 120s bounded timeout exists only on the OpenAI client. Mirror it (same rationale comment style as `openai.py:67-75`).

**Files:**
- Modify: `backend/providers/gemini.py:50-64`, `backend/providers/anthropic.py:45-57`
- Test: `backend/providers/tests/test_gemini_timeout.py`, `backend/providers/tests/test_anthropic_timeout.py` (new)

- [ ] **Step 1: Write the failing tests**

`backend/providers/tests/test_anthropic_timeout.py`:

```python
"""Same rationale as test_openai_timeout: a wedged connection must surface as
a provider error within ~2 minutes, not hang for the SDK's 10-minute default."""
import pytest

pytest.importorskip("anthropic")

from backend.providers.anthropic import AnthropicProvider


def test_client_timeout_and_retries_are_bounded():
    provider = AnthropicProvider(model="m", api_key="k")
    client = provider._get_client()
    t = client.timeout
    assert t is not None, "client must not use the SDK's unbounded default"
    for phase in ("connect", "read", "write", "pool"):
        v = getattr(t, phase)
        assert v is not None and v <= 180, f"{phase} timeout too long: {v}"
    assert client.max_retries <= 1
```

`backend/providers/tests/test_gemini_timeout.py`:

```python
"""Gemini path of the bounded-timeout rule (see test_openai_timeout)."""
import pytest

genai = pytest.importorskip("google.genai")

from backend.providers.gemini import GeminiProvider


def test_client_carries_bounded_timeout(monkeypatch):
    captured: dict = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(genai, "Client", FakeClient)
    provider = GeminiProvider(model="m", api_key="k")
    provider._get_client()
    opts = captured.get("http_options")
    assert opts is not None, "client must set http_options with a bounded timeout"
    assert opts.timeout is not None and opts.timeout <= 180_000  # milliseconds
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest backend/providers/tests/test_gemini_timeout.py backend/providers/tests/test_anthropic_timeout.py -x -v`
Expected: FAIL (or SKIP if an SDK is not installed in `.venv-api` — install it or accept the skip and note it).

- [ ] **Step 3: Implement**

`backend/providers/gemini.py` `_get_client` — replace the client construction:

```python
        from google.genai import types  # type: ignore

        # Bounded timeout (ms): mirrors openai.py — the SDK default turns a
        # half-dead tunnel into a multi-minute silent hang inside `generate`.
        self._client = genai.Client(
            api_key=self.api_key,
            http_options=types.HttpOptions(timeout=120_000),
        )
```

`backend/providers/anthropic.py` `_get_client` — replace the client construction:

```python
        import httpx  # anthropic's own transport dep, always present with it

        # Bounded timeout: mirrors openai.py — a wedged socket must surface as
        # a provider error within ~2 minutes. Retries are with_retry's job.
        self._client = anthropic.Anthropic(
            api_key=self.api_key,
            timeout=httpx.Timeout(120.0, connect=10.0),
            max_retries=0,
        )
```

- [ ] **Step 4: Run the provider suite**

Run: `pytest backend/providers/tests/ -x -q`
Expected: PASS (skips acceptable only for uninstalled SDKs).

- [ ] **Step 5: Commit**

```bash
git add backend/providers/gemini.py backend/providers/anthropic.py backend/providers/tests/test_gemini_timeout.py backend/providers/tests/test_anthropic_timeout.py
git commit -m "fix(providers): bounded timeouts for Gemini and Anthropic to match the OpenAI client"
```

---

### Task 9: System prompt sent once, not twice (P2 quick win)

`RealAgentRunner` hands the prompt to the provider as `system_instruction` (`real_engine.py:207`) while `AgentLoop` ALSO seeds `messages[0]` with the same text (`loop.py:113-114`) — providers send it twice. Make the provider the single owner on the real path.

**Files:**
- Modify: `backend/agent/loop.py:112-118` (skip empty system prompt), `loop.py:217` (seed insert position), `backend/api/real_engine.py:209`
- Test: `backend/agent/tests/test_system_prompt_dedup.py` (new)

**Interfaces:**
- Produces: `AgentLoop(..., system_prompt="")` seeds NO system message (provider carries it); default behavior (None) unchanged.

- [ ] **Step 1: Write the failing test** (`backend/agent/tests/test_system_prompt_dedup.py`)

```python
"""The system prompt must reach the provider exactly once. RealAgentRunner
passes it as the provider's system_instruction; with system_prompt="" the loop
must not ALSO seed messages[0] with the same text."""

from __future__ import annotations

import asyncio

from backend.agent import AgentLoop, ToolDispatcher
from backend.agent.mocks import MockBackendExecutor, MockFrontendChannel, MockProvider, tool_turn


def _run(coro):
    return asyncio.run(coro)


class RecordingProvider(MockProvider):
    def __init__(self, script):
        super().__init__(script)
        self.seen: list[list[dict]] = []

    def generate(self, messages, tools, images=None):
        self.seen.append([dict(m) for m in messages])
        return super().generate(messages, tools, images)


def _drive(system_prompt):
    channel = MockFrontendChannel()
    provider = RecordingProvider([tool_turn(("answer", {"text": "ok"}))])
    loop = AgentLoop(
        provider, ToolDispatcher(MockBackendExecutor(), channel), channel,
        stage="understand", system_prompt=system_prompt,
    )
    _run(loop.run("hello"))
    return [m["role"] for m in provider.seen[0]]


def test_empty_system_prompt_seeds_no_system_message():
    roles = _drive("")
    assert "system" not in roles


def test_default_still_seeds_exactly_one_system_message_first():
    roles = _drive(None)
    assert roles.count("system") == 1 and roles[0] == "system"
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest backend/agent/tests/test_system_prompt_dedup.py -x -v`
Expected: FAIL — empty-prompt case still contains a system role (empty content).

- [ ] **Step 3: Implement**

`backend/agent/loop.py` `run()` — replace the message seeding:

```python
        self._messages = []
        if self.system_prompt:
            self._messages.append({"role": "system", "content": self.system_prompt})
        self._messages.append({"role": "user", "content": prompt})
```

`_seed_grounding` — the insert position assumed `messages[0]` is system; make it explicit (replace `self._messages.insert(1, ...)`):

```python
        pos = 1 if self._messages and self._messages[0].get("role") == "system" else 0
        self._messages.insert(pos, {"role": "user", "content": msg})
```

`backend/api/real_engine.py:209`:

```python
        # The provider carries the system prompt natively (system_instruction
        # above); an empty system_prompt stops the loop from ALSO seeding
        # messages[0] with the same text — providers were sending it twice.
        loop = AgentLoop(provider, dispatcher, channel, stage=resolved, system_prompt="")
```

- [ ] **Step 4: Run the backend suites**

Run: `pytest backend/agent/tests/ backend/api/tests/ -x -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/agent/loop.py backend/api/real_engine.py backend/agent/tests/test_system_prompt_dedup.py
git commit -m "fix(agent): send the system prompt once — provider owns it on the real path"
```

---

### Final Checkpoint

- [ ] Full backend gate: `pytest` (repo root, venv active) — green.
- [ ] Full frontend gate: `npm test -- --run && npx tsc --noEmit && npm run lint && npm run build` — green.
- [ ] Manual smoke (needs backend + browser): survey run ends without camera movement; killing the backend mid-run shows "Agent connection lost" instead of an eternal spinner; a cleanup run's narrate/marker steps visibly work.
- [ ] `.claude/settings.json` and `tasks/` left uncommitted.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Capture-barrier breaks existing scripted tests that batch post-capture actions | Med | Task 7 Step 4 explicitly splits those scripts into separate turns — the barrier is the new contract |
| `/agent/run` 409 breaks other API tests that never connect a WS | Med | Task 2 Step 5 sweeps `backend/api/tests/` and connects a `FakeRenderer` where needed |
| New framing distance (1.5× core radius) changes the default view aesthetics | Low | The framing test pins the coverage band [0.3, 0.85]; manual look at `examples/messy.ply` confirms |
| `scene_changed` key breaks dict-equality asserts on `complete` events | Low | Task 4 Step 4 runs the suite and updates expectations |
| Older backend without `scene_changed` + new frontend → reload never fires | Low | Intentional fail-safe: no reload means no camera yank; both sides ship together on this branch |
