import { describe, it, expect } from 'vitest'
import { analystStatus } from './analystStatus'

describe('analystStatus', () => {
  it('asks for a scene when the URL carries none', () => {
    expect(analystStatus(null, false, false)).toBe('no-scene')
  })

  it('is loading while the URL scene is still being fetched', () => {
    expect(analystStatus('abc', false, false)).toBe('loading')
  })

  it('reports a missing scene when the backend no longer holds it', () => {
    expect(analystStatus('abc', true, false)).toBe('scene-gone')
  })

  it('is ready once a scene is actually loaded', () => {
    expect(analystStatus('abc', false, true)).toBe('ready')
  })

  it('clears the scene-gone overlay when a replacement file is dropped', () => {
    // The dropped file loads without changing the URL id, so `gone` stays true.
    // Deriving from the URL alone stranded the overlay over a working scene.
    expect(analystStatus('abc', true, true)).toBe('ready')
  })

  it('clears the no-scene state when a file is dropped with no URL id', () => {
    expect(analystStatus(null, false, true)).toBe('ready')
  })
})
