import { describe, it, expect, beforeEach } from 'vitest'
import {
  savePersistedScene, loadPersistedScene, clearPersistedScene, updatePersistedCamera,
} from './persistence'

const REC = {
  sceneId: 'abc123',
  fileName: 'iona_park.ply',
  baseline: 2_000_000,
  camera: null,
}

describe('scene persistence', () => {
  beforeEach(() => { sessionStorage.clear() })

  it('round-trips a record', () => {
    savePersistedScene(REC)
    expect(loadPersistedScene()).toEqual(REC)
  })

  it('returns null when nothing was saved', () => {
    expect(loadPersistedScene()).toBeNull()
  })

  it('clears', () => {
    savePersistedScene(REC)
    clearPersistedScene()
    expect(loadPersistedScene()).toBeNull()
  })

  it('treats corrupt JSON as absent rather than throwing', () => {
    sessionStorage.setItem('splatagent.scene.v1', '{not json')
    expect(loadPersistedScene()).toBeNull()
  })

  it('rejects a record with no scene id', () => {
    sessionStorage.setItem('splatagent.scene.v1', JSON.stringify({ fileName: 'x.ply' }))
    expect(loadPersistedScene()).toBeNull()
  })

  it('merges a camera pose into the existing record', () => {
    savePersistedScene(REC)
    const camera = { position: [1, 2, 3] as [number, number, number], target: [0, 0, 0] as [number, number, number] }
    updatePersistedCamera(camera)
    expect(loadPersistedScene()).toEqual({ ...REC, camera })
  })

  it('does not resurrect a cleared record when a camera update arrives late', () => {
    // pagehide can fire after the record was dropped (view-only load, failed
    // upload). Writing a camera-only record would leave a scene id-less entry
    // that the restore path would then have to defend against.
    clearPersistedScene()
    updatePersistedCamera({ position: [1, 2, 3], target: [0, 0, 0] })
    expect(loadPersistedScene()).toBeNull()
  })
})
