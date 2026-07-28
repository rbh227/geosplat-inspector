import { describe, it, expect } from 'vitest'
import { parseRoute, analystHref } from './routing'

describe('parseRoute', () => {
  it('defaults to the editor for an empty hash', () => {
    expect(parseRoute('')).toEqual({ page: 'editor', sceneId: null })
  })

  it('defaults to the editor for an unknown hash', () => {
    expect(parseRoute('#/nonsense')).toEqual({ page: 'editor', sceneId: null })
  })

  it('routes #/analyze with a scene id', () => {
    expect(parseRoute('#/analyze?scene=abc123')).toEqual({
      page: 'analyst', sceneId: 'abc123',
    })
  })

  it('routes #/analyze with no scene id', () => {
    expect(parseRoute('#/analyze')).toEqual({ page: 'analyst', sceneId: null })
  })

  it('treats an empty scene param as absent', () => {
    expect(parseRoute('#/analyze?scene=')).toEqual({ page: 'analyst', sceneId: null })
  })
})

describe('analystHref', () => {
  it('builds a hash href', () => {
    expect(analystHref('abc123')).toBe('#/analyze?scene=abc123')
  })

  it('encodes ids that need it', () => {
    expect(analystHref('a b')).toBe('#/analyze?scene=a%20b')
  })
})
