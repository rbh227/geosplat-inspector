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
import type { RendererBridge } from './types.ts'

const CLEAR_COLOR = 0x0b0d16
const SETTLE_FRAMES = 4

function nextFrame(): Promise<void> {
  return new Promise((r) => requestAnimationFrame(() => r()))
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

/** Render the current view and return a clean, opaque PNG as a data URL. */
export async function capturePNG(bridge: RendererBridge): Promise<string> {
  const renderer = bridge.getRenderer()
  const prevColor = new THREE.Color()
  renderer.getClearColor(prevColor)
  const prevAlpha = renderer.getClearAlpha()

  renderer.setClearColor(CLEAR_COLOR, 1)
  try {
    bridge.renderOnce()
    for (let i = 0; i < SETTLE_FRAMES; i++) await nextFrame()
    bridge.renderOnce()

    const canvas = renderer.domElement
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob((b) => resolve(b), 'image/png'),
    )
    if (!blob) throw new Error('capturePNG: canvas.toBlob returned null')
    return await blobToDataURL(blob)
  } finally {
    renderer.setClearColor(prevColor, prevAlpha)
    bridge.renderOnce()
  }
}
