import { describe, expect, it } from 'vitest'
import { IdMap } from './idMap.ts'

/** Simulate a compact-write pass keeping original IDs not in `dead`. */
function compactDeleting(map: IdMap, dead: Set<number>): number {
  let writeIdx = 0
  const n = map.liveCount
  for (let i = 0; i < n; i++) {
    if (!dead.has(map.idAt(i))) {
      map.retain(writeIdx, i)
      writeIdx++
    }
  }
  map.setLive(writeIdx)
  return n - writeIdx
}

describe('IdMap', () => {
  it('initializes to identity 0..N-1', () => {
    const m = new IdMap(5)
    expect(Array.from(m.liveIds())).toEqual([0, 1, 2, 3, 4])
  })

  it('deleting IDs {2,5} leaves original IDs with 2 and 5 absent', () => {
    const m = new IdMap(7)
    compactDeleting(m, new Set([2, 5]))
    expect(Array.from(m.liveIds())).toEqual([0, 1, 3, 4, 6])
  })

  it('two successive deletes compose — IDs stay original, never re-indexed', () => {
    const m = new IdMap(7)
    compactDeleting(m, new Set([2, 5]))
    // second delete targets ORIGINAL id 4 (now at packed index 3)
    compactDeleting(m, new Set([4]))
    expect(Array.from(m.liveIds())).toEqual([0, 1, 3, 6])
  })

  it('empty delete set is a no-op', () => {
    const m = new IdMap(4)
    const removed = compactDeleting(m, new Set())
    expect(removed).toBe(0)
    expect(Array.from(m.liveIds())).toEqual([0, 1, 2, 3])
  })

  it('deleting all IDs empties the map', () => {
    const m = new IdMap(3)
    compactDeleting(m, new Set([0, 1, 2]))
    expect(m.liveCount).toBe(0)
    expect(m.liveIds().length).toBe(0)
  })

  it('undo restores the pre-delete map exactly (snapshot/restore symmetry)', () => {
    const m = new IdMap(6)
    compactDeleting(m, new Set([1])) // state A: [0,2,3,4,5]
    const snap = m.snapshot()
    compactDeleting(m, new Set([3, 5])) // state B: [0,2,4]
    expect(Array.from(m.liveIds())).toEqual([0, 2, 4])
    m.restore(snap)
    expect(Array.from(m.liveIds())).toEqual([0, 2, 3, 4, 5])
  })
})
