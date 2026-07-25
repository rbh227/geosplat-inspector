# Operator-Edited Crop Box Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the operator a movable, resizable 3D crop box in the editor rail that deletes everything outside it, and let an agent seed that box and crop to the operator's final version.

**Architecture:** A unit-cube `THREE.Mesh` parented to the splat mesh represents the box, so its local transform is already in backend coordinates (the viewer's `mesh.rotation.x = Math.PI` flip is the parent's, not the box's). `TransformControls` drives it in translate/scale modes and suspends orbit only while a handle is being dragged. Box math lives in a pure module so it is unit-testable without a WebGL context. The commit path reuses the existing `keep_only_ids` edit route, so the crop lands in the one shared history and Undo works unchanged.

**Tech Stack:** TypeScript, React, Three.js 0.184 (`three/examples/jsm/controls/TransformControls.js`), SparkJS, Vitest, FastAPI, pytest.

## Global Constraints

- Contracts are mirrored: any change to `backend/contracts/tools.py` requires the same change in `frontend/src/contracts.ts`. Drift guards: `backend/contracts/tests/test_tools.py`, `frontend/src/agent/contracts.test.ts`.
- This phase's contract version is **v0.6**.
- Backend runs on Python 3.12+ via `.venv-api`. Run tests with `.venv-api/bin/python -m pytest`.
- Frontend: `npx vitest run`, `npx tsc --noEmit`, `npm run lint` must all pass. `npm run lint` has one pre-existing warning in `src/App.tsx:172` — that is the baseline, not a regression.
- Box coordinates crossing the WS boundary are **backend coordinates** (mesh-local), matching `show_box_preview`.
- Never compute an exact splat count per animation frame. Scenes reach 2,000,000 splats; use the strided sample for live readouts.
- Every destructive edit goes through `commitEdit` in `src/App.tsx:329` so it records in the backend history.

---

### Task 1: Tool descriptions in the rail

**Files:**
- Modify: `src/ui/EditorToolbar.tsx`
- Test: `src/ui/EditorToolbar.test.tsx` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `TOOLS` entries gain a `description: string` field. Task 4 adds the `cropBox` entry to this same array.

- [ ] **Step 1: Write the failing test**

Create `src/ui/EditorToolbar.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest'
import { TOOLS, ACTION_DESCRIPTIONS } from './EditorToolbar.tsx'

describe('tool rail descriptions', () => {
  it('every tool carries a non-empty description', () => {
    expect(TOOLS.length).toBeGreaterThan(0)
    for (const t of TOOLS) {
      expect(t.description, `${t.tool} has no description`).toBeTruthy()
      expect(t.description.length).toBeGreaterThan(10)
    }
  })

  it('descriptions are plain sentences, not repeats of the title', () => {
    for (const t of TOOLS) {
      expect(t.description).not.toBe(t.title)
    }
  })

  it('every action button has a description', () => {
    for (const key of ['delete', 'keep', 'invert', 'clear', 'undo', 'redo', 'erase'] as const) {
      expect(ACTION_DESCRIPTIONS[key], `${key} missing`).toBeTruthy()
    }
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/ui/EditorToolbar.test.tsx`
Expected: FAIL — `TOOLS` and `ACTION_DESCRIPTIONS` are not exported.

- [ ] **Step 3: Export TOOLS with descriptions and add ACTION_DESCRIPTIONS**

In `src/ui/EditorToolbar.tsx`, replace the `TOOLS` constant (currently line 38-44) with:

```tsx
export const TOOLS: Array<{
  tool: SelectionTool
  icon: typeof Brush
  title: string
  description: string
}> = [
  { tool: 'brush', icon: Brush, title: 'Brush select', description: 'Paint over splats to select them. [ and ] resize the brush.' },
  { tool: 'lasso', icon: Lasso, title: 'Lasso select', description: 'Draw a freehand outline; everything inside it is selected.' },
  { tool: 'polygon', icon: Hexagon, title: 'Polygon select', description: 'Click points to outline a region; double-click to close it.' },
  { tool: 'sphere', icon: CircleDashed, title: 'Sphere select', description: 'Drag out a sphere; splats inside it are selected.' },
  { tool: 'box', icon: Box, title: 'Box select', description: 'Drag out a box; splats inside it are selected.' },
]

export const ACTION_DESCRIPTIONS = {
  erase: 'Selections delete the moment you finish the gesture, instead of building up.',
  delete: 'Delete the selected splats.',
  keep: 'Delete everything except the selection.',
  invert: 'Swap what is selected for what is not.',
  clear: 'Deselect everything; nothing is deleted.',
  undo: 'Step back one edit.',
  redo: 'Re-apply the edit you just undid.',
} as const
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/ui/EditorToolbar.test.tsx`
Expected: PASS (3 tests)

- [ ] **Step 5: Add the `?` toggle that expands descriptions inline**

In `src/ui/EditorToolbar.tsx`, add `HelpCircle` to the `lucide-react` import list. Inside the component, before `return`, add:

```tsx
const [showHelp, setShowHelp] = useState(false)
```

Add `import { useState } from 'react'` at the top of the file.

Change the rail's outer `div` className so it widens when help is shown — replace `'w-[34px]'` with a template:

```tsx
<div className={`absolute left-0 top-0 bottom-0 z-20 flex ${showHelp ? 'w-[230px]' : 'w-[34px]'} flex-col items-stretch gap-0.5 border-r border-border-panel bg-bg-topbar pt-2 transition-[width] duration-100`}>
```

Wrap each rail entry so the description can sit beside it. Replace the `TOOLS.map(...)` block with:

```tsx
{TOOLS.map(({ tool, icon: Icon, title, description }) => (
  <div key={tool} className="flex items-center gap-2 px-[3px]">
    <RailButton
      title={showHelp ? title : `${title} — ${description}`}
      active={activeTool === tool}
      disabled={disabled}
      onClick={() => onToolChange(activeTool === tool ? null : tool)}
    >
      <Icon size={15} />
    </RailButton>
    {showHelp && (
      <div className="min-w-0 flex-1 leading-tight">
        <div className="text-[10px] font-medium text-text-primary">{title}</div>
        <div className="text-[9px] text-text-dim">{description}</div>
      </div>
    )}
  </div>
))}
```

Add the toggle as the last child of the rail, after the Undo/Redo group:

```tsx
<div className="mt-auto mb-2 flex items-center gap-2 px-[3px]">
  <RailButton
    title={showHelp ? 'Hide tool descriptions' : 'Show tool descriptions'}
    active={showHelp}
    onClick={() => setShowHelp(!showHelp)}
  >
    <HelpCircle size={15} />
  </RailButton>
  {showHelp && <div className="text-[9px] text-text-dim">Hide descriptions</div>}
</div>
```

- [ ] **Step 6: Verify type-check, lint and the full frontend suite**

Run: `npx tsc --noEmit && npx vitest run && npm run lint`
Expected: tsc clean; all tests pass; lint shows only the pre-existing `src/App.tsx:172` warning.

- [ ] **Step 7: Commit**

```bash
git add src/ui/EditorToolbar.tsx src/ui/EditorToolbar.test.tsx
git commit -m "feat(ui): discoverable tool descriptions in the editor rail"
```

---

### Task 2: Pure crop-box math

**Files:**
- Create: `src/viewer/cropBoxMath.ts`
- Test: `src/viewer/cropBoxMath.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `interface Box { min: [number, number, number]; max: [number, number, number] }`
  - `boxFromTransform(position: readonly number[], scale: readonly number[]): Box`
  - `transformFromBox(box: Box): { position: [number,number,number]; scale: [number,number,number] }`
  - `normalizeBox(box: Box): Box`
  - `countInsideSampled(centers: Float32Array, box: Box): number`

- [ ] **Step 1: Write the failing test**

Create `src/viewer/cropBoxMath.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import {
  boxFromTransform, transformFromBox, normalizeBox, countInsideSampled,
} from './cropBoxMath.ts'

describe('boxFromTransform / transformFromBox', () => {
  it('round-trips a box through a unit-cube transform', () => {
    const box = { min: [-1, 2, -3] as [number,number,number], max: [3, 6, 1] as [number,number,number] }
    const t = transformFromBox(box)
    expect(t.position).toEqual([1, 4, -1])
    expect(t.scale).toEqual([4, 4, 4])
    expect(boxFromTransform(t.position, t.scale)).toEqual(box)
  })

  it('never produces a zero-sized scale', () => {
    const t = transformFromBox({ min: [0, 0, 0], max: [0, 0, 0] })
    expect(t.scale[0]).toBeGreaterThan(0)
    expect(t.scale[1]).toBeGreaterThan(0)
    expect(t.scale[2]).toBeGreaterThan(0)
  })
})

describe('normalizeBox', () => {
  it('repairs an inverted axis rather than returning an empty box', () => {
    // A negative scale drag flips an axis; min/max must be rebuilt componentwise.
    expect(normalizeBox({ min: [5, 0, 2], max: [1, 3, -4] })).toEqual({
      min: [1, 0, -4], max: [5, 3, 2],
    })
  })

  it('leaves an already-ordered box untouched', () => {
    const box = { min: [-1, -1, -1] as [number,number,number], max: [1, 1, 1] as [number,number,number] }
    expect(normalizeBox(box)).toEqual(box)
  })
})

describe('countInsideSampled', () => {
  const centers = new Float32Array([
    0, 0, 0,      // inside
    0.5, 0.5, 0.5,// inside
    5, 5, 5,      // outside
    -5, 0, 0,     // outside
  ])

  it('counts only centers within the box, inclusive of the boundary', () => {
    expect(countInsideSampled(centers, { min: [-1, -1, -1], max: [1, 1, 1] })).toBe(2)
  })

  it('returns 0 for a box containing nothing', () => {
    expect(countInsideSampled(centers, { min: [100, 100, 100], max: [101, 101, 101] })).toBe(0)
  })

  it('counts a point exactly on the boundary as inside', () => {
    expect(countInsideSampled(new Float32Array([1, 1, 1]), { min: [0, 0, 0], max: [1, 1, 1] })).toBe(1)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/viewer/cropBoxMath.test.ts`
Expected: FAIL — cannot resolve `./cropBoxMath.ts`.

- [ ] **Step 3: Write the implementation**

Create `src/viewer/cropBoxMath.ts`:

```ts
/**
 * Pure geometry for the operator crop box.
 *
 * The box is represented in the scene as a unit cube parented to the splat
 * mesh, so `position` is its center and `scale` its full size — both already in
 * backend (mesh-local) coordinates, because the viewer's Y-flip lives on the
 * parent. Keeping the math here means it can be tested without a WebGL context.
 */

export interface Box {
  min: [number, number, number]
  max: [number, number, number]
}

const MIN_SIZE = 1e-4

/** Center + full size of a unit cube -> min/max box. */
export function boxFromTransform(position: readonly number[], scale: readonly number[]): Box {
  const half = [scale[0] / 2, scale[1] / 2, scale[2] / 2]
  return normalizeBox({
    min: [position[0] - half[0], position[1] - half[1], position[2] - half[2]],
    max: [position[0] + half[0], position[1] + half[1], position[2] + half[2]],
  })
}

/** min/max box -> the unit cube's center and full size. */
export function transformFromBox(box: Box): {
  position: [number, number, number]
  scale: [number, number, number]
} {
  const b = normalizeBox(box)
  return {
    position: [
      (b.min[0] + b.max[0]) / 2,
      (b.min[1] + b.max[1]) / 2,
      (b.min[2] + b.max[2]) / 2,
    ],
    scale: [
      Math.max(b.max[0] - b.min[0], MIN_SIZE),
      Math.max(b.max[1] - b.min[1], MIN_SIZE),
      Math.max(b.max[2] - b.min[2], MIN_SIZE),
    ],
  }
}

/**
 * Rebuild min/max componentwise. A scale handle dragged past its opposite face
 * produces a negative scale and inverts an axis; an inverted box silently
 * contains nothing, which would read as "the crop deleted everything".
 */
export function normalizeBox(box: Box): Box {
  return {
    min: [
      Math.min(box.min[0], box.max[0]),
      Math.min(box.min[1], box.max[1]),
      Math.min(box.min[2], box.max[2]),
    ],
    max: [
      Math.max(box.min[0], box.max[0]),
      Math.max(box.min[1], box.max[1]),
      Math.max(box.min[2], box.max[2]),
    ],
  }
}

/** Centers inside the box, boundary inclusive. `centers` is flat xyz triples. */
export function countInsideSampled(centers: Float32Array, box: Box): number {
  const b = normalizeBox(box)
  let n = 0
  for (let i = 0; i < centers.length; i += 3) {
    const x = centers[i], y = centers[i + 1], z = centers[i + 2]
    if (
      x >= b.min[0] && x <= b.max[0] &&
      y >= b.min[1] && y <= b.max[1] &&
      z >= b.min[2] && z <= b.max[2]
    ) n++
  }
  return n
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/viewer/cropBoxMath.test.ts`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/viewer/cropBoxMath.ts src/viewer/cropBoxMath.test.ts
git commit -m "feat(viewer): pure crop-box geometry with inverted-axis repair"
```

---

### Task 3: The gizmo wrapper

**Files:**
- Create: `src/viewer/CropBoxGizmo.ts`
- Test: `src/viewer/CropBoxGizmo.test.ts`

**Interfaces:**
- Consumes: `Box`, `boxFromTransform`, `transformFromBox` from Task 2.
- Produces: `class CropBoxGizmo` with `attach(box: Box): void`, `detach(): void`, `getBox(): Box | null`, `setMode(m: 'translate' | 'scale'): void`, `onChange: (box: Box) => void`, and constructor `(deps: GizmoDeps)` where

```ts
interface GizmoDeps {
  camera: THREE.Camera
  domElement: HTMLElement
  scene: THREE.Object3D          // where the gizmo helper is added
  parent: THREE.Object3D         // the splat mesh — box is parented here
  setOrbitEnabled: (on: boolean) => void
}
```

- [ ] **Step 1: Write the failing test**

Create `src/viewer/CropBoxGizmo.test.ts`. It fakes `TransformControls` so no WebGL is needed:

```ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import * as THREE from 'three'

const listeners: Record<string, Array<(e: { value: boolean }) => void>> = {}
const fake = {
  attach: vi.fn(),
  detach: vi.fn(),
  setMode: vi.fn(),
  dispose: vi.fn(),
  getHelper: vi.fn(() => new THREE.Object3D()),
  addEventListener: vi.fn((ev: string, fn: (e: { value: boolean }) => void) => {
    ;(listeners[ev] ??= []).push(fn)
  }),
}
vi.mock('three/examples/jsm/controls/TransformControls.js', () => ({
  TransformControls: vi.fn(() => fake),
}))

const emit = (ev: string, value: boolean) => (listeners[ev] ?? []).forEach((f) => f({ value }))

import { CropBoxGizmo } from './CropBoxGizmo.ts'

function makeGizmo() {
  const setOrbitEnabled = vi.fn()
  const parent = new THREE.Object3D()
  const g = new CropBoxGizmo({
    camera: new THREE.PerspectiveCamera(),
    domElement: document.createElement('div'),
    scene: new THREE.Object3D(),
    parent,
    setOrbitEnabled,
  })
  return { g, setOrbitEnabled, parent }
}

beforeEach(() => {
  for (const k of Object.keys(listeners)) delete listeners[k]
  vi.clearAllMocks()
})

describe('CropBoxGizmo', () => {
  it('attaching parents a box proxy to the splat mesh', () => {
    const { g, parent } = makeGizmo()
    g.attach({ min: [-1, -1, -1], max: [1, 1, 1] })
    expect(parent.children.length).toBe(1)
    expect(g.getBox()).toEqual({ min: [-1, -1, -1], max: [1, 1, 1] })
  })

  it('suspends orbit while a handle is dragged and restores it after', () => {
    const { g, setOrbitEnabled } = makeGizmo()
    g.attach({ min: [0, 0, 0], max: [1, 1, 1] })
    emit('dragging-changed', true)
    expect(setOrbitEnabled).toHaveBeenLastCalledWith(false)
    emit('dragging-changed', false)
    expect(setOrbitEnabled).toHaveBeenLastCalledWith(true)
  })

  it('restores orbit when detached mid-drag', () => {
    const { g, setOrbitEnabled } = makeGizmo()
    g.attach({ min: [0, 0, 0], max: [1, 1, 1] })
    emit('dragging-changed', true)
    setOrbitEnabled.mockClear()
    g.detach()
    expect(setOrbitEnabled).toHaveBeenCalledWith(true)
  })

  it('detaching removes the proxy and clears the box', () => {
    const { g, parent } = makeGizmo()
    g.attach({ min: [0, 0, 0], max: [1, 1, 1] })
    g.detach()
    expect(parent.children.length).toBe(0)
    expect(g.getBox()).toBeNull()
  })

  it('reports the box after the proxy transform changes', () => {
    const { g } = makeGizmo()
    const seen: unknown[] = []
    g.onChange = (b) => seen.push(b)
    g.attach({ min: [0, 0, 0], max: [2, 2, 2] })
    g.proxyForTest!.position.set(5, 5, 5)
    emit('objectChange', false)
    expect(seen.at(-1)).toEqual({ min: [4, 4, 4], max: [6, 6, 6] })
  })

  it('getBox is null before attach', () => {
    const { g } = makeGizmo()
    expect(g.getBox()).toBeNull()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/viewer/CropBoxGizmo.test.ts`
Expected: FAIL — cannot resolve `./CropBoxGizmo.ts`.

- [ ] **Step 3: Write the implementation**

Create `src/viewer/CropBoxGizmo.ts`:

```ts
import * as THREE from 'three'
import { TransformControls } from 'three/examples/jsm/controls/TransformControls.js'
import { boxFromTransform, transformFromBox, type Box } from './cropBoxMath.ts'

export interface GizmoDeps {
  camera: THREE.Camera
  domElement: HTMLElement
  /** Where the gizmo helper is added — the scene root, not the splat mesh. */
  scene: THREE.Object3D
  /** The splat mesh. The box proxy is parented here so its local transform is
   *  already in backend coordinates (the Y-flip belongs to this parent). */
  parent: THREE.Object3D
  setOrbitEnabled: (on: boolean) => void
}

/**
 * Movable/resizable crop box.
 *
 * Orbit is disabled only for the duration of a handle drag. That is the single
 * sanctioned exception to "the mouse always orbits" — it is scoped to an active
 * drag, so there is no mode the operator can get stuck in, and `detach()`
 * restores orbit even if the drag never ended (tool switched mid-drag).
 */
export class CropBoxGizmo {
  onChange: ((box: Box) => void) | null = null
  /** Exposed for tests only. */
  proxyForTest: THREE.Object3D | null = null

  private controls: TransformControls
  private proxy: THREE.Mesh | null = null
  private dragging = false

  constructor(private deps: GizmoDeps) {
    this.controls = new TransformControls(deps.camera, deps.domElement)
    this.controls.addEventListener('dragging-changed', (e: { value: boolean }) => {
      this.dragging = e.value
      deps.setOrbitEnabled(!e.value)
    })
    this.controls.addEventListener('objectChange', () => this.emit())
    deps.scene.add(this.controls.getHelper())
  }

  attach(box: Box): void {
    this.detachProxy()
    const t = transformFromBox(box)
    const proxy = new THREE.Mesh(
      new THREE.BoxGeometry(1, 1, 1),
      new THREE.MeshBasicMaterial({ visible: false }),
    )
    proxy.position.set(t.position[0], t.position[1], t.position[2])
    proxy.scale.set(t.scale[0], t.scale[1], t.scale[2])
    this.deps.parent.add(proxy)
    this.proxy = proxy
    this.proxyForTest = proxy
    this.controls.attach(proxy)
    this.emit()
  }

  detach(): void {
    this.detachProxy()
    if (this.dragging) {
      // A tool switch mid-drag never fires dragging-changed:false, which would
      // leave orbit disabled forever — exactly the nav trap the editor fixed.
      this.dragging = false
      this.deps.setOrbitEnabled(true)
    }
  }

  getBox(): Box | null {
    if (!this.proxy) return null
    const p = this.proxy.position, s = this.proxy.scale
    return boxFromTransform([p.x, p.y, p.z], [s.x, s.y, s.z])
  }

  setMode(mode: 'translate' | 'scale'): void {
    this.controls.setMode(mode)
  }

  dispose(): void {
    this.detach()
    this.controls.dispose()
  }

  private emit(): void {
    const box = this.getBox()
    if (box && this.onChange) this.onChange(box)
  }

  private detachProxy(): void {
    this.controls.detach()
    if (this.proxy) {
      this.deps.parent.remove(this.proxy)
      this.proxy.geometry.dispose()
      ;(this.proxy.material as THREE.Material).dispose()
    }
    this.proxy = null
    this.proxyForTest = null
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/viewer/CropBoxGizmo.test.ts`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/viewer/CropBoxGizmo.ts src/viewer/CropBoxGizmo.test.ts
git commit -m "feat(viewer): crop-box gizmo with scoped orbit suspension"
```

---

### Task 4: Wire the crop-box tool end to end

**Files:**
- Modify: `src/viewer/SceneManager.ts`, `src/types/viewer.ts`, `src/viewer/ViewerCanvas.tsx`, `src/ui/EditorToolbar.tsx`, `src/App.tsx`, `src/viewer/SelectionOverlay.tsx`
- Test: `src/viewer/cropBoxMath.test.ts` (extend)

**Interfaces:**
- Consumes: `CropBoxGizmo` (Task 3), `countInsideSampled`/`Box` (Task 2), `TOOLS` (Task 1).
- Produces: on `ViewerHandle` — `beginCropBox(seed?: Box): void`, `endCropBox(): void`, `getCropBox(): Box | null`, `cropToBox(): Uint32Array`, `cropBoxCount(): number`.

- [ ] **Step 1: Add `'cropBox'` to the SelectionTool union**

In `src/viewer/SelectionOverlay.tsx`, find the `SelectionTool` type and add `'cropBox'` to the union. The overlay must ignore it — find the guard that dispatches on the active tool and return early for `'cropBox'` so no selection gesture starts (the gizmo owns the pointer).

- [ ] **Step 2: Write the failing test for the count contract**

Append to `src/viewer/cropBoxMath.test.ts`:

```ts
describe('sampled count scaling', () => {
  it('scales a strided sample back to a full-scene estimate', () => {
    // 3 of 4 sampled centers are inside; stride 10 -> ~30 of 40.
    const centers = new Float32Array([0,0,0, 0,0,0, 0,0,0, 9,9,9])
    const inside = countInsideSampled(centers, { min: [-1,-1,-1], max: [1,1,1] })
    expect(inside).toBe(3)
    expect(inside * 10).toBe(30)
  })
})
```

- [ ] **Step 3: Run it**

Run: `npx vitest run src/viewer/cropBoxMath.test.ts`
Expected: PASS (this pins the documented scaling convention; it needs no new source).

- [ ] **Step 4: Add the viewer methods on SceneManager**

In `src/viewer/SceneManager.ts`, add the import:

```ts
import { CropBoxGizmo } from './CropBoxGizmo.ts'
import { countInsideSampled, type Box } from './cropBoxMath.ts'
```

Add fields beside the proposal-box fields (near line 1152):

```ts
private cropGizmo: CropBoxGizmo | null = null
private cropSample: Float32Array | null = null   // strided centers, backend coords
private cropStride = 1
private cropCount = 0
```

Add these methods after `getProposalBox()`:

```ts
/** Start the crop-box tool. `seed` defaults to the tight core box. */
beginCropBox(seed?: Box): void {
  const mesh = this.splatMesh
  if (!mesh) return
  const box = seed ?? this.getCoreBoundsBox() ?? null
  if (!box) return
  this.buildCropSample()
  if (!this.cropGizmo) {
    this.cropGizmo = new CropBoxGizmo({
      camera: this.camera,
      domElement: this.renderer.domElement,
      scene: this.scene,
      parent: mesh,
      setOrbitEnabled: (on) => { this.controls.enabled = on },
    })
    this.cropGizmo.onChange = (b) => {
      this.showProposalBox(b.min, b.max)   // wireframe + SDF dim of the outside
      this.cropCount = countInsideSampled(this.cropSample!, b) * this.cropStride
    }
  }
  this.cropGizmo.attach({ min: box.min as Box['min'], max: box.max as Box['max'] })
}

endCropBox(): void {
  this.cropGizmo?.detach()
  this.clearProposalBox()
  this.cropSample = null
  this.cropCount = 0
}

getCropBox(): Box | null {
  return this.cropGizmo?.getBox() ?? null
}

/** Approximate splat count inside the box, from the strided sample. */
cropBoxCount(): number {
  return this.cropCount
}

/** Keep only splats inside the box. Returns the kept stable IDs (exact). */
cropToBox(): Uint32Array {
  const box = this.getCropBox()
  const packed = this.splatMesh?.packedSplats
  if (!box || !packed || !this.idMap) return new Uint32Array(0)
  const keep: number[] = []
  for (let i = 0; i < packed.numSplats; i++) {
    const c = packed.getSplat(i).center
    if (
      c.x >= box.min[0] && c.x <= box.max[0] &&
      c.y >= box.min[1] && c.y <= box.max[1] &&
      c.z >= box.min[2] && c.z <= box.max[2]
    ) keep.push(this.idMap.idAt(i))
  }
  const ids = new Uint32Array(keep)
  if (ids.length > 0) this.keepOnlyIds(ids)
  this.endCropBox()
  return ids
}

/** Strided centers for the live readout — an exact per-frame count is O(N)
 *  and unusable at 2M splats (same 100k cap as getCoreBoundsBox). */
private buildCropSample(): void {
  const packed = this.splatMesh?.packedSplats
  if (!packed) return
  const n = packed.numSplats
  this.cropStride = Math.max(1, Math.floor(n / 100_000))
  const out: number[] = []
  for (let i = 0; i < n; i += this.cropStride) {
    const c = packed.getSplat(i).center
    out.push(c.x, c.y, c.z)
  }
  this.cropSample = new Float32Array(out)
}
```

- [ ] **Step 5: Expose them on the handle**

In `src/types/viewer.ts`, add to the `ViewerHandle` interface beside `getProposalBox`:

```ts
beginCropBox(seed?: { min: number[]; max: number[] }): void
endCropBox(): void
getCropBox(): { min: number[]; max: number[] } | null
cropBoxCount(): number
cropToBox(): Uint32Array
```

In `src/viewer/ViewerCanvas.tsx`, beside the other forwarded methods (near line 91):

```tsx
beginCropBox: (seed) => mgr().beginCropBox(seed as never),
endCropBox: () => mgr().endCropBox(),
getCropBox: () => mgr().getCropBox(),
cropBoxCount: () => mgr().cropBoxCount(),
cropToBox: () => mgr().cropToBox(),
```

- [ ] **Step 6: Add the rail entry**

In `src/ui/EditorToolbar.tsx` add `Scissors` to the `lucide-react` import and append to `TOOLS`:

```tsx
{ tool: 'cropBox', icon: Scissors, title: 'Crop box', description: 'Place a box, move and resize it, then delete everything outside it.' },
```

Add a `cropBoxCount` prop and a commit button. Extend `EditorToolbarProps` with:

```tsx
cropBoxCount?: number
onCropToBox?: () => void
```

and render, immediately after the `TOOLS.map(...)` block:

```tsx
{activeTool === 'cropBox' && (
  <div className="flex flex-col items-stretch gap-1 px-[3px] py-1">
    <button
      type="button"
      onClick={onCropToBox}
      disabled={disabled || !cropBoxCount}
      className="rounded-[2px] bg-accent-cyan/90 px-1 py-1 text-[9px] font-medium text-white disabled:opacity-35"
    >
      Crop to box
    </button>
    <div className="text-center font-mono text-[9px] text-text-dim">
      ~{(cropBoxCount ?? 0).toLocaleString()} inside
    </div>
  </div>
)}
```

- [ ] **Step 7: Wire it in App.tsx**

In `src/App.tsx`, add state near the other editor state:

```tsx
const [cropBoxCount, setCropBoxCount] = useState(0)
```

Add an effect that starts/stops the gizmo with the tool, polling the count while it is active (the gizmo mutates on drag, outside React):

```tsx
useEffect(() => {
  if (activeTool !== 'cropBox') {
    viewerRef.current?.endCropBox()
    setCropBoxCount(0)
    return
  }
  viewerRef.current?.beginCropBox()
  const id = window.setInterval(
    () => setCropBoxCount(viewerRef.current?.cropBoxCount() ?? 0),
    120,
  )
  return () => {
    window.clearInterval(id)
    viewerRef.current?.endCropBox()
  }
}, [activeTool])
```

Add the commit handler beside `handleKeepSelection`:

```tsx
const handleCropToBox = useCallback(() => {
  const before = viewerRef.current?.getStats().splatCount ?? 0
  const ids = viewerRef.current?.cropToBox() ?? new Uint32Array(0)
  if (ids.length === 0) {
    showStatus('Box contains no splats — nothing cropped')
    return
  }
  if (ids.length === before) {
    // Everything was already inside: a keep_only_ids here is a no-op that still
    // costs a history entry, so the operator's Undo would appear to do nothing.
    showStatus('Box already contains the whole scene — nothing to crop')
    setActiveTool(null)
    return
  }
  commitEdit('keep_only_ids', ids)
  setActiveTool(null)
}, [commitEdit, showStatus])
```

Note: `cropToBox()` applies the local keep before returning, so the no-op branch
above must run *before* any local mutation matters — it does not, because when
`ids.length === before` the local keep changed nothing by definition.

If `getStats()` is not the accessor for the live splat count on `ViewerHandle`,
use whichever accessor `src/App.tsx` already uses to drive the HUD's splat count
and keep the comparison identical.

Pass both to `<EditorToolbar ... cropBoxCount={cropBoxCount} onCropToBox={handleCropToBox} />`.

- [ ] **Step 8: Verify**

Run: `npx tsc --noEmit && npx vitest run && npm run lint`
Expected: tsc clean, all tests pass, lint at baseline.

- [ ] **Step 9: Manual check**

Start the app (`npm run dev`, backend on :8000). Load `public/demos/iona_park.ply`. Pick the crop-box tool. Confirm: a box appears around the dense core with the outside dimmed; dragging the body moves it; dragging a handle resizes it; the mouse still orbits when not on a handle; the count updates; "Crop to box" deletes the outside; Undo restores it.

- [ ] **Step 10: Commit**

```bash
git add src/viewer/SceneManager.ts src/types/viewer.ts src/viewer/ViewerCanvas.tsx src/ui/EditorToolbar.tsx src/App.tsx src/viewer/SelectionOverlay.tsx src/viewer/cropBoxMath.test.ts
git commit -m "feat(editor): operator crop-box tool — place, resize, crop outside"
```

---

### Task 5: v0.6 contract — the approved box travels with the verdict

**Files:**
- Modify: `frontend/src/contracts.ts`, `backend/contracts/tools.py`
- Test: `frontend/src/agent/contracts.test.ts`, `backend/contracts/tests/test_tools.py`

**Interfaces:**
- Consumes: nothing.
- Produces: the proposal reply payload may carry `box?: { min: number[]; max: number[] }`. Task 6 sends it; Task 7 honors it.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/agent/contracts.test.ts`:

```ts
import { PROPOSAL_DECISION_FIELDS } from '../contracts.ts'

describe('v0.6 proposal decision', () => {
  it('carries the operator-edited box alongside the verdict', () => {
    expect(PROPOSAL_DECISION_FIELDS).toContain('verdict')
    expect(PROPOSAL_DECISION_FIELDS).toContain('feedback')
    expect(PROPOSAL_DECISION_FIELDS).toContain('box')
  })
})
```

Append to `backend/contracts/tests/test_tools.py`:

```python
def test_proposal_decision_fields_v06():
    """The operator's edited box rides back with an approved verdict (v0.6)."""
    from backend.contracts.tools import PROPOSAL_DECISION_FIELDS

    assert "verdict" in PROPOSAL_DECISION_FIELDS
    assert "feedback" in PROPOSAL_DECISION_FIELDS
    assert "box" in PROPOSAL_DECISION_FIELDS
```

- [ ] **Step 2: Run both to verify they fail**

Run: `npx vitest run frontend/src/agent/contracts.test.ts && .venv-api/bin/python -m pytest backend/contracts/tests/test_tools.py -q`
Expected: both FAIL on the missing `PROPOSAL_DECISION_FIELDS` export.

- [ ] **Step 3: Add the mirrored constant**

In `frontend/src/contracts.ts`, beside the v0.5 proposal section (near line 155):

```ts
/**
 * v0.6 — fields a proposal reply may carry. `box` is the operator's edited crop
 * box in BACKEND coordinates; when present on an `approved` verdict the backend
 * rebinds the approval to it, so the crop runs on the box the operator actually
 * looked at rather than the one the agent previewed.
 */
export const PROPOSAL_DECISION_FIELDS = ['verdict', 'feedback', 'box'] as const
```

In `backend/contracts/tools.py`, beside the v0.5 registry additions:

```python
# v0.6 — fields a proposal reply may carry. `box` is the operator's edited crop
# box in backend coordinates; on an `approved` verdict the backend rebinds the
# approval to it (mirror: frontend/src/contracts.ts PROPOSAL_DECISION_FIELDS).
PROPOSAL_DECISION_FIELDS: tuple[str, ...] = ("verdict", "feedback", "box")
```

Add `PROPOSAL_DECISION_FIELDS` to that module's `__all__`.

- [ ] **Step 4: Run both to verify they pass**

Run: `npx vitest run frontend/src/agent/contracts.test.ts && .venv-api/bin/python -m pytest backend/contracts/tests/test_tools.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/contracts.ts backend/contracts/tools.py frontend/src/agent/contracts.test.ts backend/contracts/tests/test_tools.py
git commit -m "feat(contracts): v0.6 — proposal replies carry the operator's box"
```

---

### Task 6: Send the edited box with an approved verdict

**Files:**
- Modify: `frontend/src/agent/ws-client.ts:162-205`, `src/App.tsx`
- Test: `frontend/src/agent/ws-client.test.ts`

**Interfaces:**
- Consumes: `PROPOSAL_DECISION_FIELDS` (Task 5), `getProposalBox()` on the bridge (already exists).
- Produces: the `tool_result` reply for a `proposal` command includes `box` when the verdict is `approved` and a proposal box is live.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/agent/ws-client.test.ts`, following the existing proposal test's setup:

```ts
it('an approved verdict carries the current (operator-edited) box', async () => {
  const sent: unknown[] = []
  // `harness` mirrors the existing proposal test's fixture: a client wired to a
  // fake transport that records sends, and a bridge with a live proposal box.
  const h = harness({ onSend: (m) => sent.push(m) })
  h.bridge.showProposalBox([0, 0, 0], [1, 1, 1])
  h.deliver({ type: 'proposal', id: 'p1', payload: { args: { kind: 'crop_outside_box', summary: 's' } } })
  h.panels.proposal.get()!.resolve('approved')
  await Promise.resolve()

  const reply = sent.find((m) => (m as { id: string }).id === 'p1') as {
    payload: { verdict: string; box?: { min: number[]; max: number[] } }
  }
  expect(reply.payload.verdict).toBe('approved')
  expect(reply.payload.box).toEqual({ min: [0, 0, 0], max: [1, 1, 1] })
})

it('a rejected verdict carries no box', async () => {
  const sent: unknown[] = []
  const h = harness({ onSend: (m) => sent.push(m) })
  h.bridge.showProposalBox([0, 0, 0], [1, 1, 1])
  h.deliver({ type: 'proposal', id: 'p2', payload: { args: { kind: 'crop_outside_box', summary: 's' } } })
  h.panels.proposal.get()!.resolve('rejected', 'no')
  await Promise.resolve()

  const reply = sent.find((m) => (m as { id: string }).id === 'p2') as {
    payload: { box?: unknown }
  }
  expect(reply.payload.box).toBeUndefined()
})
```

- [ ] **Step 2: Run it**

Run: `npx vitest run frontend/src/agent/ws-client.test.ts`
Expected: FAIL — the reply has no `box`.

- [ ] **Step 3: Include the box in the reply**

In `frontend/src/agent/ws-client.ts`, inside the `case 'proposal':` resolver (the `resolve: (verdict, feedback) => {` closure around line 198), build the payload as:

```ts
resolve: (verdict, feedback) => {
  if (done) return
  done = true
  // v0.6: on approval, return the box as it stands NOW — the operator may have
  // moved or resized it since the agent previewed it, and the crop must run on
  // what they actually looked at.
  const box = verdict === 'approved' ? this.bridge.getProposalBox() : null
  this.transport.send({
    type: 'tool_result',
    id,
    payload: { ok: true, verdict, feedback, ...(box ? { box } : {}) },
  } as WSResponse)
  this.panels.setProposal(null)
},
```

- [ ] **Step 4: Run it**

Run: `npx vitest run frontend/src/agent/ws-client.test.ts`
Expected: PASS.

- [ ] **Step 5: Let the operator edit the proposed box**

In `src/App.tsx`, when a proposal of kind `crop_outside_box` arrives, attach the gizmo to the previewed box so it is editable. Add to the proposal-handling effect:

```tsx
useEffect(() => {
  const p = proposal
  if (p?.kind === 'crop_outside_box') {
    const box = viewerRef.current?.getProposalBox()
    if (box) viewerRef.current?.beginCropBox(box as never)
  } else {
    viewerRef.current?.endCropBox()
  }
}, [proposal])
```

Note: `beginCropBox` calls `showProposalBox` on every change, so `getProposalBox()` tracks the operator's edits and Task 6 Step 3 picks up the edited box.

- [ ] **Step 6: Verify**

Run: `npx tsc --noEmit && npx vitest run && npm run lint`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/agent/ws-client.ts frontend/src/agent/ws-client.test.ts src/App.tsx
git commit -m "feat(agent): operator's edited box rides back with the approval"
```

---

### Task 7: Bind the approval to the operator's box

**Files:**
- Modify: `backend/agent/loop.py:495-501` (call site), `backend/agent/loop.py:657-691` (`_bank_approval`)
- Test: `backend/agent/tests/test_proposals.py`

**Interfaces:**
- Consumes: the `box` field from Task 5/6.
- Produces: `_bank_approval(kind, args, decision)` — third parameter is the decision payload returned by the frontend.

- [ ] **Step 1: Write the failing test**

Append to `backend/agent/tests/test_proposals.py`, following the existing scripted-provider fixture:

```python
@pytest.mark.asyncio
async def test_approved_crop_uses_the_operators_edited_box(scripted_loop):
    """The operator moved the box after the agent previewed it; the crop must
    run on THEIR box, not the preview (v0.6)."""
    previewed = {"min": [0.0, 0.0, 0.0], "max": [1.0, 1.0, 1.0]}
    edited = {"min": [2.0, 2.0, 2.0], "max": [5.0, 5.0, 5.0]}

    loop, calls = scripted_loop(
        script=[
            ("show_box_preview", previewed),
            ("propose_decision", {"kind": "crop_outside_box", "summary": "crop"}),
            ("crop_bbox", previewed),
            ("answer", {"text": "done"}),
        ],
        proposal_verdict={"verdict": "approved", "box": edited},
    )
    await loop.run("clean it")

    crop = next(c for c in calls if c.name == "crop_bbox")
    assert crop.args["min"] == edited["min"]
    assert crop.args["max"] == edited["max"]


@pytest.mark.asyncio
async def test_approved_crop_without_a_box_uses_the_preview(scripted_loop):
    """Unchanged behaviour when the reply carries no box."""
    previewed = {"min": [0.0, 0.0, 0.0], "max": [1.0, 1.0, 1.0]}

    loop, calls = scripted_loop(
        script=[
            ("show_box_preview", previewed),
            ("propose_decision", {"kind": "crop_outside_box", "summary": "crop"}),
            ("crop_bbox", {"min": [9.0, 9.0, 9.0], "max": [9.0, 9.0, 9.0]}),
            ("answer", {"text": "done"}),
        ],
        proposal_verdict={"verdict": "approved"},
    )
    await loop.run("clean it")

    crop = next(c for c in calls if c.name == "crop_bbox")
    assert crop.args["min"] == previewed["min"]
    assert crop.args["max"] == previewed["max"]
```

If `scripted_loop` does not yet accept a `proposal_verdict` kwarg, extend the existing fixture in that file to pass the given dict through as the `propose_decision` dispatch result.

- [ ] **Step 2: Run it**

Run: `.venv-api/bin/python -m pytest backend/agent/tests/test_proposals.py -q`
Expected: FAIL — the crop uses the previewed box in both cases.

- [ ] **Step 3: Thread the decision into banking**

In `backend/agent/loop.py`, change the call site (currently line 499):

```python
        if call.name == "propose_decision" and result.get("ok"):
            payload = result.get("result")
            if isinstance(payload, dict) and payload.get("verdict") == "approved":
                kind = str(call.args.get("kind", ""))
                refusal = await self._bank_approval(kind, call.args, payload)
                if refusal:
                    self._nudge_sync(refusal)
```

Change the signature and the `crop_outside_box` branch:

```python
    async def _bank_approval(
        self, kind: str, args: dict, decision: dict | None = None
    ) -> str | None:
        """Bank an approved proposal, capturing the reviewed artifact.

        Returns a refusal message (and banks nothing) when the approval would
        bind no artifact — the gate must never be passable by an approval the
        operator couldn't have meaningfully reviewed.
        """
        if kind == "crop_outside_box":
            # v0.6: the operator can move/resize the box before approving, and
            # the reply carries what they finally looked at. Prefer it over the
            # agent's preview — the approval must bind the reviewed artifact,
            # and the reviewed artifact is theirs.
            operator_box = (decision or {}).get("box")
            if isinstance(operator_box, dict) and _is_vec3(
                operator_box.get("min")
            ) and _is_vec3(operator_box.get("max")):
                self._approved_box = {
                    "min": [float(v) for v in operator_box["min"]],
                    "max": [float(v) for v in operator_box["max"]],
                }
            elif self._previewed_box is None:
                return (
                    "[system] approval not banked: no box was previewed. Call "
                    "show_box_preview, verify with a capture, then propose again."
                )
            else:
                self._approved_box = dict(self._previewed_box)
```

Leave the `bulk_edit`, `_SELECTION_KINDS` and trailing `self._approvals[kind] = ...` lines unchanged.

- [ ] **Step 4: Run it**

Run: `.venv-api/bin/python -m pytest backend/agent/tests/test_proposals.py -q`
Expected: PASS.

- [ ] **Step 5: Run the whole backend suite**

Run: `.venv-api/bin/python -m pytest -q`
Expected: all pass (229 before this plan, plus the new tests).

- [ ] **Step 6: Commit**

```bash
git add backend/agent/loop.py backend/agent/tests/test_proposals.py
git commit -m "feat(agent): approved crop binds to the operator's edited box"
```

---

### Task 8: Point the cleanup recipe at the new flow

**Files:**
- Modify: `backend/agent/system_prompt.py:104-110` (the `cleanup_scene` skill), `backend/agent/system_prompt.py:203-215` (GOOD-CUBE ROUTINE)
- Test: `backend/agent/tests/test_cleanup_prompt.py`

**Interfaces:**
- Consumes: the behaviour from Tasks 4-7.
- Produces: none — terminal task.

- [ ] **Step 1: Write the failing test**

Append to `backend/agent/tests/test_cleanup_prompt.py`:

```python
def test_cleanup_recipe_hands_the_box_to_the_operator():
    """The model seeds the box and stops; the operator sizes it (v0.6)."""
    prompt = system_prompt_for("clean")
    lowered = prompt.lower()

    assert "the operator" in lowered
    # It must not promise to size the box itself.
    assert "adjust_box_preview only if the subject is clipped" not in lowered


def test_cleanup_recipe_no_longer_prescribes_brush_rounds():
    clean = {s["name"]: s for s in skills_for("clean")}
    assert "select_by_brush" not in clean["cleanup_scene"]["recipe"]
```

- [ ] **Step 2: Run it**

Run: `.venv-api/bin/python -m pytest backend/agent/tests/test_cleanup_prompt.py -q`
Expected: FAIL — the recipe still prescribes `adjust_box_preview` and brush rounds.

- [ ] **Step 3: Rewrite the recipe**

Replace the `cleanup_scene` entry's `recipe` value with:

```python
        "recipe": "Start IMMEDIATELY — the box comes from the DATA, not your view. In order: 1) capture_frame once for context, 2) get_core_bounds, 3) show_box_preview with exactly those bounds, 4) narrate that the operator can move and resize the box, 5) propose_decision(kind='crop_outside_box'), 6) crop_bbox on approval — the operator's final box is bound automatically, so pass the previewed bounds and let the backend substitute theirs. Then verify: get_metrics and one capture_frame, report before/after counts, and call answer. Do NOT brush, sweep, or crop again.",
```

Replace the GOOD-CUBE ROUTINE bullet with:

```
- GOOD-CUBE ROUTINE (the whole cleanup pass): get_core_bounds ->
  show_box_preview -> tell the operator they can drag and resize the box ->
  propose_decision(kind='crop_outside_box') -> on approval, crop_bbox. You do
  NOT size the box: the operator does, and their final box is what gets cropped
  regardless of the bounds you pass. After the crop, measure, capture once, and
  answer. Nothing else.
```

- [ ] **Step 4: Run it**

Run: `.venv-api/bin/python -m pytest backend/agent/tests/test_cleanup_prompt.py -q`
Expected: PASS.

- [ ] **Step 5: Run the whole backend suite**

Run: `.venv-api/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Manual end-to-end check**

With the backend, vLLM (or Gemini) and Vite running, load `public/demos/iona_park.ply` and run the `cleanup_scene` pill. Confirm: the agent previews a box; you can drag and resize it while the ProposalCard is up; approving crops to *your* box; the splat count holds at the cropped number; Undo restores.

- [ ] **Step 7: Commit**

```bash
git add backend/agent/system_prompt.py backend/agent/tests/test_cleanup_prompt.py
git commit -m "feat(agent): cleanup recipe hands box sizing to the operator"
```

---

## Notes for the implementer

**`TransformControls` import path.** Three 0.184 ships it at `three/examples/jsm/controls/TransformControls.js` and the helper is added to the scene via `controls.getHelper()`, not by adding `controls` itself. Adding `controls` directly throws in this version.

**Orbit suspension is deliberate and narrow.** `src/viewer/SceneManager.ts` keeps `OrbitControls` enabled at all times by design — a previous bug trapped users in fly mode. The gizmo disables orbit only between `dragging-changed: true` and `dragging-changed: false`, and `detach()` restores it if a drag is interrupted. Task 3's tests cover the interrupted case; do not weaken them.

**Coordinates.** The box proxy is parented to `splatMesh`, whose `rotation.x = Math.PI`. Local transforms on a child of that mesh are therefore already backend coordinates — no manual flip anywhere in this plan. If you find yourself converting, something is parented wrong.

**Approximate counts.** `cropBoxCount()` is sampled and may be off by up to one stride's worth. Label it with `~` in the UI (Task 4 Step 6 does). The committed crop in `cropToBox()` walks every splat and is exact.
