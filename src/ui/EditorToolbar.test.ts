import { describe, it, expect } from 'vitest'
import { TOOLS, ACTION_DESCRIPTIONS, ACTION_TITLES, describedTooltip, actionTooltip } from './EditorToolbar.tsx'

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

  it('every action button has a title to pair with its description', () => {
    for (const key of Object.keys(ACTION_DESCRIPTIONS) as Array<keyof typeof ACTION_DESCRIPTIONS>) {
      expect(ACTION_TITLES[key], `${key} has no title`).toBeTruthy()
    }
  })
})

describe('describedTooltip (collapsed-rail tooltip builder used by every rail row)', () => {
  it('joins title and description with an em dash when a description is present', () => {
    expect(describedTooltip('Brush select', 'Paint over splats.')).toBe('Brush select — Paint over splats.')
  })

  it('falls back to the bare title when there is no description', () => {
    expect(describedTooltip('Pointer / navigate')).toBe('Pointer / navigate')
  })
})

describe('actionTooltip (the exact helper EditorToolbar calls to build each action row\'s collapsed title)', () => {
  it('produces "title — description" for every action, using the same ACTION_TITLES/ACTION_DESCRIPTIONS the component renders', () => {
    for (const key of Object.keys(ACTION_DESCRIPTIONS) as Array<keyof typeof ACTION_DESCRIPTIONS>) {
      const tooltip = actionTooltip(key)
      expect(tooltip).toBe(`${ACTION_TITLES[key]} — ${ACTION_DESCRIPTIONS[key]}`)
      // Regression guard for the "ACTION_DESCRIPTIONS is dead data" finding: the
      // description text must actually reach the tooltip the rail shows, not just
      // exist in the constant.
      expect(tooltip).toContain(ACTION_DESCRIPTIONS[key])
    }
  })

  it('matches the erase row\'s OFF-state tooltip built by the component', () => {
    // EditorToolbar renders the erase row's collapsed title as
    // `${ACTION_TITLES.erase}: ON` when active, or ACTION_TITLES.erase otherwise,
    // paired with ACTION_DESCRIPTIONS.erase via describedTooltip — same as here.
    expect(actionTooltip('erase')).toBe(describedTooltip(ACTION_TITLES.erase, ACTION_DESCRIPTIONS.erase))
  })
})
