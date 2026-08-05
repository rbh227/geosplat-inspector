import { describe, it, expect } from 'vitest'
import { captureSize, drawGridOverlay, MAX_CAPTURE_EDGE } from './capture.ts'

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

/** jsdom has no real 2D context (needs node-canvas), so record the calls on a
 *  stub — these tests pin the CONVENTION: 4×4, labels A1..D4, columns A-D
 *  left→right, rows 1-4 top→bottom (must match backend clusters.cell_index). */
function stubCanvas(width: number, height: number) {
  const texts: Array<{ text: string; x: number; y: number }> = []
  const lines: Array<{ x: number; y: number }> = []
  const ctx = {
    save() {}, restore() {}, beginPath() {}, stroke() {},
    moveTo(x: number, y: number) { lines.push({ x, y }) },
    lineTo() {},
    fillText(text: string, x: number, y: number) { texts.push({ text, x, y }) },
    strokeStyle: '', fillStyle: '', lineWidth: 0, font: '',
  }
  const canvas = {
    width, height,
    getContext: (kind: string) => (kind === '2d' ? ctx : null),
  } as unknown as HTMLCanvasElement
  return { canvas, texts, lines }
}

describe('drawGridOverlay', () => {
  it('draws 16 labels A1..D4; A left/top, D right, 4 bottom', () => {
    const { canvas, texts } = stubCanvas(400, 400)
    drawGridOverlay(canvas)
    expect(texts).toHaveLength(16)
    const names = texts.map((t) => t.text).sort()
    const expected: string[] = []
    for (const col of ['A', 'B', 'C', 'D']) for (let r = 1; r <= 4; r++) expected.push(col + r)
    expect(names).toEqual(expected.sort())

    const a1 = texts.find((t) => t.text === 'A1')!
    const d4 = texts.find((t) => t.text === 'D4')!
    const d1 = texts.find((t) => t.text === 'D1')!
    expect(a1.x).toBeLessThan(100)        // col A = leftmost quarter
    expect(a1.y).toBeLessThan(100)        // row 1 = top quarter
    expect(d4.x).toBeGreaterThan(300)     // col D = rightmost quarter
    expect(d4.y).toBeGreaterThan(300)     // row 4 = bottom quarter
    expect(d1.y).toBeLessThan(100)        // D1 = top-right, not bottom
  })

  it('draws 6 divider lines (3 vertical + 3 horizontal) for a 4x4 grid', () => {
    const { canvas, lines } = stubCanvas(400, 400)
    drawGridOverlay(canvas)
    expect(lines).toHaveLength(6)
  })

  it('is a no-op without a 2d context', () => {
    const canvas = { width: 10, height: 10, getContext: () => null } as unknown as HTMLCanvasElement
    expect(() => drawGridOverlay(canvas)).not.toThrow()
  })
})
