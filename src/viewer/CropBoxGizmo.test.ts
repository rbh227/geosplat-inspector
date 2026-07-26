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
