import { describe, expect, it } from 'vitest'
import { HIGHLIGHT_RGB, TINT_STRENGTH, TintStore, tintedColor, type RGB } from './selectionTint.ts'
import { IdMap } from './idMap.ts'

describe('tintedColor', () => {
  it('lerps 60% toward the warm highlight by default', () => {
    const [r, g, b] = tintedColor([0, 0, 0])
    expect(r).toBeCloseTo(HIGHLIGHT_RGB[0] * TINT_STRENGTH)
    expect(g).toBeCloseTo(HIGHLIGHT_RGB[1] * TINT_STRENGTH)
    expect(b).toBeCloseTo(HIGHLIGHT_RGB[2] * TINT_STRENGTH)
  })

  it('strength 0 leaves the color untouched, strength 1 is the pure highlight', () => {
    expect(tintedColor([0.3, 0.4, 0.5], 0)).toEqual([0.3, 0.4, 0.5])
    const pure = tintedColor([0.3, 0.4, 0.5], 1)
    expect(pure[0]).toBeCloseTo(HIGHLIGHT_RGB[0])
    expect(pure[1]).toBeCloseTo(HIGHLIGHT_RGB[1])
    expect(pure[2]).toBeCloseTo(HIGHLIGHT_RGB[2])
  })

  it('a warmer original moves less than a cool one (component-wise lerp)', () => {
    // green channel: from 0 climbs toward 0.75; from 0.75 stays put
    expect(tintedColor([0, 0, 0])[1]).toBeGreaterThan(0)
    expect(tintedColor([1, 0.75, 0.2])).toEqual([1, 0.75, 0.2])
  })
})

describe('TintStore', () => {
  it('remembers the FIRST color only — a re-tint never overwrites the original', () => {
    const s = new TintStore()
    s.remember(7, [0.1, 0.2, 0.3])
    s.remember(7, [0.9, 0.9, 0.9]) // already tinted — must be ignored
    expect(s.original(7)).toEqual([0.1, 0.2, 0.3])
  })

  it('tracks size and clears', () => {
    const s = new TintStore()
    expect(s.size).toBe(0)
    s.remember(1, [0, 0, 0])
    s.remember(2, [0, 0, 0])
    expect(s.size).toBe(2)
    expect(s.has(1)).toBe(true)
    s.clear()
    expect(s.size).toBe(0)
    expect(s.has(1)).toBe(false)
    expect(s.original(1)).toBeUndefined()
  })
})

/**
 * End-to-end store/restore contract against a simulated packed buffer + IdMap,
 * the way SceneManager drives it. Colors keyed by packed index; selection and
 * the tint store speak original IDs. Proves restore recovers colors EXACTLY —
 * even after a compaction reshuffles packed indices between apply and restore.
 */
describe('tint apply/restore over a simulated packed buffer', () => {
  type Buffer = RGB[]

  function applyTint(buf: Buffer, map: IdMap, selection: Set<number>, store: TintStore): void {
    for (let i = 0; i < map.liveCount; i++) {
      const id = map.idAt(i)
      if (!selection.has(id)) continue
      store.remember(id, [...buf[i]] as RGB)
      buf[i] = tintedColor(store.original(id)!)
    }
  }

  function restoreTint(buf: Buffer, map: IdMap, store: TintStore): void {
    for (let i = 0; i < map.liveCount; i++) {
      const orig = store.original(map.idAt(i))
      if (!orig) continue
      buf[i] = [...orig] as RGB
    }
    store.clear()
  }

  it('restores exact original colors on deselect', () => {
    const original: Buffer = [
      [0.10, 0.20, 0.30],
      [0.40, 0.50, 0.60],
      [0.70, 0.10, 0.90],
      [0.05, 0.05, 0.05],
    ]
    const buf: Buffer = original.map((c) => [...c] as RGB)
    const map = new IdMap(4)
    const store = new TintStore()

    applyTint(buf, map, new Set([1, 3]), store)
    // selected splats visibly changed...
    expect(buf[1]).not.toEqual(original[1])
    expect(buf[3]).not.toEqual(original[3])
    // ...unselected untouched
    expect(buf[0]).toEqual(original[0])
    expect(buf[2]).toEqual(original[2])

    restoreTint(buf, map, store)
    expect(buf).toEqual(original)
    expect(store.size).toBe(0)
  })

  /**
   * Regression: an undo snapshot must NEVER capture tinted colors. A filter
   * (cleanOpacity/cropBbox/filterBy*) snapshots the buffer while a selection is
   * live and tinted. If it sliced the tinted bytes, a later deselect would empty
   * the store and a subsequent undo would write the frozen highlight back with
   * nothing left to un-tint — permanent corruption. pushUndoSnapshot fixes this
   * by restoring true colors BEFORE the slice, then re-tinting. This models that
   * seam over the simulated buffer/IdMap the same way SceneManager drives it.
   */
  it('undo snapshot taken mid-filter holds ORIGINALS, and undo→deselect recovers them', () => {
    // Mirror of pushUndoSnapshot: untint if tinted, slice, then re-tint.
    function snapshotUndo(buf: Buffer, map: IdMap, store: TintStore, selection: Set<number>): Buffer {
      const wasTinted = store.size > 0
      if (wasTinted) restoreTint(buf, map, store)
      const snap = buf.map((c) => [...c] as RGB) // slice the packed buffer
      if (wasTinted && selection.size > 0) applyTint(buf, map, selection, store)
      return snap
    }

    const original: Buffer = [
      [0.10, 0.20, 0.30],
      [0.40, 0.50, 0.60],
      [0.70, 0.10, 0.90],
      [0.05, 0.05, 0.05],
    ]
    const buf: Buffer = original.map((c) => [...c] as RGB)
    const map = new IdMap(4)
    const store = new TintStore()
    const selection = new Set([1, 3])

    // Operator selects → splats get tinted.
    applyTint(buf, map, selection, store)
    expect(buf[1]).not.toEqual(original[1])
    expect(buf[3]).not.toEqual(original[3])

    // A filter runs WHILE the selection is live and tinted → takes an undo snapshot.
    const snap = snapshotUndo(buf, map, store, selection)

    // The snapshot bytes are the TRUE colors, not the highlight.
    expect(snap).toEqual(original)
    // ...and the live buffer is still visibly tinted (highlight didn't vanish).
    expect(buf[1]).not.toEqual(original[1])
    expect(buf[3]).not.toEqual(original[3])
    expect(store.size).toBe(2)

    // Later: operator deselects (store empties), then undoes the filter.
    restoreTint(buf, map, store) // deselect
    expect(store.size).toBe(0)
    buf.forEach((_, i) => { buf[i] = [...snap[i]] as RGB }) // undo() writes the snapshot back

    // Nothing is tinted anymore: colors are the pristine originals, no corruption.
    expect(buf).toEqual(original)
  })

  it('restore keyed by original ID survives a compaction between apply and restore', () => {
    const original: Buffer = [
      [0.10, 0.20, 0.30], // id 0
      [0.40, 0.50, 0.60], // id 1  (selected/tinted)
      [0.70, 0.10, 0.90], // id 2
      [0.05, 0.05, 0.05], // id 3  (selected/tinted)
    ]
    const buf: Buffer = original.map((c) => [...c] as RGB)
    const map = new IdMap(4)
    const store = new TintStore()
    const tintColor1 = tintedColor(original[1])
    const tintColor3 = tintedColor(original[3])

    applyTint(buf, map, new Set([1, 3]), store)

    // Compact away original id 0: survivors shift left, carrying their colors.
    // Packed order becomes ids [1, 2, 3] at indices [0, 1, 2].
    const compacted: Buffer = [buf[1], buf[2], buf[3]]
    let w = 0
    for (let i = 0; i < 4; i++) {
      if (map.idAt(i) === 0) continue
      map.retain(w, i)
      w++
    }
    map.setLive(3)

    // Tinted colors rode the shift intact.
    expect(compacted[0]).toEqual(tintColor1)
    expect(compacted[2]).toEqual(tintColor3)

    // Restore finds ids 1 and 3 at their NEW indices and recovers exactly.
    restoreTint(compacted, map, store)
    expect(compacted[0]).toEqual(original[1])
    expect(compacted[1]).toEqual(original[2])
    expect(compacted[2]).toEqual(original[3])
  })
})
