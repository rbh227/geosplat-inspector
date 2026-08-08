import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as THREE from 'three'

// capturePNG needs a real WebGL canvas — mock the capture module wholesale.
vi.mock('./capture.ts', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./capture.ts')>()
  return {
    ...mod,
    capturePNG: vi.fn(async () => 'data:image/png;base64,QUJD'), // "ABC"
  }
})
// animateTo drives a rAF tween against the live bridge — not available in
// jsdom. The survey only needs it to have moved the camera; a no-op is fine.
vi.mock('./camera.ts', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./camera.ts')>()
  return {
    ...mod,
    animateTo: vi.fn(async () => {}),
    sleep: vi.fn(async () => {}),
  }
})

import { capturePNG } from './capture.ts'
import { animateTo } from './camera.ts'
import { FrontendExecutors } from './executors.ts'

function makeBridge(revision = 7) {
  const camera = new THREE.PerspectiveCamera(60, 16 / 9)
  camera.position.set(0, 10, 20)
  return {
    getSceneRevision: () => revision,
    getSceneCore: () => ({ center: [0, 0, 0] as [number, number, number], radius: 5 }),
    getCamera: () => camera,
    getCameraPose: () => ({
      position: camera.position.clone(),
      target: new THREE.Vector3(0, 0, 0),
    }),
    setCameraPose: vi.fn(),
    renderOnce: vi.fn(),
    getRenderer: () => ({ domElement: { clientWidth: 100, clientHeight: 100 } }) as never,
  }
}

const overlay = { pushTrailPoint: vi.fn() }

describe('survey_capture', () => {
  beforeEach(() => vi.clearAllMocks())

  it('short-circuits when the revision is unchanged', async () => {
    const ex = new FrontendExecutors(makeBridge() as never, overlay as never)
    const result = await ex.survey_capture({ if_revision_not: 7 })
    expect(result).toMatchObject({ unchanged: true, revision: 7 })
    expect(capturePNG).not.toHaveBeenCalled()
  })

  it('captures operator view + three survey poses with labels', async () => {
    const ex = new FrontendExecutors(makeBridge() as never, overlay as never)
    const result = (await ex.survey_capture({})) as {
      frames_base64: string[]
      labels: string[]
      revision: number
    }
    expect(result.frames_base64).toHaveLength(4)
    expect(result.labels).toEqual([
      "operator's view",
      'top-down',
      'oblique view from the north-east',
      'oblique view from the south-west',
    ])
    expect(result.revision).toBe(7)
    expect(result.frames_base64.every((f) => f === 'QUJD')).toBe(true)
    expect(animateTo).toHaveBeenCalledTimes(3) // one flight per survey pose
  })

  it('returns only the operator view when there is no scene core', async () => {
    const bridge = { ...makeBridge(), getSceneCore: () => null }
    const ex = new FrontendExecutors(bridge as never, overlay as never)
    const result = (await ex.survey_capture({})) as { frames_base64: string[]; labels: string[] }
    expect(result.frames_base64).toHaveLength(1)
    expect(result.labels).toEqual(["operator's view"])
  })

  it('skips a hung pose instead of hanging the whole survey (watchdog)', async () => {
    vi.useFakeTimers()
    try {
      // first survey pose's flight never settles — the exact live failure
      ;(animateTo as unknown as ReturnType<typeof vi.fn>)
        .mockImplementationOnce(() => new Promise<void>(() => {}))
      const ex = new FrontendExecutors(makeBridge() as never, overlay as never)
      const pending = ex.survey_capture({})
      await vi.advanceTimersByTimeAsync(16000)    // trip the 15s pose watchdog
      const result = (await pending) as { frames_base64: string[]; labels: string[]; poses: unknown[] }
      // operator view + the two poses that worked; the hung one is absent
      expect(result.labels).toEqual([
        "operator's view",
        'oblique view from the north-east',
        'oblique view from the south-west',
      ])
      expect(result.frames_base64).toHaveLength(3)
      expect(result.poses).toHaveLength(3)        // arrays stay index-aligned
    } finally {
      vi.useRealTimers()
    }
  })

  it('capture_frame times out instead of dangling (single-capture watchdog)', async () => {
    vi.useFakeTimers()
    try {
      ;(capturePNG as unknown as ReturnType<typeof vi.fn>)
        .mockImplementationOnce(() => new Promise(() => {}))   // toBlob never calls back
      const ex = new FrontendExecutors(makeBridge() as never, overlay as never)
      const pending = ex.capture_frame()
      await vi.advanceTimersByTimeAsync(16000)
      expect(await pending).toMatchObject({ ok: false })
    } finally {
      vi.useRealTimers()
    }
  })
})
