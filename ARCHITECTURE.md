# GeoSplat Inspector — ARCHITECTURE.md (shared context for all agents)

> **Read this first, fully, before writing any code.** This is the shared constitution for every agent on this project. It defines the architecture, the locked decisions, and — critically — the **contracts** (interfaces, schemas, constants) that every agent builds against. You may freely change anything *inside your assigned boundary*. You must **never** change anything in `/backend/contracts/` or `/frontend/src/contracts.ts` or anything outside your boundary. If a contract is wrong, STOP and raise it; do not edit it unilaterally.

---

## 1. What we are building

GeoSplat Inspector is a local tool where an **AI agent autonomously inspects, navigates, and cleans up 3D Gaussian Splatting (`.ply`) scenes**, showing its work visibly as it goes (it flies around like a robot inspector, pauses to scan, drops markers, narrates, and edits the scene with undo). The `.ply` already loads and renders. We are building the **agent and its backend**, not the renderer, not the generation pipeline, not the final polished UI.

**North star:** impressive demo video + clean open-source project a peer can `docker compose up` and run.

---

## 2. Locked decisions (do not relitigate)

1. **Python backend** owns: the splat data, metrics, editing, model providers, and the agent loop. **Thin TypeScript/React + Three.js/Spark frontend** renders the scene, captures frames, shows UI. They communicate over a local API (REST + WebSocket).
2. **No NVIDIA GPU.** Python cannot render splats (gsplat needs CUDA). Therefore **the browser is the renderer AND the agent's eyes**: the agent gets visual input by asking the frontend to capture its canvas and send the frame back. The Docker image is **CPU-only**.
3. **Model-agnostic.** The agent loop talks to a `ModelProvider` interface, never a vendor SDK. **Gemini Flash is the default** (free tier); Claude/OpenAI/local are drop-in adapters.
4. **Real-time live editing is NOT required.** "Apply edit, re-render a moment later" is fine, so render-sync is just re-serving the edited scene.
5. **Local-only, open-sourced.** Optimize for portability and a peer running it on a laptop, not hosting or scale.

---

## 3. Design principles (override any local decision)

1. **Deterministic-first.** Core capabilities are exact, O(N), repeatable numpy/Open3D operations. No training/optimization/generative models in the core.
2. **Reference-free.** No ground-truth images. Quality is judged from parameter-space metrics + multi-view self-consistency. Never assume PSNR/SSIM/LPIPS.
3. **Reversible.** Every destructive op snapshots first. The agent can always undo.
4. **Visible and verified.** Every action is legible to a watching human (paced moves, markers, narration, trace). Every edit is followed by a verify step that confirms improvement or rolls back.
5. **Swappable seams.** Rendering is behind `capture_frame`; the model is behind `ModelProvider`. Either can change without touching the loop.

---

## 4. System architecture

```
┌──────────────── BROWSER (thin · TypeScript · /frontend) ────────────────┐
│ Three.js + Spark renderer · owns the camera · renders the .ply           │
│ CAPTURES frames on request (canvas.toBlob, preserveDrawingBuffer:true)   │
│ shows: capabilities launcher · metrics panel · trace · narration         │
│ applies edited scene when backend re-serves it                           │
└─────────────┬─────────────────────────────────────────┬──────────────────┘
              │ REST: upload, metrics, edit, fetch .ply   │ WebSocket (bidir)
              │                                           │  ↓ camera/capture/marker cmds
              │                                           │  ↑ frame bytes
              │                                           │  ↓ trace/narration events
              ▼                                           ▼
┌──────────────── PYTHON BACKEND (FastAPI · CPU-only · /backend) ──────────┐
│ AGENT LOOP (perceive→act→verify) ── ModelProvider → Gemini│Claude│OpenAI  │
│ TOOL DISPATCH (runs_on routing):                                         │
│   backend-local: get_metrics, edits, snapshot/undo, export               │
│   frontend (WS round-trip): camera moves, capture, markers, narrate      │
│ ANALYSIS: metrics engine + editing engine (numpy + Open3D-as-mask)       │
│ SPLAT DATA: plyfile loader → numpy arrays → alive mask → INRIA exporter  │
└────────────────────────────────────────────────────────────────────────────┘
```

### 4.1 The backend/frontend tool split (the crux of the no-GPU design)

Because rendering only exists in the browser, tools execute on one of two sides, marked by a `runs_on` flag in the tool contract:

- **`runs_on: "backend"`** — operate on the numpy arrays, run instantly, locally: `get_metrics`, `list_problem_regions`, all edit ops, `snapshot`/`undo`/`redo`, `export_ply`.
- **`runs_on: "frontend"`** — need the renderer, so the backend sends a command over WebSocket and **awaits** the result: `look_at`, `set_view`, `orbit`, `dolly`, `scan_pause`, `frame_object`, `reset_view`, `capture_frame`, `capture_orbit`, and display-only `drop_marker`, `clear_markers`, `narrate`, `reset_trail`.

The agent loop calls tools uniformly; the **dispatcher** decides where each runs. The loop does not know or care which side executes — this is hidden behind the dispatcher and the `FrontendChannel` interface (§6.5).

### 4.2 Render-for-vision flow

Agent calls `look_at` then `capture_frame` → dispatcher sends both over WS → frontend animates camera (paced), waits for depth-sort to settle, captures via `canvas.toBlob()` → sends PNG back → backend passes it to the `ModelProvider` as an image → model reasons.

### 4.3 Render-sync flow

After a backend edit mutates the `alive` mask, backend re-serves `GET /scene/{id}.ply`; frontend reloads it into Spark. (Optimization for later: send only changed indices. Not in v1.)

---

## 5. Repository layout & ownership

```
/backend
  /contracts        ← FROZEN. Shared schemas, interfaces, constants. (Phase 0)
  /splat            ← AGENT 1: loader, numpy model, alive mask, exporter, spatial queries
  /analysis         ← AGENT 2: metrics engine + editing engine + selection + history
  /agent            ← AGENT 3: perceive→act→verify loop, tool dispatch, closed loops
  /providers        ← AGENT 3: ModelProvider interface impls (Gemini default, stubs)
  /api              ← AGENT 4: FastAPI REST + WebSocket server + scene serving + state
  server.py         ← AGENT 4: app entrypoint
/frontend
  /src/contracts.ts ← FROZEN. TS mirror of the API + WS + tool contract. (Phase 0)
  /src/agent        ← AGENT 5: WS client, frontend tool executors, panels wiring
/examples
  clean.ply         ← sample scene (Phase 0)
  messy.ply         ← deliberately noisy scene with floaters/outliers (Phase 0)
CLAUDE.md           ← build/lint/test commands + boundaries (Phase 0)
Dockerfile, docker-compose.yml  ← CPU-only (Phase 0 skeleton, Agent 4 finalizes)
```

**Boundary rule:** an agent edits only its own folder(s). It *imports* from `/backend/contracts` (or `/frontend/src/contracts.ts`) and from already-published sibling modules, but never edits them. Cross-boundary needs that aren't covered by a contract are a STOP-and-raise event.

---

## 6. THE CONTRACTS (frozen in Phase 0; everyone builds against these)

### 6.1 The Gaussian `.ply` layout

Per-Gaussian, INRIA standard, SH degree 3 = 59 floats, header order:
`x,y,z` · `nx,ny,nz` (unused) · `f_dc_0..2` · `f_rest_0..44` · `opacity` · `scale_0..2` · `rot_0..3`.

Stored values are NOT render values:
- opacity: **logit** → `sigmoid(x)`; inverse `log(p/(1-p))`
- scale: **log space** → `exp(x)`; inverse `log(x)`
- rotation: **unnormalized quaternion (w,x,y,z)** → L2-normalize
- color DC → RGB: `0.5 + C0 * f_dc`, `C0 = 0.28209479177387814`; inverse `(rgb-0.5)/C0`

Auto-detect field set from the header. Count `f_rest_*`: 9→deg1, 24→deg2, 45→deg3. SH layout is channel-grouped (planar): all coeffs of one channel contiguous, then the next.

### 6.2 Shared constants (`/backend/contracts/constants.py`, mirrored in TS)

```
SH_C0               = 0.28209479177387814
FLOATER_ALPHA       = 0.05     # opacity threshold for floater pruning
VISIBILITY_ALPHA    = 0.10     # "near-transparent" cutoff for metrics
OUTLIER_K           = 16       # k for k-NN distance
OUTLIER_STD_RATIO   = 2.0      # statistical outlier threshold (mean + ratio*std)
NEEDLE_RATIO        = 10.0     # axis-ratio cutoff for needle detection
OVERSIZED_SCENE_FRAC= 0.05     # max axis as fraction of scene diagonal
HIST_BINS           = 50
UNDO_STACK_MAX      = 50
```

### 6.3 `SplatModel` interface (Agent 1 implements; Agents 2 & 3 import)

```python
class SplatModel:
    # parallel numpy arrays, indexed by Gaussian id (raw/stored values)
    means: np.ndarray         # (N,3) float32
    scales_raw: np.ndarray    # (N,3) log-space
    quats: np.ndarray         # (N,4) wxyz, unnormalized
    opacity_raw: np.ndarray   # (N,)  logit
    f_dc: np.ndarray          # (N,3)
    f_rest: np.ndarray        # (N,K) K depends on sh_degree
    alive: np.ndarray         # (N,)  bool   ← soft-delete mask
    sh_degree: int

    @classmethod
    def load(cls, path: str) -> "SplatModel": ...
    def export(self, path: str) -> None       # writes valid INRIA .ply of alive Gaussians
    def alive_indices(self) -> np.ndarray
    def apply_mask(self, keep: np.ndarray) -> None   # AND `keep` into alive
    # activated accessors (computed on demand, alive-only by default)
    def opacity(self, alive_only=True) -> np.ndarray   # sigmoid
    def scale(self, alive_only=True) -> np.ndarray     # exp
    def color(self, alive_only=True) -> np.ndarray     # 0.5 + C0*f_dc
    # spatial (built lazily over alive positions; rebuilt on alive change)
    def knn(self, k: int) -> tuple[np.ndarray, np.ndarray]  # (dist (M,k), idx (M,k))
    def bounds(self) -> tuple[np.ndarray, np.ndarray]       # (min(3,), max(3,))
```

### 6.4 `Metrics` schema (Agent 2 produces; Agent 3 & frontend consume)

```python
Metrics = {
  "gaussianCount": int,
  "opacity": {"histogram": list[int], "nearTransparentFraction": float, "mean": float, "median": float},
  "scale":   {"histogram": list[int], "oversizedFraction": float,
              "axisRatio": {"histogram": list[int], "needleFraction": float}},
  "spatial": {"nnDistance": {"mean": float, "std": float, "histogram": list[int]},
              "outlierFraction": float, "density": float},
  "bounds":  {"min": [float,float,float], "max": [float,float,float], "volume": float},
  "color":   {"dcMean": [float,float,float], "dcStd": [float,float,float]},
  "computedAt": str, "region": dict | None
}
```
The **outlier criterion** (mean k-NN distance > mean + OUTLIER_STD_RATIO*std) is implemented ONCE in the metrics engine and imported by the editing engine's `remove_outliers`. Never define it twice.

### 6.5 The tool contract (Agent 3 dispatches; Agent 5 executes frontend tools)

Each tool: `name`, `runs_on`, JSON-schema params, return shape. Summary:

| Tool | runs_on | params | returns |
|------|---------|--------|---------|
| `look_at` | frontend | target[3], duration_ms? | ok |
| `set_view` | frontend | position[3], target[3], duration_ms? | ok |
| `orbit` | frontend | center[3], deg, axis, duration_ms? | ok |
| `dolly` | frontend | distance, duration_ms? | ok |
| `scan_pause` | frontend | ms | ok |
| `frame_object` | frontend | bbox, duration_ms? | ok |
| `reset_view` | frontend | — | ok |
| `capture_frame` | frontend | — | image bytes (PNG) |
| `capture_orbit` | frontend | center[3], n, radius? | image bytes[] |
| `drop_marker` | frontend | position[3], label | ok |
| `clear_markers` | frontend | — | ok |
| `narrate` | frontend | text | ok |
| `reset_trail` | frontend | — | ok |
| `get_metrics` | backend | region? | Metrics |
| `list_problem_regions` | backend | — | ranked regions w/ bboxes |
| `opacity_threshold` | backend | min_alpha | before/after counts |
| `remove_outliers` | backend | k, std_ratio | before/after counts |
| `prune_oversized` | backend | max_axis_scene_frac | before/after counts |
| `remove_needles` | backend | max_axis_ratio | before/after counts |
| `crop_bbox` | backend | min[3], max[3] | before/after counts |
| `crop_sphere` | backend | center[3], radius, invert? | before/after counts |
| `recolor` | backend | selection, rgb[3] | ok |
| `adjust_opacity` | backend | selection, factor | ok |
| `truncate_sh` | backend | degree | ok |
| `snapshot` | backend | — | ok |
| `undo` / `redo` | backend | — | ok |
| `export_ply` | backend | — | path |
| `answer` | backend | text | ends run |

Every destructive backend tool MUST snapshot before mutating.

### 6.6 `ModelProvider` interface (Agent 3 implements)

```python
@dataclass
class ToolSpec:    name: str; description: str; parameters: dict
@dataclass
class ToolCall:    name: str; args: dict
@dataclass
class ModelResponse: text: str | None; tool_calls: list[ToolCall]; raw: Any

class ModelProvider(Protocol):
    def generate(self, messages: list[dict], tools: list[ToolSpec],
                 images: list[bytes] | None = None) -> ModelResponse: ...
```
Adapters normalize tool schema, image attachment, and response parsing per vendor. Default `GeminiProvider` uses `google-genai`, `gemini-2.5-flash`. Provider/model chosen via env: `MODEL_PROVIDER`, `MODEL_NAME`.

### 6.7 REST API (Agent 4)

`POST /scene` (load → id+metrics) · `GET /scene/{id}.ply` (chunked serve) · `GET /metrics?region=` · `POST /edit {op,params,selection}` (→ counts+metrics) · `POST /undo` `/redo` · `POST /agent/run {prompt}` (streams over WS).

### 6.8 WebSocket protocol (Agent 4 server, Agent 5 client, Agent 3 loop uses `FrontendChannel`)

Backend→frontend commands: `camera_move`, `capture_request`, `drop_marker`, `clear_markers`, `narrate`, `reload_scene`.
Frontend→backend: `frame` (PNG bytes), `user_interrupt?`.
Backend→frontend trace events: `thought`, `tool_call`, `tool_result`, `complete`.

The loop depends on this interface (implemented by Agent 4, called by Agent 3):
```python
class FrontendChannel(Protocol):
    async def send_command(self, cmd: dict) -> dict   # send + await result (e.g. a frame)
    async def emit_event(self, event: dict) -> None    # fire-and-forget trace/narration
```

---

## 7. Capability tiers

| Tier | What | v1 |
|------|------|----|
| 1 | Navigation & perception (paced camera, capture, markers, trail, narration) | ✓ |
| 2 | Inspection & measurement (all Metrics fields, problem-region ranking) — reference-free | ✓ |
| 3 | Cleanup & editing (opacity/outlier/oversized/needle/crop/recolor/SH-truncate, snapshot/undo, export) | ✓ |
| 4 | Closed loops: detect→fix→verify→keep/undo | ✓ |
| 5 | Semantic/generative (language selection, inpainting, relighting, deformation) | ✗ deferred — agent refuses & flags |

**Flagship loop (floater cleanup):** read metrics → rank problem regions → fly + scan + marker + narrate → snapshot + opacity/outlier removal → re-measure + before/after capture (bad fraction dropped? silhouette intact?) → keep, or undo + loosen + retry once.

---

## 8. Cross-cutting rules (every agent)

- Import shared types/constants from `/backend/contracts` (or `/frontend/src/contracts.ts`); never copy or redefine them.
- The outlier criterion lives only in the metrics engine; the editing engine imports it.
- Every destructive op snapshots first; every edit is reversible.
- Benchmark anything touching all Gaussians on a **real** multi-hundred-K scene (`/examples/messy.ply`), not a toy.
- No secrets in the image or the bundle; keys via env only.
- A task is "done" only when its acceptance test passes **on a real scene**, not when it merely typechecks.
- **Grounding rule:** the agent may only assert what it read from a metric or saw in a captured frame.
- If a request needs Tier-5 work, refuse and flag out-of-scope; do not ship a fragile approximation.

---

## 9. Risk register (know these)

| ID | Risk | Mitigation / owner |
|----|------|--------------------|
| R1 | Black/empty captured frames | `preserveDrawingBuffer:true`, capture after sort settles, opaque clear color · Agent 5 |
| R2 | Invalid PLY export (header order/activation space) | bit-faithful round-trip test · Agent 1 |
| R3 | Outlier defined twice → measure/fix diverge | single criterion in metrics, imported by editing · Agent 2 |
| R4 | Model rate limits stall demo (Gemini free tier low) | frugal vision calls, frame caching, bounded steps; swap provider via interface · Agent 3 |
| R5 | WS round-trip per "look" feels slow | batch metrics into text (backend-local); reserve vision calls for real frames; pacing is also the intended UX · Agent 3 |
| R6 | A task edits a frozen contract | contracts frozen after Phase 0; changes are stop-and-raise · all |
| R7 | Open3D misbehaves headless | used only for CPU array math/queries, not rendering; cKDTree fallback · Agents 1/2 |

---

## 10. Definition of done (whole system)

Data layer load→export bit-faithful; metrics compute reference-free and fast on 500K Gaussians; every edit reversible and `remove_outliers` provably lowers `outlierFraction`; Gemini default works (vision+tools) and providers swap with no loop change; frontend camera animates visibly and returns clean frames; the flagship floater loop runs end to end autonomously with trace + working undo on a real scene; grounding enforced; Tier-5 refused; CPU-only image builds and `docker compose up` runs; README complete; a peer can clone, add a key, and run the flagship loop.
