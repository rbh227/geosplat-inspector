import { describe, expect, it } from 'vitest'
import * as THREE from 'three'
import {
  composeMatrices,
  projectToScreen,
  selectInBox,
  selectInCircle,
  selectInMask,
  selectInPolygon,
  selectInSphere,
  transformPoints,
} from './selection.ts'

// Reference camera: at origin, looking down -Z, 90° fov, square viewport.
function refCamera(): THREE.PerspectiveCamera {
  const cam = new THREE.PerspectiveCamera(90, 1, 0.1, 100)
  cam.position.set(0, 0, 0)
  cam.lookAt(0, 0, -1)
  cam.updateMatrixWorld(true)
  cam.updateProjectionMatrix()
  return cam
}

function viewProjOf(cam: THREE.PerspectiveCamera): number[] {
  return composeMatrices(
    Array.from(cam.projectionMatrix.elements),
    Array.from(cam.matrixWorldInverse.elements),
  )
}

describe('transformPoints', () => {
  it('applies the Y-flip world matrix (rotation.x = PI) — regression for the mirrored-coordinate bug', () => {
    const flip = new THREE.Matrix4().makeRotationX(Math.PI)
    const out = transformPoints(new Float32Array([1, 2, 3]), Array.from(flip.elements))
    expect(out[0]).toBeCloseTo(1, 5)
    expect(out[1]).toBeCloseTo(-2, 5)
    expect(out[2]).toBeCloseTo(-3, 5)
  })

  it('identity matrix leaves points unchanged', () => {
    const id = new THREE.Matrix4()
    const out = transformPoints(new Float32Array([4, -5, 6]), Array.from(id.elements))
    expect(Array.from(out)).toEqual([4, -5, 6])
  })
})

describe('projectToScreen', () => {
  it('projects a point straight ahead to the viewport center', () => {
    const cam = refCamera()
    const { xy, visible } = projectToScreen(new Float32Array([0, 0, -5]), viewProjOf(cam), 800, 800)
    expect(visible[0]).toBe(1)
    expect(xy[0]).toBeCloseTo(400, 3)
    expect(xy[1]).toBeCloseTo(400, 3)
  })

  it('matches THREE.Vector3.project for an off-axis point', () => {
    const cam = refCamera()
    const p = new THREE.Vector3(1.2, -0.7, -4)
    const ndc = p.clone().project(cam)
    const expectedX = (ndc.x * 0.5 + 0.5) * 640
    const expectedY = (-ndc.y * 0.5 + 0.5) * 480
    const { xy, visible } = projectToScreen(new Float32Array([1.2, -0.7, -4]), viewProjOf(cam), 640, 480)
    expect(visible[0]).toBe(1)
    expect(xy[0]).toBeCloseTo(expectedX, 3)
    expect(xy[1]).toBeCloseTo(expectedY, 3)
  })

  it('marks points behind the camera as not visible', () => {
    const cam = refCamera()
    const { visible } = projectToScreen(new Float32Array([0, 0, 5]), viewProjOf(cam), 800, 800)
    expect(visible[0]).toBe(0)
  })
})

describe('selectInPolygon', () => {
  // Triangle in pixel space: (100,100) (300,100) (200,300)
  const tri = [100, 100, 300, 100, 200, 300]

  it('selects points inside and skips points outside', () => {
    const xy = new Float32Array([200, 150 /* inside */, 50, 50 /* outside */, 200, 299 /* inside near apex */])
    const visible = new Uint8Array([1, 1, 1])
    const hits = selectInPolygon(xy, visible, tri)
    expect(Array.from(hits)).toEqual([0, 2])
  })

  it('never selects invisible (behind-camera) points', () => {
    const xy = new Float32Array([200, 150])
    const visible = new Uint8Array([0])
    expect(selectInPolygon(xy, visible, tri).length).toBe(0)
  })
})

describe('selectInMask', () => {
  it('selects points over painted pixels and skips holes', () => {
    // 4x4 RGBA mask, only pixel (2,1) painted
    const data = new Uint8ClampedArray(4 * 4 * 4)
    data[(1 * 4 + 2) * 4 + 3] = 255
    const xy = new Float32Array([2.4, 1.4 /* on painted */, 0.5, 0.5 /* hole */])
    const visible = new Uint8Array([1, 1])
    const hits = selectInMask(xy, visible, data, 4, 4)
    expect(Array.from(hits)).toEqual([0])
  })

  it('ignores points outside the mask bounds', () => {
    const data = new Uint8ClampedArray(4 * 4 * 4).fill(255)
    const xy = new Float32Array([-1, 2, 2, 9])
    const visible = new Uint8Array([1, 1])
    expect(selectInMask(xy, visible, data, 4, 4).length).toBe(0)
  })
})

describe('selectInCircle', () => {
  it('selects within the pixel radius, skips outside and invisible', () => {
    const xy = new Float32Array([100, 100, 130, 100, 100, 101])
    const visible = new Uint8Array([1, 1, 0])
    const hits = selectInCircle(xy, visible, 100, 100, 20)
    expect(Array.from(hits)).toEqual([0])
  })
})

describe('selectInSphere', () => {
  it('respects the boundary radius (inside at r-eps, outside at r+eps)', () => {
    const centers = new Float32Array([0, 0, 0.999, 0, 0, 1.001])
    const hits = selectInSphere(centers, [0, 0, 0], 1)
    expect(Array.from(hits)).toEqual([0])
  })
})

describe('selectInBox', () => {
  it('includes faces and corners, excludes just-outside points', () => {
    const centers = new Float32Array([
      1, 1, 1, // corner — inside (inclusive)
      0, 0, 1, // face — inside
      1.0001, 0, 0, // just outside
    ])
    const hits = selectInBox(centers, [-1, -1, -1], [1, 1, 1])
    expect(Array.from(hits)).toEqual([0, 1])
  })
})
