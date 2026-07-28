import { describe, it, expect, vi, beforeEach } from 'vitest'

// Only getAliveIds is stubbed; everything else in the client stays real so the
// module graph loads exactly as it does in the app.
vi.mock('../backend/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../backend/client')>()
  return { ...actual, getAliveIds: vi.fn() }
})

import { getAliveIds } from '../backend/client'
import { probeBackendScene } from './useSession'

describe('probeBackendScene', () => {
  beforeEach(() => { vi.mocked(getAliveIds).mockReset() })

  it('reports present when the backend still holds the scene', async () => {
    const ids = Uint32Array.from([1, 2, 3])
    vi.mocked(getAliveIds).mockResolvedValue(ids)
    expect(await probeBackendScene('abc')).toEqual({ present: true, ids })
  })

  it('reports absent when the scene 404s', async () => {
    // Scenes are in-memory only: a restarted backend loses them while a
    // browser tab still holds the id. That must surface as a state, not a throw.
    vi.mocked(getAliveIds).mockImplementation(async () => {
      throw new Error('ids fetch failed (404): not found')
    })
    expect(await probeBackendScene('abc')).toEqual({ present: false, ids: null })
  })
})
