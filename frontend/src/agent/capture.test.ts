import { describe, it, expect } from 'vitest'
import { captureSize, MAX_CAPTURE_EDGE } from './capture.ts'

/**
 * Vision models bill by patch, so capture pixel dimensions are a cost and a
 * stability concern, not a cosmetic one. An unscaled Retina viewport OOM'd the
 * vLLM vision tower mid-run and killed the server; see capture.ts.
 */
describe('captureSize', () => {
  it('leaves a small canvas untouched', () => {
    expect(captureSize(800, 600)).toEqual({ width: 800, height: 600 })
  })

  it('never upscales a canvas that is exactly at the cap', () => {
    expect(captureSize(MAX_CAPTURE_EDGE, 512)).toEqual({
      width: MAX_CAPTURE_EDGE,
      height: 512,
    })
  })

  it('caps the long edge of a landscape viewport, preserving aspect ratio', () => {
    const { width, height } = captureSize(2044, 1316)
    expect(width).toBe(MAX_CAPTURE_EDGE)
    expect(height).toBe(Math.round(1316 * (MAX_CAPTURE_EDGE / 2044)))
    expect(width / height).toBeCloseTo(2044 / 1316, 2)
  })

  it('caps the long edge of a portrait viewport', () => {
    const { width, height } = captureSize(1000, 2500)
    expect(height).toBe(MAX_CAPTURE_EDGE)
    expect(width).toBe(Math.round(1000 * (MAX_CAPTURE_EDGE / 2500)))
  })

  it('cuts the Retina viewport that crashed the server well under 1000 vision tokens', () => {
    // Qwen3-VL: 14px patches, 2x2 merge -> tokens = (w/14)*(h/14)/4
    const tokens = (w: number, h: number) =>
      Math.floor(w / 14) * Math.floor(h / 14) / 4

    expect(tokens(2044, 1316)).toBeGreaterThan(3000) // the frame that OOM'd
    const { width, height } = captureSize(2044, 1316)
    expect(tokens(width, height)).toBeLessThan(1000)
  })

  it('honours an explicit cap', () => {
    expect(captureSize(4000, 2000, 500)).toEqual({ width: 500, height: 250 })
  })

  it('degrades safely on a zero-sized canvas', () => {
    expect(captureSize(0, 0)).toEqual({ width: 1, height: 1 })
  })
})
