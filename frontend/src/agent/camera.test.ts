import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { clampToCore, coreInView, poseForBox, resolveAimPoint, sceneCoverage, surveyPoses, toRenderSpace } from './camera.ts'
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

describe('coreInView (direction-aware coverage companion)', () => {
  const core = { center: [0, 0, 0] as [number, number, number], radius: 1 }
  function cam(pos: [number, number, number], look: [number, number, number]): THREE.PerspectiveCamera {
    const c = new THREE.PerspectiveCamera(60, 1.6)
    c.position.set(...pos)
    c.lookAt(new THREE.Vector3(...look))
    c.updateMatrixWorld()
    return c
  }

  it('true when the camera faces the core', () => {
    expect(coreInView(cam([0, 0, 10], [0, 0, 0]), core)).toBe(true)
  })
  it('false when the core is behind the camera (coverage alone still reads well-framed)', () => {
    expect(coreInView(cam([0, 0, 10], [0, 0, 20]), core)).toBe(false)
  })
  it('false when the core is outside the frustum', () => {
    expect(coreInView(cam([0, 0, 10], [30, 0, 10]), core)).toBe(false)
  })
  it('false with no core', () => {
    expect(coreInView(cam([0, 0, 10], [0, 0, 0]), null)).toBe(false)
  })
})

describe('surveyPoses', () => {
  const camera = new THREE.PerspectiveCamera(60, 16 / 9)
  const core = { center: [10, 2, -5] as [number, number, number], radius: 4 }

  it('returns three labeled poses, all targeting the core center', () => {
    const poses = surveyPoses(camera, core)
    expect(poses.map((p) => p.label)).toEqual([
      'top-down',
      'oblique view from the north-east',
      'oblique view from the south-west',
    ])
    for (const p of poses) {
      expect(p.target.toArray()).toEqual(core.center)
    }
  })

  it('places every pose at the same framing distance, outside the core sphere', () => {
    const poses = surveyPoses(camera, core)
    const c = new THREE.Vector3(...core.center)
    const dists = poses.map((p) => p.position.distanceTo(c))
    for (const d of dists) {
      expect(d).toBeGreaterThan(core.radius)
      expect(Math.abs(d - dists[0])).toBeLessThan(1e-6)
    }
  })

  it('top-down sits high above the center; obliques at moderate, opposite azimuths', () => {
    const [top, ne, sw] = surveyPoses(camera, core)
    const elevation = (p: THREE.Vector3) => {
      const dy = p.y - core.center[1]
      const dh = Math.hypot(p.x - core.center[0], p.z - core.center[2])
      return (Math.atan2(dy, dh) * 180) / Math.PI
    }
    expect(elevation(top.position)).toBeGreaterThan(80)
    expect(elevation(ne.position)).toBeCloseTo(35, 0)
    expect(elevation(sw.position)).toBeCloseTo(35, 0)
    const h = (p: THREE.Vector3) =>
      new THREE.Vector2(p.x - core.center[0], p.z - core.center[2]).normalize()
    expect(h(ne.position).dot(h(sw.position))).toBeLessThan(-0.99)
  })
})

describe('surveyPoses — operator anchoring (v0.8.2)', () => {
  const camera = new THREE.PerspectiveCamera(60, 16 / 9)
  // A junk-inflated core: data framing would fly ~hundreds of units out.
  const core = { center: [0, 0, 0] as [number, number, number], radius: 160 }

  it('never flies farther out than the operator', () => {
    const anchor = {
      position: new THREE.Vector3(0, 20, 55),   // operator zoomed into the scene
      target: new THREE.Vector3(0, 0, 0),
    }
    const far = surveyPoses(camera, core)[0].position.length()
    for (const p of surveyPoses(camera, core, anchor)) {
      const d = p.position.distanceTo(p.target)
      expect(d).toBeLessThanOrEqual(anchor.position.length() + 1e-6)
      expect(d).toBeLessThan(far)               // strictly closer than data framing
    }
  })

  it('adopts the operator look-target when it plausibly sits on the scene', () => {
    const anchor = {
      position: new THREE.Vector3(30, 20, 30),
      target: new THREE.Vector3(12, 0, -8),     // inside 1.5x core radius
    }
    for (const p of surveyPoses(camera, core, anchor)) {
      expect(p.target.toArray()).toEqual([12, 0, -8])
    }
  })

  it('ignores an off-scene target and clamps an extreme close-up to the floor', () => {
    const anchor = {
      position: new THREE.Vector3(0, 0, 1),     // nose against one car
      target: new THREE.Vector3(9999, 0, 0),    // aimed off into the void
    }
    for (const p of surveyPoses(camera, core, anchor)) {
      expect(p.target.toArray()).toEqual([0, 0, 0])                 // core center kept
      const d = p.position.distanceTo(p.target)
      expect(d).toBeGreaterThanOrEqual(core.radius * 0.1 - 1e-6)    // the floor holds
    }
  })
})

describe('occluded-window resilience (nextStep)', () => {
  it('animateTo completes even when requestAnimationFrame never fires', async () => {
    // macOS throttles rAF to ZERO in occluded/backgrounded windows — this
    // froze every agent flight mid-survey (live-found, three runs in a row).
    const { animateTo } = await import('./camera.ts')
    const original = globalThis.requestAnimationFrame
    // @ts-expect-error simulate a fully throttled window
    globalThis.requestAnimationFrame = undefined
    try {
      const poses: THREE.Vector3[] = []
      const bridge = {
        getCameraPose: () => ({ position: new THREE.Vector3(0, 0, 0), target: new THREE.Vector3(0, 0, -1) }),
        setCameraPose: (p: THREE.Vector3) => { poses.push(p.clone()) },
      }
      await animateTo(bridge as unknown as RendererBridge, new THREE.Vector3(2, 0, 0), new THREE.Vector3(0, 0, 0), 60)
      expect(poses.length).toBeGreaterThan(0)
      expect(poses.at(-1)!.x).toBe(2)     // landed on the target pose
    } finally {
      globalThis.requestAnimationFrame = original
    }
  }, 10000)

  it('animateOrbit completes without requestAnimationFrame too', async () => {
    const { animateOrbit } = await import('./camera.ts')
    const original = globalThis.requestAnimationFrame
    // @ts-expect-error simulate a fully throttled window
    globalThis.requestAnimationFrame = undefined
    try {
      let last: THREE.Vector3 | null = null
      const bridge = {
        getCameraPose: () => ({ position: new THREE.Vector3(1, 0, 0), target: new THREE.Vector3(0, 0, 0) }),
        setCameraPose: (p: THREE.Vector3) => { last = p.clone() },
      }
      await animateOrbit(bridge as unknown as RendererBridge, new THREE.Vector3(0, 0, 0), 'y', 180, 60)
      expect(last).not.toBeNull()
    } finally {
      globalThis.requestAnimationFrame = original
    }
  }, 10000)
})
