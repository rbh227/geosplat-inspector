import { describe, it, expect } from 'vitest'
import { classifyAction, completeContent, sceneChanged } from './trace'

describe('classifyAction', () => {
  it('maps camera tools', () => {
    for (const n of ['look_at', 'set_view', 'orbit', 'dolly', 'scan_pause', 'frame_object', 'reset_view']) {
      expect(classifyAction(n)).toBe('camera_move')
    }
  })
  it('maps capture tools', () => {
    expect(classifyAction('capture_frame')).toBe('capture')
    expect(classifyAction('capture_orbit')).toBe('capture')
  })
  it('maps answer', () => {
    expect(classifyAction('answer')).toBe('answer')
  })
  it('defaults backend/edit tools to cleanup', () => {
    expect(classifyAction('remove_outliers')).toBe('cleanup')
    expect(classifyAction('crop_bbox')).toBe('cleanup')
    expect(classifyAction('totally_unknown')).toBe('cleanup')
  })
})

describe('completeContent', () => {
  it('error wins over answer', () => {
    expect(completeContent({ error: 'boom', answer: 'ignored' })).toBe('Error: boom')
  })
  it('uses answer when no error', () => {
    expect(completeContent({ answer: 'scene cleaned' })).toBe('scene cleaned')
  })
  it('falls back to Done', () => {
    expect(completeContent({})).toBe('Done.')
    expect(completeContent(undefined)).toBe('Done.')
  })
  it('reports a step-limit ending instead of a bare Done', () => {
    expect(completeContent({ status: 'max_steps', answer: null, error: null }))
      .toBe('Run ended: step limit reached before finishing.')
  })
  it('reports an operator stop', () => {
    expect(completeContent({ status: 'interrupted', answer: null, error: null }))
      .toBe('Stopped by the operator.')
  })
})

describe('sceneChanged (completion-gated reload)', () => {
  it('is true only when the payload explicitly records a backend edit', () => {
    expect(sceneChanged({ scene_changed: true })).toBe(true)
    expect(sceneChanged({ scene_changed: false })).toBe(false)
    expect(sceneChanged({})).toBe(false)        // absent field: never reload-yank
    expect(sceneChanged(undefined)).toBe(false)
  })
})
