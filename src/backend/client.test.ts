import { describe, it, expect, vi, afterEach } from 'vitest'
import {
  scenePlyUrl, sceneWsUrl, isBackendLoadable, getMetrics,
  getProviders, getModelConfig, saveModelConfig, testModelConfig,
} from './client'

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

describe('getProviders', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('fetches the registry and returns the providers array', async () => {
    const providers = [{ id: 'gemini', label: 'Google Gemini' }]
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ providers }) }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await getProviders()
    expect(fetchMock).toHaveBeenCalledWith('/config/providers')
    expect(result).toEqual(providers)
  })

  it('degrades to an empty array on a non-OK response', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 500 })))
    expect(await getProviders()).toEqual([])
  })
})

describe('getModelConfig', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('fetches the current selection', async () => {
    const config = { preset: 'gemini', provider: 'gemini', model: 'gemini-2.5-flash', base_url: null, key_set: true, key_source: 'env', source: 'env' }
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => config }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await getModelConfig()
    expect(fetchMock).toHaveBeenCalledWith('/config/model')
    expect(result).toEqual(config)
  })

  it('degrades to null on a non-OK response (e.g. backend offline)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 500 })))
    expect(await getModelConfig()).toBeNull()
  })
})

describe('saveModelConfig', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('POSTs the selection as JSON and returns the saved config', async () => {
    const saved = { preset: 'openai', provider: 'openai', model: 'gpt-4o-mini', base_url: null, key_set: true, key_source: 'ui', source: 'ui' }
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => saved }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await saveModelConfig({ preset: 'openai', api_key: 'sk-test' })
    expect(fetchMock).toHaveBeenCalledWith('/config/model', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ preset: 'openai', api_key: 'sk-test' }),
    })
    expect(result).toEqual(saved)
  })

  it('throws with status and detail on a non-OK response', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: false,
      status: 400,
      text: async () => 'unknown preset',
    })))
    await expect(saveModelConfig({ preset: 'bogus' })).rejects.toThrow(/400.*unknown preset/)
  })
})

describe('testModelConfig', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('POSTs and returns the ok/error result', async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ ok: true, model: 'gemini-2.5-flash' }) }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await testModelConfig({ preset: 'gemini', api_key: 'k' })
    expect(fetchMock).toHaveBeenCalledWith('/config/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ preset: 'gemini', api_key: 'k' }),
    })
    expect(result).toEqual({ ok: true, model: 'gemini-2.5-flash' })
  })

  it('returns an ok:false result (not a throw) on a non-OK response', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: false,
      status: 500,
      text: async () => 'boom',
    })))
    const result = await testModelConfig()
    expect(result.ok).toBe(false)
    expect(result.error).toMatch(/500/)
  })
})
