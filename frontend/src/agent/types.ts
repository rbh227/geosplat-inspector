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

/** Movement directions shared by keyboard, pad, and the agent (v0.2). */
export type MoveDirection = 'forward' | 'back' | 'left' | 'right' | 'up' | 'down'

/** Look/turn directions driven by the rotate pad and the agent `turn` tool. */
export type RotateDirection = 'yaw-left' | 'yaw-right' | 'pitch-up' | 'pitch-down'

/** The slice of the existing renderer the agent layer drives. */
export interface RendererBridge {
  setCameraPose(position: THREE.Vector3, target: THREE.Vector3, animate?: boolean): void
  getCameraPose(): { position: THREE.Vector3; target: THREE.Vector3 }
  getBoundingBox(): THREE.Box3 | null
  /** World-space robust scene center + radius. The agent aims camera tools here
   *  because getBoundingBox() is mesh-local (mirrored for off-origin scenes). */
  getSceneCore(): { center: [number, number, number]; radius: number } | null
  /** Monotonic scene revision — bumps on every edit; tags captured percepts. */
  getSceneRevision(): number
  /** The operator's start-of-run view; `reframe` returns the camera here. */
  getHomePose(): { position: THREE.Vector3; target: THREE.Vector3 } | null
  getCamera(): THREE.PerspectiveCamera
  getRenderer(): THREE.WebGLRenderer
  getOverlayGroup(): THREE.Group
  /** Force one synchronous render of the current scene + camera. */
  renderOnce(): void
  loadSplat(url: string): Promise<void>
  isLoaded(): boolean

  // v0.2 — the shared selection/movement action layer (R13 parity)
  getCentersWorld(): { centers: Float32Array; ids: Uint32Array } | null
  getSelectionIds(): Uint32Array
  updateSelection(ids: Iterable<number>, mode?: 'add' | 'remove'): number
  clearSelection(): number
  invertSelection(): number
  getSelectionSummary(): { count: number; bbox: { min: number[]; max: number[] } | null }
  /** Robust percentile core box in BACKEND coords + count of centers inside —
   *  the "good cube" seed for the agent's crop proposal. */
  getCoreBoundsBox(): { min: number[]; max: number[]; count: number } | null
  showSelectionPreview(shape: 'sphere' | 'box', center: number[], size: number[]): void
  clearSelectionPreview(): void
  /** Persistent "good cube" crop proposal — SDF dim + wireframe in BACKEND
   *  coords, visible in the viewport and the agent's captures until cleared. */
  showProposalBox(min: number[], max: number[]): void
  clearProposalBox(): void
  getProposalBox(): { min: number[]; max: number[] } | null
  setMovementInput(direction: MoveDirection, active: boolean): void
  /** Hold a rotate-pad look input (yaw/pitch) — the agent `turn` tool. */
  setRotationInput(direction: RotateDirection, active: boolean): void
}

/** Result returned by a frontend tool executor (JSON-serializable).
 *  Capture results carry BARE base64 PNG (no data: prefix) under explicit keys
 *  the backend decodes into raw bytes (ws.py); single -> png_base64, orbit ->
 *  frames_base64. */
/** Where/when a percept was taken — every capture carries this so the agent
 *  never reasons on a stale frame (pose + monotonic scene revision). */
export interface PerceptTag {
  position: [number, number, number]
  target: [number, number, number]
  revision: number
  /** Fraction of the view the scene fills (0..1). ~0.4-0.7 well-framed;
   *  <0.15 too far, >0.9 too close. Lets the agent judge zoom without guessing. */
  coverage: number
}

export type ToolResult =
  | { ok: true }
  | { png_base64: string; percept?: PerceptTag }  // capture_frame
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
