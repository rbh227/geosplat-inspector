import type * as THREE from 'three'
import type { MoveDirection, RotateDirection } from '../viewer/flyController.ts'

export type { MoveDirection, RotateDirection }

export interface CameraPose {
  position: THREE.Vector3
  target: THREE.Vector3
}

export type ViewPreset = 'front' | 'back' | 'top' | 'right' | 'left' | 'iso'

export interface SceneStats {
  count: number
  bbox: {
    min: { x: number; y: number; z: number }
    max: { x: number; y: number; z: number }
  }
  meanPosition: { x: number; y: number; z: number }
  stdPosition: { x: number; y: number; z: number }
  /** 10 buckets: [0-0.1), [0.1-0.2), ..., [0.9-1.0] */
  opacityHistogram: number[]
  /** 10 buckets for log10(maxScale), range determined dynamically */
  scaleHistogram: { buckets: number[]; minLog: number; maxLog: number }
  /** Top 5 dominant colors (clustered by HSL quantization) */
  dominantColors: Array<{ r: number; g: number; b: number; count: number }>
  /** Suggested starting radius for density filter */
  estimatedDensityRadius: number
}

export interface ViewerHandle {
  // Camera
  setCameraPose(position: THREE.Vector3, target: THREE.Vector3, animate?: boolean): void
  getCameraPose(): CameraPose
  lookAt(target: THREE.Vector3, animate?: boolean): void
  setView(preset: ViewPreset, animate?: boolean): void
  orbit(dx: number, dy: number): void
  dolly(amount: number): void

  // Capture
  captureFrame(): Promise<string>

  // Agent overlay hook (additive — consumed by /frontend/src/agent).
  // The agent layer owns its own marker/trail Object3D inside this group;
  // the renderer just hosts and draws it. See ARCHITECTURE.md §4.1.
  getOverlayGroup(): THREE.Group
  getCamera(): THREE.PerspectiveCamera
  getRenderer(): THREE.WebGLRenderer
  /** Force one synchronous render of the current scene+camera. */
  renderOnce(): void

  // Scene info
  getSplatCount(): number
  getBoundingBox(): THREE.Box3 | null
  /** World-space robust scene center + radius (agent camera aim; see SceneManager). */
  getSceneCore(): { center: [number, number, number]; radius: number } | null
  /** Monotonic scene revision — bumps on every edit; tags captured percepts. */
  getSceneRevision(): number
  /** The operator's start-of-run view; the agent's `reframe` home. */
  setHomePose(pose: { position: THREE.Vector3; target: THREE.Vector3 }): void
  getHomePose(): { position: THREE.Vector3; target: THREE.Vector3 } | null
  isLoaded(): boolean

  // Loading
  loadSplat(url: string, opts?: { keepCamera?: boolean }): Promise<void>
  loadSplatFile(file: File): Promise<void>

  // Cleanup
  cleanOpacity(threshold: number): number
  removeOutliers(k: number, stdFactor?: number): number
  cropBbox(min: THREE.Vector3, max: THREE.Vector3): number
  filterByScale(minScale?: number, maxScale?: number): number
  filterByColor(targetR: number, targetG: number, targetB: number, tolerance: number): number
  filterByDensity(minNeighbors: number, radius: number): number
  filterByHeight(minY?: number, maxY?: number): number

  // Fly navigation (v0.2 — KTD6)
  getNavigationMode(): 'orbit' | 'fly'
  setNavigationMode(mode: 'orbit' | 'fly'): void
  setMovementInput(direction: MoveDirection, active: boolean): void
  getActiveDirections(): MoveDirection[]

  // Rotate control (R7/R8) — works in both nav modes
  setRotationInput(direction: RotateDirection, active: boolean): void
  getActiveRotations(): RotateDirection[]

  // Stable-ID editing (v0.2 — KTD2/KTD3)
  getLiveIds(): Uint32Array
  deleteByIds(ids: Iterable<number>): number
  keepOnlyIds(ids: Iterable<number>): number
  getCentersWorld(): { centers: Float32Array; ids: Uint32Array } | null
  setIdMapFromIds(ids: ArrayLike<number>): void

  // Selection (v0.2)
  getSelectionIds(): Uint32Array
  getSelectionCount(): number
  updateSelection(ids: Iterable<number>, mode?: 'add' | 'remove'): number
  clearSelection(): number
  invertSelection(): number
  getSelectionSummary(): { count: number; bbox: { min: number[]; max: number[] } | null }
  /** Robust percentile core box in BACKEND coords + count of centers inside. */
  getCoreBoundsBox(): { min: number[]; max: number[]; count: number } | null
  deleteSelection(): Uint32Array
  keepSelection(): Uint32Array
  showSelectionPreview(shape: 'sphere' | 'box', center: number[], size: number[]): void
  clearSelectionPreview(): void

  // Operator crop-box tool
  beginCropBox(seed?: { min: number[]; max: number[] }): void
  endCropBox(): void
  getCropBox(): { min: number[]; max: number[] } | null
  cropBoxCount(): number
  cropToBox(): Uint32Array

  // Analysis
  getSceneStats(): SceneStats | null

  // Undo
  undo(): boolean
  canUndo(): boolean
  getUndoStackLabels(): string[]
}

export interface ViewerState {
  splatCount: number
  fps: number
  cameraPosition: [number, number, number]
  fileName: string | null
  isLoading: boolean
  undoCount: number
  navigationMode: 'orbit' | 'fly'
}
