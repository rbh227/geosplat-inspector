/**
 * Frame capture (R1 — black/empty frames are the top failure mode).
 *
 * Mitigations:
 *  - renderer is built `preserveDrawingBuffer:true` (root SceneManager) so the
 *    backbuffer survives until toBlob reads it.
 *  - force an OPAQUE clear color before reading so transparent regions don't
 *    flatten to black / punch alpha holes.
 *  - render, then wait a few frames for Spark's async depth-sort to settle,
 *    render once more, THEN read the pixels.
 */
import * as THREE from 'three'
import { nextStep } from './camera.ts'
import type { RendererBridge } from './types.ts'

const CLEAR_COLOR = 0x0b0d16
const SETTLE_FRAMES = 4

/**
 * Longest edge sent to the model, in pixels.
 *
 * A vision model bills by patch, not by file size: Qwen3-VL uses 14px patches
 * with a 2x2 merge, so tokens ~= (w/14)*(h/14)/4. An unscaled Retina viewport
 * (~2044x1316) is 13,724 patches = 3,431 tokens for ONE frame, and the vision
 * tower's activation for it OOM'd a 24GB card mid-run (the KV cache had already
 * claimed 92%), taking the whole server down. At 1024 the same view costs ~800
 * tokens and a quarter of the activation, which is plenty of detail for "is the
 * subject inside the box" and "how many buildings do you see".
 */
export const MAX_CAPTURE_EDGE = 1024

/** Target size preserving aspect ratio, capped at `MAX_CAPTURE_EDGE`. Never upscales. */
export function captureSize(
  width: number,
  height: number,
  maxEdge: number = MAX_CAPTURE_EDGE,
): { width: number; height: number } {
  const longest = Math.max(width, height)
  if (longest <= maxEdge || longest === 0) {
    return { width: Math.max(1, Math.round(width)), height: Math.max(1, Math.round(height)) }
  }
  const scale = maxEdge / longest
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
  }
}

/** Strip the `data:image/png;base64,` prefix, leaving bare base64 for the wire. */
export function dataUrlToBase64(dataUrl: string): string {
  const comma = dataUrl.indexOf(',')
  return comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl
}

async function blobToDataURL(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(blob)
  })
}

/**
 * Copy `canvas` onto a bounded-size 2D canvas, or return it unchanged when it
 * already fits (and when no 2D context is available — a downscale is an
 * optimisation, never a reason to fail a capture).
 */
function downscale(canvas: HTMLCanvasElement): HTMLCanvasElement {
  const target = captureSize(canvas.width, canvas.height)
  if (target.width === canvas.width && target.height === canvas.height) return canvas

  const out = document.createElement('canvas')
  out.width = target.width
  out.height = target.height
  const ctx = out.getContext('2d')
  if (!ctx) return canvas
  ctx.imageSmoothingEnabled = true
  ctx.imageSmoothingQuality = 'high'
  ctx.drawImage(canvas, 0, 0, target.width, target.height)
  return out
}

/** Burn a labeled grid into a capture (cells A1..D4; columns A-D left→right,
 *  rows 1-4 top→bottom — MUST match backend/analysis/clusters.cell_index). */
export function drawGridOverlay(canvas: HTMLCanvasElement, grid = 4): void {
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  const w = canvas.width, h = canvas.height
  ctx.save()
  ctx.strokeStyle = 'rgba(255,255,255,0.7)'
  ctx.lineWidth = Math.max(1, Math.round(w / 500))
  ctx.font = `bold ${Math.round(h / 24)}px sans-serif`
  ctx.fillStyle = 'rgba(255,220,0,0.9)'
  for (let i = 1; i < grid; i++) {
    ctx.beginPath(); ctx.moveTo((w * i) / grid, 0); ctx.lineTo((w * i) / grid, h); ctx.stroke()
    ctx.beginPath(); ctx.moveTo(0, (h * i) / grid); ctx.lineTo(w, (h * i) / grid); ctx.stroke()
  }
  for (let row = 0; row < grid; row++) {
    for (let col = 0; col < grid; col++) {
      const label = String.fromCharCode(65 + col) + String(row + 1)
      ctx.fillText(label, (w * col) / grid + w / (grid * 12), (h * row) / grid + h / (grid * 7))
    }
  }
  ctx.restore()
}

/** Copy a canvas so overlays never touch the live renderer backbuffer. */
function copyCanvas(canvas: HTMLCanvasElement): HTMLCanvasElement {
  const out = document.createElement('canvas')
  out.width = canvas.width
  out.height = canvas.height
  const ctx = out.getContext('2d')
  if (!ctx) return canvas
  ctx.drawImage(canvas, 0, 0)
  return out
}

/** Render the current view and return a clean, opaque PNG as a data URL. */
export async function capturePNG(
  bridge: RendererBridge,
  opts?: { grid?: boolean },
): Promise<string> {
  const renderer = bridge.getRenderer()
  const prevColor = new THREE.Color()
  renderer.getClearColor(prevColor)
  const prevAlpha = renderer.getClearAlpha()

  renderer.setClearColor(CLEAR_COLOR, 1)
  try {
    bridge.renderOnce()
    // nextStep (not raw rAF): rAF is throttled to zero in occluded windows,
    // which froze every capture the moment the operator switched away.
    for (let i = 0; i < SETTLE_FRAMES; i++) await nextStep(150)
    bridge.renderOnce()

    const canvas = renderer.domElement
    let source = downscale(canvas)
    if (opts?.grid) {
      // downscale() may hand back the LIVE renderer canvas (when it already
      // fits) — never draw the overlay on that; copy first.
      if (source === canvas) source = copyCanvas(canvas)
      drawGridOverlay(source)
    }
    const blob = await new Promise<Blob | null>((resolve) =>
      source.toBlob((b) => resolve(b), 'image/png'),
    )
    if (!blob) throw new Error('capturePNG: canvas.toBlob returned null')
    return await blobToDataURL(blob)
  } finally {
    renderer.setClearColor(prevColor, prevAlpha)
    bridge.renderOnce()
  }
}
