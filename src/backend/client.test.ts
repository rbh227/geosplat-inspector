import { describe, it, expect, vi, afterEach } from 'vitest'
import { scenePlyUrl, sceneWsUrl, isBackendLoadable, getMetrics } from './client'

describe('isBackendLoadable', () => {
  it('accepts .ply (case-insensitive)', () => {
    expect(isBackendLoadable('scene.ply')).toBe(true)
    expect(isBackendLoadable('SCENE.PLY')).toBe(true)
  })
  it('rejects non-.ply formats and extensionless names', () => {
    expect(isBackendLoadable('bonsai.splat')).toBe(false)
    expect(isBackendLoadable('a.spz')).toBe(false)
    expect(isBackendLoadable('a.ksplat')).toBe(false)
    expect(isBackendLoadable('noext')).toBe(false)
  })
})

describe('scenePlyUrl', () => {
  it('is a same-origin relative path by default', () => {
    expect(scenePlyUrl('abc123')).toBe('/scene/abc123.ply')
  })
})

describe('sceneWsUrl', () => {
  it('derives a ws URL from the page origin', () => {
    expect(sceneWsUrl('abc123')).toBe(`ws://${window.location.host}/ws/abc123`)
  })
})

describe('getMetrics', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('requests the scene-scoped metrics endpoint and returns parsed JSON', async () => {
    const payload = { gaussianCount: 1200 }
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => payload }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await getMetrics('abc 123')
    expect(fetchMock).toHaveBeenCalledWith('/metrics?scene_id=abc%20123')
    expect(result).toEqual(payload)
  })

  it('throws with status and detail on a non-OK response', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: false,
      status: 404,
      text: async () => 'no such scene',
    })))
    await expect(getMetrics('missing')).rejects.toThrow(/404.*no such scene/)
  })
})
