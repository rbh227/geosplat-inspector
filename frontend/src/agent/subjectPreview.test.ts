import { describe, it, expect, beforeEach } from 'vitest'
import { setSubject, applyLevel, getState, clear } from './subjectPreview.ts'
import type { RendererBridge } from './types.ts'

/**
 * v0.8 subject lock-on preview, complement form (live-found at 2M splats: the
 * keep-set is ~N ids — 17MB of JSON — while the excluded set is the small
 * one). The controller ships `outsideIds` (excluded at the LOOSEST level) plus
 * per-level deltas; the viewer derives each keep-tint locally as
 * invert-all-then-remove-excluded. These tests pin the suffix-cumulative
 * exclusion math, the clear→invert→remove sequence, clamping, and teardown.
 */
class TintBridge {
  /** The live-id universe invertSelection() draws from. */
  universe = [1, 2, 3, 4, 5]
  selection = new Set<number>()
  calls: string[] = []
  updateSelection(ids: Iterable<number>, mode: 'add' | 'remove' = 'add'): number {
    for (const id of ids) {
      if (mode === 'add') this.selection.add(id)
      else this.selection.delete(id)
    }
    this.calls.push(`update:${mode}`)
    return this.selection.size
  }
  clearSelection(): number {
    this.selection.clear()
    this.calls.push('clear')
    return 0
  }
  invertSelection(): number {
    const next = new Set<number>()
    for (const id of this.universe) if (!this.selection.has(id)) next.add(id)
    this.selection = next
    this.calls.push('invert')
    return this.selection.size
  }
  selected(): number[] {
    return Array.from(this.selection).sort((a, b) => a - b)
  }
}

describe('subjectPreview (complement form)', () => {
  let b: TintBridge

  beforeEach(() => {
    b = new TintBridge()
    clear(b as unknown as RendererBridge)  // module state survives between tests
    b.calls = []
  })

  // Levels over universe [1..5]: K0=[1,2], K1=[1,2,3], K2=[1,2,3,4].
  // outsideIds = [5] (excluded even at the loosest), deltas = [[3],[4]].
  const ARGS = { outsideIds: [5], deltas: [[3], [4]], counts: [2, 3, 4], level: 1 }

  it('setSubject at level 1 tints exactly the level-1 keep-set [1,2,3]', () => {
    const count = setSubject(b as unknown as RendererBridge, { ...ARGS })
    expect(count).toBe(3)
    expect(b.selected()).toEqual([1, 2, 3])
    expect(getState()).toEqual({ counts: [2, 3, 4], level: 1 })
  })

  it('applyLevel re-tints via clear → invert-all → remove-excluded', () => {
    setSubject(b as unknown as RendererBridge, { ...ARGS, level: 0 })
    b.calls = []
    const count = applyLevel(b as unknown as RendererBridge, 2)
    expect(count).toBe(4)
    expect(b.calls).toEqual(['clear', 'invert', 'update:remove'])
    expect(b.selected()).toEqual([1, 2, 3, 4])
    expect(getState()).toEqual({ counts: [2, 3, 4], level: 2 })
  })

  it('applyLevel clamps out-of-range levels to the valid band', () => {
    setSubject(b as unknown as RendererBridge, { ...ARGS, level: 0 })
    applyLevel(b as unknown as RendererBridge, 99)
    expect(getState()!.level).toBe(2)
    expect(b.selected()).toEqual([1, 2, 3, 4])
    applyLevel(b as unknown as RendererBridge, -7)
    expect(getState()!.level).toBe(0)
    expect(b.selected()).toEqual([1, 2])
  })

  it('applyLevel with no subject set is a harmless no-op returning 0', () => {
    expect(applyLevel(b as unknown as RendererBridge, 1)).toBe(0)
    expect(b.calls).toEqual([])
  })

  it('clear empties both the module state and the viewport selection', () => {
    setSubject(b as unknown as RendererBridge, { ...ARGS })
    clear(b as unknown as RendererBridge)
    expect(getState()).toBeNull()
    expect(b.selected()).toEqual([])
    expect(b.calls.at(-1)).toBe('clear')
  })
})
