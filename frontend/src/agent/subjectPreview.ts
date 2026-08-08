/** Subject lock-on preview state (v0.8). The controller ships nested
 *  keep-levels ONCE; the card's slider re-tints locally with zero round trips
 *  (the run is blocked on the parked proposal, so no dispatch could serve it).
 *
 *  The tint marks the DELETE-set (live-found at 2M splats, twice over): the
 *  keep-set is ~N splats, so tinting it wedges the main thread for minutes in
 *  the per-splat recolor path AND washes the whole scene gold; the excluded
 *  set is small, cheap to tint, and is what the operator actually needs to
 *  review before approving. `excluded[k]` = outsideIds ∪ deltas[k..]. */
import type { RendererBridge } from './types.ts'

interface SubjectState {
  /** excluded[k] = ids NOT kept at level k (suffix-cumulative). */
  excluded: number[][]
  /** KEEP counts per level (for the slider label). */
  counts: number[]
  level: number
}
let state: SubjectState | null = null

export function setSubject(
  bridge: RendererBridge,
  args: { outsideIds: number[]; deltas: number[][]; counts: number[]; level: number },
): number {
  const n = args.deltas.length + 1
  const excluded: number[][] = new Array(n)
  excluded[n - 1] = args.outsideIds
  for (let k = n - 2; k >= 0; k--) excluded[k] = [...excluded[k + 1], ...args.deltas[k]]
  state = { excluded, counts: args.counts, level: 0 }
  return applyLevel(bridge, args.level)
}

export function applyLevel(bridge: RendererBridge, level: number): number {
  if (!state) return 0
  state.level = Math.max(0, Math.min(state.excluded.length - 1, level))
  bridge.clearSelection()
  return bridge.updateSelection(state.excluded[state.level], 'add')
}

export function getState(): { counts: number[]; level: number } | null {
  return state ? { counts: state.counts, level: state.level } : null
}

export function clear(bridge: RendererBridge): void {
  state = null
  bridge.clearSelection()
}
