import { describe, it, expect, beforeEach } from 'vitest'
import { setSubject, applyLevel, getState, clear } from './subjectPreview.ts'
import type { RendererBridge } from './types.ts'

/**
 * v0.8 subject lock-on preview. The tint marks the DELETE-set (live-found at
 * 2M splats: tinting the ~N-splat keep-set wedged the main thread for minutes
 * and washed the scene gold; the excluded set is the small, reviewable one).
 * These tests pin the suffix-cumulative exclusion math, the one-pass
 * clear→add re-tint, clamping, and teardown.
 */
class TintBridge {
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
  selected(): number[] {
    return Array.from(this.selection).sort((a, b) => a - b)
  }
}

describe('subjectPreview (delete-set tint)', () => {
  let b: TintBridge

  beforeEach(() => {
    b = new TintBridge()
    clear(b as unknown as RendererBridge)  // module state survives between tests
    b.calls = []
  })

  // Levels: K0=[1,2], K1=[1,2,3], K2=[1,2,3,4] over universe [1..5].
  // outsideIds = [5] (junk at every level), deltas = [[3],[4]].
  // excluded per level: L0=[3,4,5], L1=[4,5], L2=[5].
  const ARGS = { outsideIds: [5], deltas: [[3], [4]], counts: [2, 3, 4], level: 1 }

  it('setSubject at level 1 tints exactly the level-1 DELETE-set [4,5]', () => {
    const count = setSubject(b as unknown as RendererBridge, { ...ARGS })
    expect(count).toBe(2)
    expect(b.selected()).toEqual([4, 5])
    expect(getState()).toEqual({ counts: [2, 3, 4], level: 1 })
  })

  it('applyLevel re-tints in ONE pass: clear then a single add', () => {
    setSubject(b as unknown as RendererBridge, { ...ARGS, level: 0 })
    b.calls = []
    const count = applyLevel(b as unknown as RendererBridge, 2)
    expect(count).toBe(1)
    expect(b.calls).toEqual(['clear', 'update:add'])
    expect(b.selected()).toEqual([5])
    expect(getState()).toEqual({ counts: [2, 3, 4], level: 2 })
  })

  it('applyLevel clamps out-of-range levels to the valid band', () => {
    setSubject(b as unknown as RendererBridge, { ...ARGS, level: 0 })
    applyLevel(b as unknown as RendererBridge, 99)
    expect(getState()!.level).toBe(2)
    expect(b.selected()).toEqual([5])
    applyLevel(b as unknown as RendererBridge, -7)
    expect(getState()!.level).toBe(0)
    expect(b.selected()).toEqual([3, 4, 5])
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
