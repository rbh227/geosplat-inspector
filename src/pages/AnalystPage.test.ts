import { describe, it, expect } from 'vitest'
import { analystStatus } from './analystStatus'

describe('analystStatus', () => {
  it('asks for a scene when the URL carries none', () => {
    expect(analystStatus(null, false)).toBe('no-scene')
  })

  it('reports a missing scene when the backend no longer holds it', () => {
    expect(analystStatus('abc', true)).toBe('scene-gone')
  })

  it('is ready when a scene id resolved', () => {
    expect(analystStatus('abc', false)).toBe('ready')
  })

  it('prefers no-scene over gone when there is no id at all', () => {
    expect(analystStatus(null, true)).toBe('no-scene')
  })
})
