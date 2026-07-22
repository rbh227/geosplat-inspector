/**
 * Persistent selection tint (Task 6, docs/plans selection-visibility).
 *
 * A selection is otherwise invisible in the viewport — only a count in the top
 * bar — so the operator can't see what an agent (or they) are about to delete.
 * This module owns the two pure pieces of the "tint the selected splats" job:
 *
 *   1. the highlight color math (lerp toward a warm color), and
 *   2. the store/restore bookkeeping that lets the tint be undone EXACTLY.
 *
 * Both are free of THREE / Spark types so the store-then-restore contract is
 * unit-testable headless (see selectionTint.test.ts), mirroring how flyController
 * / idMap keep their logic pure. SceneManager does the actual packed-buffer
 * reads/writes with these helpers.
 */

export type RGB = [number, number, number]

/** Warm highlight the selection is lerped toward. */
export const HIGHLIGHT_RGB: RGB = [1.0, 0.75, 0.2]

/** How far to lerp a splat's color toward HIGHLIGHT_RGB (0 = untouched, 1 = pure highlight). */
export const TINT_STRENGTH = 0.6

/**
 * Blend a splat's original color `strength` of the way toward `target`.
 * Pure; component-wise linear interpolation.
 */
export function tintedColor(
  orig: readonly [number, number, number],
  strength: number = TINT_STRENGTH,
  target: readonly [number, number, number] = HIGHLIGHT_RGB,
): RGB {
  return [
    orig[0] + (target[0] - orig[0]) * strength,
    orig[1] + (target[1] - orig[1]) * strength,
    orig[2] + (target[2] - orig[2]) * strength,
  ]
}

/**
 * Remembers each tinted splat's TRUE color the first time it is tinted so it
 * can be restored byte-for-byte on deselect. Keyed by ORIGINAL splat ID (stable
 * across compaction), not packed index — so a restore finds the right splat even
 * after an unrelated edit reshuffles the packed buffer.
 */
export class TintStore {
  private originals = new Map<number, RGB>()

  get size(): number {
    return this.originals.size
  }

  has(id: number): boolean {
    return this.originals.has(id)
  }

  /**
   * Record the untinted color for `id` — FIRST write only. A second call (the
   * splat is already tinted) is ignored, so a re-tint never captures an
   * already-tinted value as if it were the original.
   */
  remember(id: number, rgb: RGB): void {
    if (!this.originals.has(id)) this.originals.set(id, rgb)
  }

  original(id: number): RGB | undefined {
    return this.originals.get(id)
  }

  clear(): void {
    this.originals.clear()
  }
}
