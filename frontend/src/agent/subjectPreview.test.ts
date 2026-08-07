import { describe, it, expect, beforeEach } from 'vitest'
import { setSubject, applyLevel, getState, clear } from './subjectPreview.ts'
import type { RendererBridge } from './types.ts'

/**
 * v0.8 subject lock-on preview: the controller ships nested keep-levels ONCE
 * and the card's slider re-tints locally. These tests pin the cumulative-level
 * math (base + deltas), the clear-before-retint sequence, level clamping, and
 * the state teardown.
 */
class TintBridge {
  calls: Array<{ op: 'update'; ids: number[]; mode: string } | { op: 'clear' }> = []
  updateSelection(ids: Iterable<number>, mode: 'add' | 'remove' = 'add'): number {
    const arr = Array.from(ids)
    this.calls.push({ op: 'update', ids: arr, mode })
    return arr.length
  }
  clearSelection(): number {
    this.calls.push({ op: 'clear' })
    return 0
  }
  lastTint(): number[] | null {
    for (let i = this.calls.length - 1; i >= 0; i--) {
      const c = this.calls[i]
      if (c.op === 'update') return c.ids
    }
    return null
  }
}

function bridge(): TintBridge {
  return new TintBridge()
}

describe('subjectPreview', () => {
  let b: TintBridge

  beforeEach(() => {
    b = bridge()
    clear(b as unknown as RendererBridge)  // module state survives between tests
    b.calls = []
  })

  it('setSubject with base [1,2], deltas [[3],[4,5]], level 1 tints exactly [1,2,3]', () => {
    const count = setSubject(b as unknown as RendererBridge, {
      baseIds: [1, 2], deltas: [[3], [4, 5]], counts: [2, 3, 5], level: 1,
    })
    expect(count).toBe(3)
    expect(b.lastTint()).toEqual([1, 2, 3])
    expect(getState()).toEqual({ counts: [2, 3, 5], level: 1 })
  })

  it('applyLevel(2) re-tints [1,2,3,4,5] with a clearSelection first', () => {
    setSubject(b as unknown as RendererBridge, {
      baseIds: [1, 2], deltas: [[3], [4, 5]], counts: [2, 3, 5], level: 0,
    })
    b.calls = []
    const count = applyLevel(b as unknown as RendererBridge, 2)
    expect(count).toBe(5)
    expect(b.calls[0]).toEqual({ op: 'clear' })
    expect(b.lastTint()).toEqual([1, 2, 3, 4, 5])
    expect(getState()).toEqual({ counts: [2, 3, 5], level: 2 })
  })

  it('applyLevel clamps out-of-range levels to the valid band', () => {
    setSubject(b as unknown as RendererBridge, {
      baseIds: [1, 2], deltas: [[3], [4, 5]], counts: [2, 3, 5], level: 0,
    })
    applyLevel(b as unknown as RendererBridge, 99)
    expect(getState()!.level).toBe(2)
    expect(b.lastTint()).toEqual([1, 2, 3, 4, 5])
    applyLevel(b as unknown as RendererBridge, -7)
    expect(getState()!.level).toBe(0)
    expect(b.lastTint()).toEqual([1, 2])
  })

  it('applyLevel with no subject set is a harmless no-op returning 0', () => {
    expect(applyLevel(b as unknown as RendererBridge, 1)).toBe(0)
    expect(b.calls).toEqual([])
  })

  it('clear empties both the module state and the viewport selection', () => {
    setSubject(b as unknown as RendererBridge, {
      baseIds: [1, 2], deltas: [[3]], counts: [2, 3], level: 1,
    })
    clear(b as unknown as RendererBridge)
    expect(getState()).toBeNull()
    expect(b.calls.at(-1)).toEqual({ op: 'clear' })
  })
})
