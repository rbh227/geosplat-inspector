import { describe, it, expect } from 'vitest'
import { computeFraming, computeCoreBounds, nearFarForDistance, type Vec3 } from './framing'

/** Elevation of the camera above the target's horizontal plane, in degrees. */
function elevationDeg(target: number[], position: number[]): number {
  const dx = position[0] - target[0]
  const dy = position[1] - target[1]
  const dz = position[2] - target[2]
  return (Math.atan2(dy, Math.hypot(dx, dz)) * 180) / Math.PI
}

/** Build a deterministic grid of points within the given half-extents. */
function grid(hx: number, hy: number, hz: number, steps = 6): Vec3[] {
  const pts: Vec3[] = []
  for (let i = 0; i <= steps; i++) {
    for (let j = 0; j <= steps; j++) {
      for (let k = 0; k <= steps; k++) {
        pts.push({
          x: -hx + (2 * hx * i) / steps,
          y: -hy + (2 * hy * j) / steps,
          z: -hz + (2 * hz * k) / steps,
        })
      }
    }
  }
  return pts
}

describe('computeFraming', () => {
  it('returns a high elevation for a wide, flat scene', () => {
    const f = computeFraming(grid(10, 0.1, 10), 60, 1.5)!
    expect(f).not.toBeNull()
    expect(elevationDeg(f.target, f.position)).toBeGreaterThan(45)
  })

  it('returns a moderate elevation for a cube-like scene', () => {
    const f = computeFraming(grid(1, 1, 1), 60, 1.5)!
    const el = elevationDeg(f.target, f.position)
    expect(el).toBeGreaterThanOrEqual(22)
    expect(el).toBeLessThanOrEqual(55)
  })

  it('uses a lower elevation for a tall scene than for a flat one', () => {
    const flat = computeFraming(grid(10, 0.1, 10), 60, 1.5)!
    const tall = computeFraming(grid(0.5, 10, 0.5), 60, 1.5)!
    expect(elevationDeg(tall.target, tall.position)).toBeLessThan(
      elevationDeg(flat.target, flat.position),
    )
  })

  it('ignores far floaters via percentile bounds (streak-bug regression)', () => {
    const core = grid(1, 1, 1)
    const withFloaters: Vec3[] = [
      ...core,
      { x: 1000, y: 1000, z: 1000 },
      { x: -900, y: 800, z: -700 },
      { x: 1200, y: -1100, z: 950 },
    ]
    const a = computeFraming(core, 60, 1.5)!
    const b = computeFraming(withFloaters, 60, 1.5)!

    // Target (core center) stays near the origin despite the floaters.
    expect(Math.hypot(...(b.target as [number, number, number]))).toBeLessThan(0.5)
    // Distance is within a small tolerance of the floater-free framing.
    const da = Math.hypot(a.position[0] - a.target[0], a.position[1] - a.target[1], a.position[2] - a.target[2])
    const db = Math.hypot(b.position[0] - b.target[0], b.position[1] - b.target[1], b.position[2] - b.target[2])
    expect(Math.abs(db - da) / da).toBeLessThan(0.2)
  })

  it('returns null for degenerate input', () => {
    expect(computeFraming([], 60, 1.5)).toBeNull()
    expect(computeFraming([{ x: 0, y: 0, z: 0 }], 60, 1.5)).toBeNull()
  })

  it('produces finite numbers (no NaN)', () => {
    const f = computeFraming(grid(3, 2, 5), 60, 1.778)!
    for (const v of [...f.target, ...f.position]) expect(Number.isFinite(v)).toBe(true)
  })
})

describe('computeCoreBounds', () => {
  it('centers on the robust core and ignores floaters', () => {
    const core = grid(2, 2, 2)
    const b = computeCoreBounds([...core, { x: 500, y: 500, z: 500 }])!
    expect(Math.hypot(...(b.center as [number, number, number]))).toBeLessThan(0.5)
    expect(b.radius).toBeGreaterThan(0)
    expect(b.radius).toBeLessThan(20)
  })

  it('returns null for empty input', () => {
    expect(computeCoreBounds([])).toBeNull()
  })
})

describe('nearFarForDistance', () => {
  it('produces a sane frustum for a small scene', () => {
    const { near, far } = nearFarForDistance(5, 2)
    expect(near).toBeGreaterThan(0)
    expect(near).toBeLessThan(far)
    expect(far).toBeGreaterThan(5 + 2)
  })

  it('keeps near from collapsing on a large scene', () => {
    const { near, far } = nearFarForDistance(500, 200)
    // near is floored well above sub-millimetre values that wreck precision.
    expect(near).toBeGreaterThanOrEqual(0.01)
    expect(near).toBeGreaterThan(0.0001)
    expect(near).toBeLessThan(far)
    // far comfortably clears the far edge of the scene (distance + radius).
    expect(far).toBeGreaterThan(500 + 200)
    expect(far).toBeGreaterThan((500 + 200) * 2)
  })

  it('produces finite numbers for both small and large scenes', () => {
    for (const [d, r] of [[5, 2], [500, 200]] as const) {
      const { near, far } = nearFarForDistance(d, r)
      expect(Number.isFinite(near)).toBe(true)
      expect(Number.isFinite(far)).toBe(true)
    }
  })
})
