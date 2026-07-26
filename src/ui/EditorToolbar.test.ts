import { describe, it, expect, beforeAll, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import EditorToolbar, { TOOLS, ACTIONS, ACTION_DESCRIPTIONS, ACTION_TITLES, describedTooltip } from './EditorToolbar.tsx'

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

  it('erase mode has a title and description', () => {
    expect(ACTION_TITLES.erase, 'erase has no title').toBeTruthy()
    expect(ACTION_DESCRIPTIONS.erase, 'erase has no description').toBeTruthy()
  })
})

describe('ACTIONS (data-driven action rows — EditorToolbar maps over this array, so a row cannot exist without its description)', () => {
  it('covers exactly the six selection/history actions', () => {
    expect(ACTIONS.map((a) => a.key).sort()).toEqual(['clear', 'delete', 'invert', 'keep', 'redo', 'undo'])
  })

  it('every action row carries a non-empty description, distinct from its title', () => {
    for (const a of ACTIONS) {
      expect(a.description, `${a.key} has no description`).toBeTruthy()
      expect(a.description).not.toBe(a.title)
    }
  })

  it('title/description come from the shared ACTION_TITLES/ACTION_DESCRIPTIONS constants the rest of the app reads', () => {
    for (const a of ACTIONS) {
      expect(a.title).toBe(ACTION_TITLES[a.key])
      expect(a.description).toBe(ACTION_DESCRIPTIONS[a.key])
    }
  })

  it('Delete/Keep/Clear are disabled with no selection; Invert/Undo/Redo are not', () => {
    const byKey = Object.fromEntries(ACTIONS.map((a) => [a.key, a])) as Record<string, (typeof ACTIONS)[number]>

    for (const key of ['delete', 'keep', 'clear']) {
      expect(byKey[key].disabledWhen({ hasSelection: false }), `${key} should disable with no selection`).toBe(true)
      expect(byKey[key].disabledWhen({ hasSelection: true }), `${key} should enable with a selection`).toBe(false)
    }

    for (const key of ['invert', 'undo', 'redo']) {
      expect(byKey[key].disabledWhen({ hasSelection: false }), `${key} should not depend on selection`).toBe(false)
      expect(byKey[key].disabledWhen({ hasSelection: true }), `${key} should not depend on selection`).toBe(false)
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

describe('EditorToolbar rendered output (guards against `description={description}` being dropped from a .map() block)', () => {
  beforeAll(() => {
    // React 19 requires this before `act()` is used outside of a test-renderer-aware harness.
    ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  })

  let container: HTMLDivElement | null = null
  let root: Root | null = null

  afterEach(() => {
    if (root) {
      act(() => {
        root!.unmount()
      })
      root = null
    }
    if (container) {
      container.remove()
      container = null
    }
  })

  function mount() {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    const props = {
      activeTool: null,
      onToolChange: () => {},
      eraseMode: false,
      onEraseModeChange: () => {},
      selectionCount: 5,
      onDeleteSelection: () => {},
      onKeepSelection: () => {},
      onInvertSelection: () => {},
      onClearSelection: () => {},
      onUndo: () => {},
      onRedo: () => {},
    }
    act(() => {
      root!.render(createElement(EditorToolbar, props))
    })
    return container
  }

  function clickHelpToggle(el: HTMLElement) {
    const toggle = Array.from(el.querySelectorAll('button')).find(
      (b) => b.title === 'Show tool descriptions',
    )
    if (!toggle) throw new Error('help-toggle button not found')
    act(() => {
      toggle.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
  }

  it('does not render descriptions while showHelp is off (default)', () => {
    const el = mount()
    expect(el.textContent).not.toContain(TOOLS[0].description)
    expect(el.textContent).not.toContain(ACTION_DESCRIPTIONS.delete)
  })

  it('renders every TOOLS description and every ACTION_DESCRIPTIONS value once showHelp is toggled on', () => {
    const el = mount()
    clickHelpToggle(el)

    for (const t of TOOLS) {
      expect(el.textContent, `missing description for tool "${t.tool}"`).toContain(t.description)
    }
    for (const [key, description] of Object.entries(ACTION_DESCRIPTIONS)) {
      expect(el.textContent, `missing description for action "${key}"`).toContain(description)
    }
  })
})
