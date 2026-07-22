import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { adjustBox, viewBasisFromCamera } from './proposalBox.ts'
import type { Box, ViewBasis } from './proposalBox.ts'

// An axis-aligned backend basis: right=+x, up=+y, forward=-z (the operator
// looking down -z, the render→backend involution already applied).
const AXIS_ALIGNED: ViewBasis = {
  right: [1, 0, 0],
  up: [0, 1, 0],
  forward: [0, 0, -1],
}

// A 2×2×2 box centered at the origin — extents are all 2.
const UNIT_BOX: Box = { min: [-1, -1, -1], max: [1, 1, 1] }

describe('adjustBox — shift (axis-aligned camera)', () => {
  it('shift:[1,0,0] moves the box +x by exactly its x-extent', () => {
    const out = adjustBox(UNIT_BOX, AXIS_ALIGNED, { shift: [1, 0, 0] })
    // extent_x = 2, sign +x -> box slides +2 in x, y/z untouched
    expect(out.min).toEqual([1, -1, -1])
    expect(out.max).toEqual([3, 1, 1])
  })

  it('shift:[0,0,1] moves the box -z by its z-extent (forward=-z)', () => {
    const out = adjustBox(UNIT_BOX, AXIS_ALIGNED, { shift: [0, 0, 1] })
    // forward view axis dominant world z with sign -1 -> slides -2 in z
    expect(out.min).toEqual([-1, -1, -3])
    expect(out.max).toEqual([1, 1, -1])
  })
})

describe('adjustBox — grow', () => {
  it('grow:2 doubles every extent about a fixed center', () => {
    const out = adjustBox(UNIT_BOX, AXIS_ALIGNED, { grow: 2 })
    expect(out.min).toEqual([-2, -2, -2])
    expect(out.max).toEqual([2, 2, 2])
  })

  it('grow keeps the center fixed for an off-center box', () => {
    const box: Box = { min: [2, 2, 2], max: [4, 4, 4] } // center (3,3,3), extent 2
    const out = adjustBox(box, AXIS_ALIGNED, { grow: 3 })
    // extent 2*3 = 6, half 3 about center 3 -> [0,0,0]..[6,6,6]
    expect(out.min).toEqual([0, 0, 0])
    expect(out.max).toEqual([6, 6, 6])
  })
})

describe('adjustBox — grow_axes (single axis)', () => {
  it('grow_axes:[2,1,1] doubles only the x-extent', () => {
    const out = adjustBox(UNIT_BOX, AXIS_ALIGNED, { grow_axes: [2, 1, 1] })
    // x-extent 2*2 -> half 2; y,z unchanged
    expect(out.min).toEqual([-2, -1, -1])
    expect(out.max).toEqual([2, 1, 1])
  })
})

describe('viewBasisFromCamera', () => {
  it('extracts a default camera as right→+x, up→-y, forward→+z (render→backend)', () => {
    // A default THREE camera looks down render -z. render basis
    // right=(1,0,0) up=(0,1,0) forward=(0,0,-1); negating y,z gives backend
    // right=(1,0,0) up=(0,-1,0) forward=(0,0,1).
    const cam = new THREE.PerspectiveCamera(60, 1, 0.1, 100)
    cam.updateMatrixWorld()
    const basis = viewBasisFromCamera(cam)
    expect(basis.right[0]).toBeCloseTo(1, 10)
    expect(basis.right[1]).toBeCloseTo(0, 10)
    expect(basis.right[2]).toBeCloseTo(0, 10)
    expect(basis.up[0]).toBeCloseTo(0, 10)
    expect(basis.up[1]).toBeCloseTo(-1, 10)
    expect(basis.up[2]).toBeCloseTo(0, 10)
    expect(basis.forward[0]).toBeCloseTo(0, 10)
    expect(basis.forward[1]).toBeCloseTo(0, 10)
    expect(basis.forward[2]).toBeCloseTo(1, 10)
  })

  it('returns unit vectors', () => {
    const cam = new THREE.PerspectiveCamera(50, 1.7, 0.1, 100)
    cam.position.set(3, 4, 5)
    cam.lookAt(0, 0, 0)
    const basis = viewBasisFromCamera(cam)
    for (const v of [basis.right, basis.up, basis.forward]) {
      expect(Math.hypot(v[0], v[1], v[2])).toBeCloseTo(1, 10)
    }
  })

  it('a camera yawed 40° still snaps right→x (shift moves x only)', () => {
    const cam = new THREE.PerspectiveCamera(60, 1, 0.1, 100)
    cam.rotateY((40 * Math.PI) / 180) // yaw within |40°| < 45° keeps x dominant
    const basis = viewBasisFromCamera(cam)
    const out = adjustBox(UNIT_BOX, basis, { shift: [1, 0, 0] })
    // right snaps to the x axis: only x moves, y and z are untouched
    expect(out.min[1]).toBe(-1)
    expect(out.max[1]).toBe(1)
    expect(out.min[2]).toBe(-1)
    expect(out.max[2]).toBe(1)
    expect(out.min[0]).not.toBe(-1) // x did move
  })
})
