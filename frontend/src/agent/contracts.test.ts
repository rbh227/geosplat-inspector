import { describe, expect, it } from 'vitest'
import { BACKEND_TOOLS, FRONTEND_TOOLS, PROPOSAL_DECISION_FIELDS } from '../contracts.ts'
import type { WSCommandType } from '../contracts.ts'

// Mirror-drift guard: these counts and names must match the Python registry
// (backend/contracts/tools.py, asserted in backend/contracts/tests/test_tools.py).
describe('contracts v0.2 mirror', () => {
  it('matches the Python registry counts (28 frontend / 18 backend)', () => {
    // v0.3 added `turn`, v0.4 added `reframe`, v0.5 added the four proposal /
    // good-cube tools (all frontend): 22 -> 24 -> 28.
    expect(FRONTEND_TOOLS.length).toBe(28)
    expect(BACKEND_TOOLS.length).toBe(18)
  })

  it('carries the v0.3 turn and v0.4 reframe tools', () => {
    const fe = new Set<string>(FRONTEND_TOOLS)
    expect(fe.has('turn')).toBe(true)
    expect(fe.has('reframe')).toBe(true)
  })

  it('carries the v0.5 proposal / good-cube tools', () => {
    const fe = new Set<string>(FRONTEND_TOOLS)
    for (const name of [
      'get_core_bounds', 'show_box_preview', 'adjust_box_preview', 'propose_decision',
    ]) expect(fe.has(name), name).toBe(true)
  })

  it('carries the v0.2 rotation_input and v0.5 proposal WS command types', () => {
    // Compile-time drift guard (tsc --noEmit): both must be members of the
    // WSCommandType union. rotation_input was in ws.py + ws-client.ts but
    // missing from this union; proposal is the new blocking-reply command.
    const cmdTypes: WSCommandType[] = ['rotation_input', 'proposal']
    expect(cmdTypes).toContain('proposal')
    expect(cmdTypes).toContain('rotation_input')
  })

  it('carries the v0.2 selection, movement, and selection-edit tools', () => {
    const fe = new Set<string>(FRONTEND_TOOLS)
    for (const name of [
      'select_by_brush', 'select_by_lasso', 'select_by_polygon',
      'select_by_sphere', 'select_by_box',
      'invert_selection', 'clear_selection', 'get_selection_state',
      'move_camera',
    ]) expect(fe.has(name), name).toBe(true)

    const be = new Set<string>(BACKEND_TOOLS)
    for (const name of ['delete_selection', 'keep_selection']) expect(be.has(name), name).toBe(true)
  })

  it('has no duplicate names across the registry', () => {
    const all = [...FRONTEND_TOOLS, ...BACKEND_TOOLS]
    expect(new Set(all).size).toBe(all.length)
  })
})

describe('v0.6 proposal decision', () => {
  it('carries the operator-edited box alongside the verdict', () => {
    expect(PROPOSAL_DECISION_FIELDS).toContain('verdict')
    expect(PROPOSAL_DECISION_FIELDS).toContain('feedback')
    expect(PROPOSAL_DECISION_FIELDS).toContain('box')
  })
})
