# /frontend/src/agent — the agent's hands & eyes

Boundary: **this folder only**. It imports the FROZEN `../contracts.ts` and a narrow
`RendererBridge` slice of the existing `ViewerHandle` (injected — never imports renderer
internals). Wraps the existing camera/renderer; does not rewrite them.

## Files
| File | Role |
|------|------|
| `types.ts` | `RendererBridge` (injected renderer slice), `ToolResult`, payloads |
| `camera.ts` | paced, **awaited** tweening + framing/orbit math |
| `overlay.ts` | world-pinned markers + auto breadcrumb trail (`reset_trail`) |
| `capture.ts` | R1-hardened PNG: opaque clear → settle frames → `toBlob` |
| `executors.ts` | the `runs_on:"frontend"` tools (§6.5) |
| `ws-client.ts` | §6.8 protocol: commands in, `frame`/`user_interrupt` out, trace → panels |
| `transport.ts` | `WebSocketTransport` (real) / `LoopbackTransport` (mock) |
| `mock-backend.ts` | in-process scripted inspector for dev |
| `panels.ts` | data wiring: trace/narration/metrics signals + capability catalog |
| `index.ts` | `createAgent(...)` factory |

## Bridge design (how it hooks the existing renderer)
The renderer (root `src/viewer/SceneManager.ts`) gained four **additive** methods on
`ViewerHandle`: `getOverlayGroup()`, `getCamera()`, `getRenderer()`, `renderOnce()`.
The agent layer uses them to (a) host its own marker/trail `Object3D`, (b) set an opaque
clear color + read pixels for capture, (c) drive paced moves via the existing
`setCameraPose(...,animate=false)` snap path per frame (so it owns duration/easing and can
`await` completion). Camera moves are never teleports.

**Coordinate frames:** the splat mesh is Y-flipped (`rotation.x = π`, COLMAP→Three). Markers
arrive in the backend's raw splat frame, so the marker group inherits the same flip and lands
on the Gaussians. The trail traces the camera's **world** path, so it stays unflipped.

## Run against the mock (no server)
```ts
import { createAgent, createMockTransport } from '@/agent' // or relative path
const { transport, backend } = createMockTransport()
const agent = createAgent({ bridge: viewerHandle, transport })
// subscribe panels: agent.panels.trace.subscribe(...), .narration, .metrics
const frames = await backend.runDemoInspection({ reloadUrl: '/examples/clean.ply' })
// frames: base64 PNG data URLs — verify the first is a CLEAN, non-black view (R1)
```

## Run against the real backend
```ts
import { createAgent, WebSocketTransport } from '@/agent'
const t = new WebSocketTransport(wsUrl)
await t.whenOpen()
const agent = createAgent({ bridge: viewerHandle, transport: t })
```

## Coordination notes (not contract edits)
- **§6.8 ack:** the contract lists only `frame`/`user_interrupt` as frontend→backend types,
  but `FrontendChannel.send_command` awaits a result per command. We reply to every command
  with a `type:"frame"` envelope correlated by `id` (payload `{ok:true}` for non-captures).
  Flagged to Agents 3/4.
- **Integration:** the running app currently lives at root `src/`; this module lives under
  `/frontend/src/` per ARCHITECTURE §5. Wiring `createAgent` into `App.tsx`/panels and
  serving `/examples/*.ply` is an integration step (crosses into root `src/`).
