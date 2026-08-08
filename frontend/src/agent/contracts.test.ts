import { describe, expect, it } from 'vitest'
import { BACKEND_TOOLS, CLUSTER_ROW_FIELDS, FRONTEND_TOOLS, PROPOSAL_DECISION_FIELDS, PROPOSAL_KINDS } from '../contracts.ts'
import type { WSCommandType } from '../contracts.ts'

// Mirror-drift guard: these counts and names must match the Python registry
// (backend/contracts/tools.py, asserted in backend/contracts/tests/test_tools.py).
describe('contracts v0.2 mirror', () => {
  it('matches the Python registry counts (28 frontend / 16 backend)', () => {
    // v0.3 `turn`, v0.4 `reframe`, v0.5 proposals, v0.6 `survey_capture`,
    // v0.7 `select_by_ids`, v0.8 `show_subject_preview`; v0.8.2 DELETES the
    // crop-box flow (3 frontend + 2 backend): 31 -> 28 frontend, 18 -> 16.
    expect(FRONTEND_TOOLS.length).toBe(28)
    expect(BACKEND_TOOLS.length).toBe(16)
  })

  it('carries the v0.3 turn and v0.4 reframe tools', () => {
    const fe = new Set<string>(FRONTEND_TOOLS)
    expect(fe.has('turn')).toBe(true)
    expect(fe.has('reframe')).toBe(true)
  })

  it('carries the v0.6 app-owned survey tool', () => {
    expect(new Set<string>(FRONTEND_TOOLS).has('survey_capture')).toBe(true)
  })

  it('carries propose_decision and none of the deleted crop-box tools (v0.8.2)', () => {
    const fe = new Set<string>(FRONTEND_TOOLS)
    expect(fe.has('propose_decision')).toBe(true)
    for (const name of ['get_core_bounds', 'show_box_preview', 'adjust_box_preview'])
      expect(fe.has(name), name).toBe(false)
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

describe('v0.7 judgment-tour additions', () => {
  it('carries select_by_ids, the delete_clusters kind, and the cluster row fields', () => {
    expect(new Set<string>(FRONTEND_TOOLS).has('select_by_ids')).toBe(true)
    expect(PROPOSAL_KINDS).toContain('delete_clusters')
    expect(CLUSTER_ROW_FIELDS).toEqual(['label', 'count', 'verdict', 'reason', 'provenance'])
  })
})

describe('v0.8 subject-first cleanup additions', () => {
  it('carries show_subject_preview, the keep_only_subject kind, and the level field', () => {
    expect(new Set<string>(FRONTEND_TOOLS).has('show_subject_preview')).toBe(true)
    expect(PROPOSAL_KINDS).toContain('keep_only_subject')
    expect(PROPOSAL_DECISION_FIELDS).toContain('level')
  })
})

describe('v0.6 proposal decision', () => {
  it('carries verdict/feedback/level — box was deleted with the crop flow (v0.8.2)', () => {
    expect(PROPOSAL_DECISION_FIELDS).toContain('verdict')
    expect(PROPOSAL_DECISION_FIELDS).toContain('feedback')
    expect(PROPOSAL_DECISION_FIELDS).toContain('level')
    expect(PROPOSAL_DECISION_FIELDS as readonly string[]).not.toContain('box')
  })
})
