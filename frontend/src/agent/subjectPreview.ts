/** Subject lock-on preview state (v0.8). The controller ships nested
 *  keep-levels ONCE; the card's slider re-tints locally with zero round trips
 *  (the run is blocked on the parked proposal, so no dispatch could serve it).
 *
 *  COMPLEMENT form (live-found at 2M splats): the keep-set is ~N ids — 17MB
 *  of JSON — while the excluded set is the small one. The controller ships
 *  `outsideIds` (excluded even at the LOOSEST level) plus per-level deltas;
 *  each keep-tint is derived locally as invert-all-then-remove-excluded. */
import type { RendererBridge } from './types.ts'

interface SubjectState {
  /** excluded[k] = ids NOT kept at level k (suffix-cumulative:
   *  outsideIds ∪ deltas[k] ∪ … ∪ deltas[last]). */
  excluded: number[][]
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
  bridge.invertSelection()  // select every live splat…
  return bridge.updateSelection(state.excluded[state.level], 'remove')  // …minus the excluded
}

export function getState(): { counts: number[]; level: number } | null {
  return state ? { counts: state.counts, level: state.level } : null
}

export function clear(bridge: RendererBridge): void {
  state = null
  bridge.clearSelection()
}
