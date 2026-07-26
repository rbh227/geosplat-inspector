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
  const scene = new THREE.Object3D()
  const g = new CropBoxGizmo({
    camera: new THREE.PerspectiveCamera(),
    domElement: document.createElement('div'),
    scene,
    parent,
    setOrbitEnabled,
  })
  return { g, setOrbitEnabled, parent, scene }
}

/** Grabs the proxy object3D passed to controls.attach() for the given call index. */
function attachedProxy(callIndex = 0): THREE.Object3D {
  return fake.attach.mock.calls[callIndex][0] as THREE.Object3D
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

  it('attach() drives TransformControls.attach with the proxy parented into deps.parent', () => {
    const { g, parent } = makeGizmo()
    g.attach({ min: [-1, -1, -1], max: [1, 1, 1] })
    expect(fake.attach).toHaveBeenCalledTimes(1)
    expect(attachedProxy()).toBe(parent.children[0])
  })

  it('detach() drives TransformControls.detach', () => {
    const { g } = makeGizmo()
    g.attach({ min: [0, 0, 0], max: [1, 1, 1] })
    g.detach()
    expect(fake.detach).toHaveBeenCalled()
  })

  it('repeated attach/detach cycles do not leak proxies into deps.parent', () => {
    const { g, parent } = makeGizmo()
    g.attach({ min: [0, 0, 0], max: [1, 1, 1] })
    g.attach({ min: [1, 1, 1], max: [2, 2, 2] })
    expect(parent.children.length).toBe(1)
    g.detach()
    expect(parent.children.length).toBe(0)
    g.attach({ min: [0, 0, 0], max: [1, 1, 1] })
    expect(parent.children.length).toBe(1)
  })

  it('suspends orbit while a handle is dragged and restores it after', () => {
    const { g, setOrbitEnabled } = makeGizmo()
    g.attach({ min: [0, 0, 0], max: [1, 1, 1] })
    emit('dragging-changed', true)
    expect(setOrbitEnabled).toHaveBeenLastCalledWith(false)
    emit('dragging-changed', false)
    expect(setOrbitEnabled).toHaveBeenLastCalledWith(true)
  })

  it('restores orbit when re-attached mid-drag (re-seed/re-target during an active handle drag)', () => {
    const { g, setOrbitEnabled } = makeGizmo()
    g.attach({ min: [0, 0, 0], max: [1, 1, 1] })
    emit('dragging-changed', true)
    setOrbitEnabled.mockClear()
    g.attach({ min: [2, 2, 2], max: [3, 3, 3] })
    expect(setOrbitEnabled).toHaveBeenLastCalledWith(true)
    // A drag that "ended" via re-attach must not still look active afterward:
    // the next real dragging-changed:false should not be treated as a no-op
    // that was already accounted for, and detach() must not re-fire restore
    // logic for a drag that attach() already unwound.
    setOrbitEnabled.mockClear()
    g.detach()
    expect(setOrbitEnabled).not.toHaveBeenCalled()
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
    const proxy = attachedProxy()
    proxy.position.set(5, 5, 5)
    emit('objectChange', false)
    expect(seen.at(-1)).toEqual({ min: [4, 4, 4], max: [6, 6, 6] })
  })

  it('getBox is null before attach', () => {
    const { g } = makeGizmo()
    expect(g.getBox()).toBeNull()
  })

  it('setMode forwards the mode to TransformControls.setMode', () => {
    const { g } = makeGizmo()
    g.setMode('scale')
    expect(fake.setMode).toHaveBeenCalledWith('scale')
    g.setMode('translate')
    expect(fake.setMode).toHaveBeenCalledWith('translate')
  })

  describe('dispose', () => {
    it('calls controls.dispose()', () => {
      const { g } = makeGizmo()
      g.attach({ min: [0, 0, 0], max: [1, 1, 1] })
      g.dispose()
      expect(fake.dispose).toHaveBeenCalled()
    })

    it('removes the proxy from the parent', () => {
      const { g, parent } = makeGizmo()
      g.attach({ min: [0, 0, 0], max: [1, 1, 1] })
      g.dispose()
      expect(parent.children.length).toBe(0)
      expect(g.getBox()).toBeNull()
    })

    it('restores orbit if a drag was in progress', () => {
      const { g, setOrbitEnabled } = makeGizmo()
      g.attach({ min: [0, 0, 0], max: [1, 1, 1] })
      emit('dragging-changed', true)
      setOrbitEnabled.mockClear()
      g.dispose()
      expect(setOrbitEnabled).toHaveBeenCalledWith(true)
    })

    it('removes the TransformControls helper from the scene (MINOR 4)', () => {
      // In three r184 TransformControls.dispose() does NOT remove the helper
      // it added to the scene — dispose() must do it explicitly, or every
      // reload while the crop tool is active leaks an orphan root that is
      // still traversed every frame.
      const { g, scene } = makeGizmo()
      expect(scene.children.length).toBe(1)
      g.dispose()
      expect(scene.children.length).toBe(0)
    })
  })
})
