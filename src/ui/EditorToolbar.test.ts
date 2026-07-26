import { describe, it, expect } from 'vitest'
import { TOOLS, ACTION_DESCRIPTIONS } from './EditorToolbar.tsx'

describe('tool rail descriptions', () => {
  it('every tool carries a non-empty description', () => {
    expect(TOOLS.length).toBeGreaterThan(0)
    for (const t of TOOLS) {
      expect(t.description, `${t.tool} has no description`).toBeTruthy()
      expect(t.description.length).toBeGreaterThan(10)
    }
  })

  it('descriptions are plain sentences, not repeats of the title', () => {
    for (const t of TOOLS) {
      expect(t.description).not.toBe(t.title)
    }
  })

  it('every action button has a description', () => {
    for (const key of ['delete', 'keep', 'invert', 'clear', 'undo', 'redo', 'erase'] as const) {
      expect(ACTION_DESCRIPTIONS[key], `${key} missing`).toBeTruthy()
    }
  })
})
