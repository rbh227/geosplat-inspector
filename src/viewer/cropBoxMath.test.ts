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
