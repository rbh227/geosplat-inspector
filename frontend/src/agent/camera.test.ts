import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { clampToCore, poseForBox, resolveAimPoint, sceneCoverage, toRenderSpace } from './camera.ts'
import { computeCoreBounds } from '../../../src/viewer/framing.ts'
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

describe('sceneCoverage (R2 framing signal)', () => {
  const core = { center: [0, 0, 0] as [number, number, number], radius: 5 }

  it('is ~0.5 when the core radius is half the view half-height (fov 90)', () => {
    // fov 90 -> tan(45)=1, halfHeight = dist; at dist 10, coverage = r/dist = 0.5
    const c = sceneCoverage(new THREE.Vector3(0, 0, 10), 90, core)
    expect(c).toBeCloseTo(0.5, 5)
  })

  it('reports too-far as a small fraction', () => {
    expect(sceneCoverage(new THREE.Vector3(0, 0, 100), 90, core)).toBeCloseTo(0.05, 5)
  })

  it('clamps to 1 when very close', () => {
    expect(sceneCoverage(new THREE.Vector3(0, 0, 2), 90, core)).toBe(1)
  })

  it('is 0 with no core', () => {
    expect(sceneCoverage(new THREE.Vector3(0, 0, 10), 90, null)).toBe(0)
  })
})

describe('coverage back-off policy on a floater-heavy scene (regression)', () => {
  it('backing off until coverage ≤0.9 keeps the dense mass filling the view', () => {
    // Reproduces the 2026-07-23 live failure: the agent obeys the prompt rule
    // "coverage >0.9 → back off", and with a floater-inflated core it kept
    // retreating until the real scene was a speck. Percept and policy must
    // agree: at the first "not too close" reading, the dense mass (median
    // distance from center) must still fill a meaningful part of the view.
    let seed = 7
    const rand = () => {
      seed = (seed * 1664525 + 1013904223) >>> 0
      return seed / 2 ** 32
    }
    const pts = []
    for (let i = 0; i < 850; i++) {
      pts.push({ x: rand() * 2 - 1, y: rand() * 2 - 1, z: rand() * 2 - 1 })
    }
    for (let i = 0; i < 150; i++) {
      const r = 100 + rand() * 900
      const u = rand() * 2 - 1
      const phi = rand() * 2 * Math.PI
      const s = Math.sqrt(1 - u * u)
      pts.push({ x: r * s * Math.cos(phi), y: r * u, z: r * s * Math.sin(phi) })
    }
    const core = computeCoreBounds(pts)!
    const center = new THREE.Vector3(...core.center)

    const fov = 60
    let dist = 2 // operator starts with the dense mass framed
    while (
      sceneCoverage(center.clone().add(new THREE.Vector3(0, 0, dist)), fov, core) > 0.9
    ) {
      dist *= 1.25
    }

    const dists = pts
      .map((p) => Math.hypot(p.x - core.center[0], p.y - core.center[1], p.z - core.center[2]))
      .sort((a, b) => a - b)
    const denseR = dists[Math.floor(dists.length / 2)]
    const halfHeight = Math.tan((fov * Math.PI) / 360) * dist
    expect(denseR / halfHeight).toBeGreaterThan(0.25)
  })
})

describe('clampToCore (R2 dolly safety limit)', () => {
  const core = { center: [0, 0, 0] as [number, number, number], radius: 10 }

  it('pulls a too-close destination out to minFactor·radius', () => {
    const v = clampToCore(new THREE.Vector3(0, 0, 1), core) // dist 1, min = 5
    expect(v.length()).toBeCloseTo(5, 5)
  })

  it('pushes a too-far destination in to maxFactor·radius', () => {
    const v = clampToCore(new THREE.Vector3(0, 0, 1000), core) // dist 1000, max = 120
    expect(v.length()).toBeCloseTo(120, 5)
  })

  it('leaves an in-band destination unchanged', () => {
    const inBand = new THREE.Vector3(0, 0, 40)
    expect(clampToCore(inBand, core)).toBe(inBand)
  })

  it('is a no-op with no core', () => {
    const p = new THREE.Vector3(0, 0, 1)
    expect(clampToCore(p, null)).toBe(p)
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
