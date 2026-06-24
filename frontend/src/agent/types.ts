/**
 * Agent-layer types. Boundary: /frontend/src/agent only.
 *
 * The agent layer never imports renderer internals. It depends on a narrow
 * `RendererBridge` slice of the existing ViewerHandle (implemented by
 * SceneManager in root src/viewer) which is injected at construction.
 */
import type * as THREE from 'three'
import type { FrontendToolName } from '../contracts.ts'

export type { FrontendToolName } from '../contracts.ts'

/** The slice of the existing renderer the agent layer drives. */
export interface RendererBridge {
  setCameraPose(position: THREE.Vector3, target: THREE.Vector3, animate?: boolean): void
  getCameraPose(): { position: THREE.Vector3; target: THREE.Vector3 }
  getBoundingBox(): THREE.Box3 | null
  getCamera(): THREE.PerspectiveCamera
  getRenderer(): THREE.WebGLRenderer
  getOverlayGroup(): THREE.Group
  /** Force one synchronous render of the current scene + camera. */
  renderOnce(): void
  loadSplat(url: string): Promise<void>
  isLoaded(): boolean
}

/** Result returned by a frontend tool executor (JSON-serializable).
 *  Capture results carry BARE base64 PNG (no data: prefix) under explicit keys
 *  the backend decodes into raw bytes (ws.py); single -> png_base64, orbit ->
 *  frames_base64. */
export type ToolResult =
  | { ok: true }
  | { png_base64: string }        // capture_frame
  | { frames_base64: string[] }   // capture_orbit

/** Payload carried by a `camera_move` command (which specific camera tool). */
export interface CameraMovePayload {
  tool: Extract<
    FrontendToolName,
    'look_at' | 'set_view' | 'orbit' | 'dolly' | 'frame_object' | 'reset_view' | 'scan_pause'
  >
  args: Record<string, unknown>
}

/** A breadcrumb / narration / trace entry surfaced to the UI panels. */
export interface TraceEntry {
  kind: 'thought' | 'tool_call' | 'tool_result' | 'narrate' | 'complete'
  text: string
  detail?: Record<string, unknown>
  at: number
}
