import { describe, expect, it } from 'vitest'
import { BACKEND_TOOLS, FRONTEND_TOOLS } from '../contracts.ts'

// Mirror-drift guard: these counts and names must match the Python registry
// (backend/contracts/tools.py, asserted in backend/contracts/tests/test_tools.py).
describe('contracts v0.2 mirror', () => {
  it('matches the Python registry counts (23 frontend / 18 backend)', () => {
    // v0.3 added `turn` (frontend): 22 -> 23.
    expect(FRONTEND_TOOLS.length).toBe(23)
    expect(BACKEND_TOOLS.length).toBe(18)
  })

  it('carries the v0.3 turn tool', () => {
    expect(new Set<string>(FRONTEND_TOOLS).has('turn')).toBe(true)
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
