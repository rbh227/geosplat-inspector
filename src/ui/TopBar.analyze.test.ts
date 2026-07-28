/**
 * Render-mount, following the precedent set by EditorToolbar.test.ts: that one
 * exists because props were silently dropped inside a .map(), and a pure-logic
 * test would not have caught it.
 */
import { describe, it, expect, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import TopBar from './TopBar.tsx'
import { analystHref } from '../routing'

let root: Root | null = null
let host: HTMLDivElement | null = null

const BASE_PROPS = {
  stage: 'clean' as const,
  onStageChange: () => {},
  stageLocked: false,
  navigationMode: 'orbit' as const,
  onToggleNavMode: () => {},
  rightOpen: true,
  onToggleRight: () => {},
  settingsOpen: false,
  onToggleSettings: () => {},
  settingsAttention: false,
  onImport: () => {},
  onLoadDemo: () => {},
  onResetView: () => {},
  canExport: false,
  removedCount: 0,
  onExport: () => {},
}

function render(props: Record<string, unknown>) {
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  act(() => { root!.render(createElement(TopBar, { ...BASE_PROPS, ...props } as never)) })
  return host
}

afterEach(() => {
  act(() => root?.unmount())
  host?.remove()
  root = null
  host = null
})

function analyzeButton(el: HTMLElement): HTMLButtonElement | undefined {
  return Array.from(el.querySelectorAll('button'))
    .find((b) => b.textContent?.includes('Analyze scene')) as HTMLButtonElement | undefined
}

describe('Analyze scene handoff', () => {
  it('renders the action when a handler is supplied', () => {
    const el = render({ onAnalyze: () => {}, canAnalyze: true })
    expect(analyzeButton(el)).toBeTruthy()
  })

  it('stays hidden when no handler is supplied', () => {
    const el = render({})
    expect(analyzeButton(el)).toBeUndefined()
  })

  it('is disabled until a scene is registered with the backend', () => {
    const el = render({ onAnalyze: () => {}, canAnalyze: false })
    expect(analyzeButton(el)?.disabled).toBe(true)
  })

  it('fires the handler on click once enabled', () => {
    let fired = 0
    const el = render({ onAnalyze: () => { fired += 1 }, canAnalyze: true })
    act(() => { analyzeButton(el)?.click() })
    expect(fired).toBe(1)
  })

  it('targets the analyst route for the current scene', () => {
    expect(analystHref('scene-42')).toBe('#/analyze?scene=scene-42')
  })
})
