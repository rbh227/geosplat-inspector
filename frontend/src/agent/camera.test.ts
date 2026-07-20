import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { toRenderSpace } from './camera.ts'

describe('toRenderSpace', () => {
  it('negates Y and Z, leaves X (the splat mesh rotation.x=PI flip)', () => {
    const v = toRenderSpace([1, 2, 3])
    expect(v).toBeInstanceOf(THREE.Vector3)
    expect(v.x).toBe(1)
    expect(v.y).toBe(-2)
    expect(v.z).toBe(-3)
  })

  it('matches a 180° rotation about the X axis (overlay markersGroup convention)', () => {
    const inputs: [number, number, number][] = [
      [1, 2, 3],
      [0, 0, 0],
      [-4, 5, -6],
      [0.5, -0.25, 7.5],
    ]
    for (const p of inputs) {
      const rotated = new THREE.Vector3(p[0], p[1], p[2]).applyAxisAngle(
        new THREE.Vector3(1, 0, 0),
        Math.PI,
      )
      const mapped = toRenderSpace(p)
      // applyAxisAngle introduces tiny float error for the rotated components.
      expect(mapped.x).toBeCloseTo(rotated.x, 10)
      expect(mapped.y).toBeCloseTo(rotated.y, 10)
      expect(mapped.z).toBeCloseTo(rotated.z, 10)
    }
  })

  it('accepts any ArrayLike (e.g. a Float32Array)', () => {
    const v = toRenderSpace(new Float32Array([1, 2, 3]))
    expect(v.x).toBe(1)
    expect(v.y).toBe(-2)
    expect(v.z).toBe(-3)
  })
})
