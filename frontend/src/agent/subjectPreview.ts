/** Subject lock-on preview state (v0.8). The controller ships nested
 *  keep-levels ONCE; the card's slider re-tints locally with zero round trips
 *  (the run is blocked on the parked proposal, so no dispatch could serve it). */
import type { RendererBridge } from './types.ts'

interface SubjectState { cumulative: number[][]; counts: number[]; level: number }
let state: SubjectState | null = null

export function setSubject(
  bridge: RendererBridge,
  args: { baseIds: number[]; deltas: number[][]; counts: number[]; level: number },
): number {
  const cumulative: number[][] = [args.baseIds]
  for (const d of args.deltas) cumulative.push([...cumulative[cumulative.length - 1], ...d])
  state = { cumulative, counts: args.counts, level: 0 }
  return applyLevel(bridge, args.level)
}

export function applyLevel(bridge: RendererBridge, level: number): number {
  if (!state) return 0
  state.level = Math.max(0, Math.min(state.cumulative.length - 1, level))
  bridge.clearSelection()
  return bridge.updateSelection(state.cumulative[state.level], 'add')
}

export function getState(): { counts: number[]; level: number } | null {
  return state ? { counts: state.counts, level: state.level } : null
}

export function clear(bridge: RendererBridge): void {
  state = null
  bridge.clearSelection()
}
