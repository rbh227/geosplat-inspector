import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { poseForBox, resolveAimPoint, toRenderSpace } from './camera.ts'
import type { RendererBridge } from './types.ts'

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

describe('resolveAimPoint (origin-default backstop)', () => {
  const offOriginCore = { center: [2000, 3000, 5000] as [number, number, number], radius: 2449 }

  it('substitutes the world-space scene center when the model aims at [0,0,0]', () => {
    const v = resolveAimPoint([0, 0, 0], offOriginCore)
    // core.center is already world-space — returned as-is, NOT flipped
    expect([v.x, v.y, v.z]).toEqual([2000, 3000, 5000])
  })

  it('substitutes the scene center when no target is given', () => {
    const v = resolveAimPoint(undefined, offOriginCore)
    expect([v.x, v.y, v.z]).toEqual([2000, 3000, 5000])
  })

  it('respects an explicit non-origin target (flips it to render space)', () => {
    const v = resolveAimPoint([1, 2, 3], offOriginCore)
    expect([v.x, v.y, v.z]).toEqual([1, -2, -3])
  })

  it('leaves a genuinely origin-centered scene at the origin', () => {
    // center within 5% of the radius of the origin -> not overridden
    const nearOrigin = { center: [0, 0, 0.01] as [number, number, number], radius: 5 }
    const v = resolveAimPoint([0, 0, 0], nearOrigin)
    expect(v.equals(new THREE.Vector3(0, 0, 0))).toBe(true)
  })

  it('falls back to the flipped raw point when no core is available', () => {
    const v = resolveAimPoint([0, 0, 0], null)
    expect(v.equals(new THREE.Vector3(0, 0, 0))).toBe(true)
  })
})

describe('poseForBox framing clamp (A2)', () => {
  function fakeBridge(fovDeg: number): RendererBridge {
    const cam = new THREE.PerspectiveCamera(fovDeg, 1, 0.1, 1000)
    return {
      getCamera: () => cam,
      getCameraPose: () => ({
        position: new THREE.Vector3(1, 0, 0),
        target: new THREE.Vector3(0, 0, 0),
      }),
    } as unknown as RendererBridge
  }

  it('caps camera distance at MAX_FRAME_FACTOR·radius on a large scene', () => {
    // half-extent 1000 -> radius = size.length()/2 = (2000·√3)/2 ≈ 1732
    const box = new THREE.Box3(
      new THREE.Vector3(-1000, -1000, -1000),
      new THREE.Vector3(1000, 1000, 1000),
    )
    const radius = box.getSize(new THREE.Vector3()).length() * 0.5
    // Narrow FOV would push framing distance to ~18·radius without the clamp.
    const pose = poseForBox(fakeBridge(10), box)
    const dist = pose.position.distanceTo(box.getCenter(new THREE.Vector3()))
    expect(dist).toBeLessThanOrEqual(radius * 5 + 1e-6)
    expect(dist).toBeGreaterThan(radius) // still outside the scene, not inside it
  })
})
