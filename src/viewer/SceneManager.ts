import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import {
  SparkRenderer,
  SplatMesh,
  SplatEdit,
  SplatEditSdf,
  SplatEditSdfType,
  SplatEditRgbaBlendMode,
} from '@sparkjsdev/spark'
import type { ViewerHandle, ViewerState, ViewPreset, SceneStats } from '../types/viewer.ts'
import { tweenCamera } from './camera.ts'
import { computeFraming, computeCoreBounds, computeTightCoreBox, nearFarForDistance, type Vec3 } from './framing.ts'
import { IdMap } from './idMap.ts'
import { transformPoints } from './selection.ts'
import { composeMove, composeLook, type MoveDirection, type RotateDirection } from './flyController.ts'
import { TintStore, tintedColor } from './selectionTint.ts'
import { CropBoxGizmo } from './CropBoxGizmo.ts'
import { countInsideSampled, isInsideBox, shouldCommitCrop, type Box } from './cropBoxMath.ts'

/* ------------------------------------------------------------------ */
/*  Constants                                                         */
/* ------------------------------------------------------------------ */

const TWEEN_DURATION_MS = 500
const INTS_PER_SPLAT = 8 // PackedSplats stores 8 x uint32 per splat
const MAX_PITCH = 1.5 // radians (~86°) — pitch clamp shared by drag-look and the rotate pad

/* ------------------------------------------------------------------ */
/*  Undo snapshot                                                     */
/* ------------------------------------------------------------------ */

interface UndoEntry {
  label: string
  data: Uint32Array
  numSplats: number
  /** ID-map state captured with the buffer — restored together on undo. */
  idMapSnap: { data: Uint32Array; live: number } | null
}

/* ------------------------------------------------------------------ */
/*  Box overlay (SDF dim + wireframe)                                 */
/* ------------------------------------------------------------------ */

/**
 * Persistent SDF dim + crisp wireframe, parented to the splat mesh so both
 * live in backend coords and appear in captures. Pure rendering — no
 * knowledge of who owns it. Two independent instances back the agent's
 * proposal-box channel and the operator's crop-box channel (fix pass 2,
 * IMPORTANT 1): before this class existed, both tools drove ONE shared pair
 * of scene objects, so opening the crop tool destroyed a parked agent
 * proposal and `getProposalBox()` started returning the operator's box.
 */
class BoxOverlay {
  private edit: SplatEdit | null = null
  private wire: THREE.LineSegments | null = null
  private state: { min: number[]; max: number[] } | null = null

  constructor(
    private getMesh: () => SplatMesh | null,
    private wireColor: number,
    private sdfColor: THREE.Color,
  ) {}

  show(min: number[], max: number[]): void {
    const mesh = this.getMesh()
    if (!mesh) return
    this.clear()
    const center = [(min[0]+max[0])/2, (min[1]+max[1])/2, (min[2]+max[2])/2]
    const half = [(max[0]-min[0])/2, (max[1]-min[1])/2, (max[2]-min[2])/2]
    const edit = new SplatEdit({ rgbaBlendMode: SplatEditRgbaBlendMode.MULTIPLY })
    const sdf = new SplatEditSdf({
      type: SplatEditSdfType.BOX,
      opacity: 0.25,
      color: this.sdfColor.clone(),
    })
    edit.addSdf(sdf); edit.add(sdf); mesh.add(edit)
    sdf.position.set(center[0], center[1], center[2])
    sdf.radius = 0
    sdf.scale.set(Math.max(half[0], 1e-4), Math.max(half[1], 1e-4), Math.max(half[2], 1e-4))
    const geom = new THREE.BoxGeometry(max[0]-min[0], max[1]-min[1], max[2]-min[2])
    const wire = new THREE.LineSegments(
      new THREE.EdgesGeometry(geom),
      new THREE.LineBasicMaterial({ color: this.wireColor }),
    )
    geom.dispose()
    wire.position.set(center[0], center[1], center[2])
    mesh.add(wire)
    this.edit = edit
    this.wire = wire
    this.state = { min: [...min], max: [...max] }
  }

  clear(): void {
    const mesh = this.getMesh()
    if (mesh) {
      if (this.edit) mesh.remove(this.edit)
      if (this.wire) mesh.remove(this.wire)
    }
    this.wire?.geometry.dispose()
    ;(this.wire?.material as THREE.LineBasicMaterial | undefined)?.dispose()
    this.edit = null
    this.wire = null
    this.state = null
  }

  getState(): { min: number[]; max: number[] } | null {
    return this.state
  }
}

/* ------------------------------------------------------------------ */
/*  SceneManager                                                      */
/* ------------------------------------------------------------------ */

export class SceneManager implements ViewerHandle {
  /* Three.js primitives */
  private renderer: THREE.WebGLRenderer
  private scene: THREE.Scene
  private camera: THREE.PerspectiveCamera
  private controls: OrbitControls

  /* Spark */
  private spark: SparkRenderer
  private splatMesh: SplatMesh | null = null

  /* State */
  private container: HTMLDivElement | null = null
  private animFrameId = 0
  private mounted = false
  private fileName: string | null = null
  private loading = false

  /* FPS tracking */
  private frameCount = 0
  private lastFpsTime = performance.now()
  private currentFps = 0

  /* Camera tween */
  private cancelTween: (() => void) | null = null

  /* Undo */
  private undoStack: UndoEntry[] = []

  /* Stable splat identity across compaction (KTD3) */
  private idMap: IdMap | null = null

  /* Selection (v0.2) — original-ID set, survives compaction by construction */
  private selection = new Set<number>()
  private sdfPreviewEdit: SplatEdit | null = null
  private sdfPreviewSdf: SplatEditSdf | null = null

  /* Persistent selection tint (Task 6) — remembers each tinted splat's true
     color (keyed by original ID) so the warm highlight restores exactly on
     deselect. Driven from emitSelectionChange, so it covers manual AND agent
     selections uniformly. */
  private tint = new TintStore()

  /* Selection-change callback (count for the toolbar/status surfaces) */
  onSelectionChange: ((count: number) => void) | null = null

  /* Fly navigation (KTD6) — custom thin controller, see flyController.ts */
  private navigationMode: 'orbit' | 'fly' = 'orbit'
  private activeDirections = new Set<MoveDirection>()
  private clock = new THREE.Clock()
  private flyDistance = 3        // carried look-target distance across mode switches
  private flySpeed = 3           // world units/sec, scaled to scene radius on entry
  // Cached world-space scene core for cheap per-frame near/far tracking. Set on
  // load/frame and after every edit; lets the frustum follow the camera without
  // re-sampling all centers every frame.
  private sceneCenter = new THREE.Vector3()
  private sceneRadius = 0
  // Monotonic scene revision — bumps on every edit (markSplatDirty). A captured
  // percept is tagged with this so the agent never reasons on a stale frame.
  private revision = 0
  private lookActive = false     // drag-to-look pointer state
  private lookLast = { x: 0, y: 0 }
  private restoreFlyAfterTween = false

  /* Rotate control (R7/R8) — pad-held directions drive the per-frame step;
     the agent-pulse set drives the highlight ONLY, never the rotation math,
     so agent rotation keeps its degree precision. */
  private activeRotations = new Set<RotateDirection>()
  private agentRotationPulse = new Set<RotateDirection>()
  private agentPulseTimer: ReturnType<typeof setTimeout> | null = null
  private rotateSpeed = 1.2 // radians/sec while a pad button is held

  /* Callback for React state sync */
  onStateChange: ((state: ViewerState) => void) | null = null

  /* Movement-state callback (pad highlight — fires for ANY input source) */
  onMovementChange: ((dirs: MoveDirection[]) => void) | null = null

  /* Rotation-state callback (rotate-pad highlight — fires for ANY input source) */
  onRotationChange: ((dirs: RotateDirection[]) => void) | null = null

  /* ---------------------------------------------------------------- */
  /*  Constructor                                                     */
  /* ---------------------------------------------------------------- */

  constructor() {
    this.renderer = new THREE.WebGLRenderer({
      preserveDrawingBuffer: true,
      antialias: false,
    })
    // Cap DPR at 2: on Retina (DPR 2-3) an uncapped ratio renders 4-9x the
    // pixels and tanks FPS on large (600K+ splat) scenes.
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    // Subtle, opaque non-black clear so a small/distant subject isn't lost in
    // black margins (also satisfies the opaque-clear requirement for captures).
    // Neutral gray to match the workbench chrome (--color-bg-deep).
    this.renderer.setClearColor(0x151515, 1)

    this.scene = new THREE.Scene()

    this.camera = new THREE.PerspectiveCamera(60, 1, 0.1, 1000)
    this.camera.position.set(0, 1.5, 3)

    this.spark = new SparkRenderer({
      renderer: this.renderer,
      onDirty: () => {
        /* The render loop is always running, so nothing extra is needed. */
      },
    })
    this.scene.add(this.spark)

    // Controls are created with a temporary element; the real one is
    // attached in mount().
    this.controls = new OrbitControls(this.camera, this.renderer.domElement)
    this.controls.enableDamping = true
    this.controls.dampingFactor = 0.12
    this.controls.target.set(0, 0, 0)
    this.controls.update()
  }

  /* ---------------------------------------------------------------- */
  /*  Mount / unmount                                                 */
  /* ---------------------------------------------------------------- */

  mount(container: HTMLDivElement): void {
    if (this.mounted) return
    this.container = container
    container.appendChild(this.renderer.domElement)

    // Re-attach controls to the mounted element
    this.controls.dispose()
    this.controls = new OrbitControls(this.camera, this.renderer.domElement)
    this.controls.enableDamping = true
    this.controls.dampingFactor = 0.12
    // Allow full vertical orbit so the user can view from any angle
    this.controls.minPolarAngle = 0
    this.controls.maxPolarAngle = Math.PI
    this.controls.update()

    this.handleResize()
    window.addEventListener('resize', this.handleResize)

    // Fly-mode drag-to-look (inert while in orbit mode)
    const el = this.renderer.domElement
    el.addEventListener('pointerdown', this.onLookStart)
    el.addEventListener('pointermove', this.onLookMove)
    window.addEventListener('pointerup', this.onLookEnd)

    this.mounted = true
    this.loop()
  }

  unmount(): void {
    this.mounted = false
    cancelAnimationFrame(this.animFrameId)
    if (this.agentPulseTimer) {
      clearTimeout(this.agentPulseTimer)
      this.agentPulseTimer = null
    }
    window.removeEventListener('resize', this.handleResize)
    const el = this.renderer.domElement
    el.removeEventListener('pointerdown', this.onLookStart)
    el.removeEventListener('pointermove', this.onLookMove)
    window.removeEventListener('pointerup', this.onLookEnd)
    this.controls.dispose()
    // Dispose the crop gizmo's TransformControls helper — it owns its own
    // pointer/keyboard listeners on the DOM element (MINOR 7).
    this.cropGizmo?.dispose()
    this.cropGizmo = null
    this.renderer.domElement.remove()
    this.renderer.dispose()
    this.spark.dispose()
    this.splatMesh?.dispose()
    this.container = null
  }

  /* ---------------------------------------------------------------- */
  /*  Render loop                                                     */
  /* ---------------------------------------------------------------- */

  private loop = (): void => {
    if (!this.mounted) return
    this.animFrameId = requestAnimationFrame(this.loop)

    const dt = this.clock.getDelta() // every frame, so deltas stay small
    if (this.navigationMode === 'fly') {
      this.stepFly(dt)
    } else {
      this.stepOrbitMove(dt)
      this.controls.update()
    }
    this.stepRotate(dt)
    this.refreshNearFar()  // frustum follows the camera (agent flies far from load pose)
    this.spark.render(this.scene, this.camera)

    // FPS
    this.frameCount++
    const now = performance.now()
    if (now - this.lastFpsTime >= 1000) {
      this.currentFps = this.frameCount
      this.frameCount = 0
      this.lastFpsTime = now
      this.emitStateChange()
    }
  }

  private handleResize = (): void => {
    if (!this.container) return
    const w = this.container.clientWidth
    const h = this.container.clientHeight
    this.camera.aspect = w / h
    this.camera.updateProjectionMatrix()
    this.renderer.setSize(w, h)
  }

  /* ---------------------------------------------------------------- */
  /*  State                                                           */
  /* ---------------------------------------------------------------- */

  getState(): ViewerState {
    const p = this.camera.position
    return {
      splatCount: this.getSplatCount(),
      fps: this.currentFps,
      cameraPosition: [p.x, p.y, p.z],
      fileName: this.fileName,
      isLoading: this.loading,
      undoCount: this.undoStack.length,
      navigationMode: this.navigationMode,
    }
  }

  private emitStateChange(): void {
    this.onStateChange?.(this.getState())
  }

  /* ---------------------------------------------------------------- */
  /*  ViewerHandle – Camera                                           */
  /* ---------------------------------------------------------------- */

  setCameraPose(
    position: THREE.Vector3,
    target: THREE.Vector3,
    animate = true,
  ): void {
    this.cancelCurrentTween()
    // Fast path: the agent's animation layer calls animate=false EVERY FRAME
    // (frontend/src/agent/camera.ts drives its own rAF tween). In fly mode,
    // drive the camera directly — no mode churn, no coreBounds resampling.
    if (this.navigationMode === 'fly' && !animate) {
      // The agent's rotation tools drive this path frame-by-frame; compare
      // orientation before/after so the rotate pad lights for them too (R8).
      const before = this.cameraEuler()
      this.camera.position.copy(position)
      this.camera.lookAt(target)
      this.flyDistance = position.distanceTo(target) || this.flyDistance
      const after = this.cameraEuler()
      const dYaw = after.y - before.y
      const dPitch = after.x - before.x
      const dirs: RotateDirection[] = []
      if (Math.abs(dYaw) > 1e-4) dirs.push(dYaw > 0 ? 'yaw-left' : 'yaw-right')
      if (Math.abs(dPitch) > 1e-4) dirs.push(dPitch > 0 ? 'pitch-up' : 'pitch-down')
      this.pulseRotationHighlight(dirs)
      this.emitStateChange()
      return
    }
    // Animated pose sets (presets, internal tweens) auto-yield fly mode: the
    // tween drives OrbitControls, and fly resumes on completion.
    const wasFly = this.navigationMode === 'fly'
    if (wasFly) this.setNavigationMode('orbit')
    if (animate) {
      this.restoreFlyAfterTween = wasFly
      this.cancelTween = tweenCamera(
        this.controls,
        this.camera,
        position,
        target,
        TWEEN_DURATION_MS,
        () => {
          if (this.restoreFlyAfterTween) {
            this.restoreFlyAfterTween = false
            this.setNavigationMode('fly')
          }
          this.emitStateChange()
        },
      )
    } else {
      this.camera.position.copy(position)
      this.controls.target.copy(target)
      this.controls.update()
      if (wasFly) this.setNavigationMode('fly')
      this.emitStateChange()
    }
  }

  getCameraPose() {
    if (this.navigationMode === 'fly') {
      // FlyControls-style navigation has no orbit target; expose a virtual
      // one projected along the view direction so every consumer of
      // getCameraPose().target keeps working (KTD6).
      const dir = this.camera.getWorldDirection(new THREE.Vector3())
      return {
        position: this.camera.position.clone(),
        target: this.camera.position.clone().add(dir.multiplyScalar(this.flyDistance)),
      }
    }
    return {
      position: this.camera.position.clone(),
      target: this.controls.target.clone(),
    }
  }

  /* ---------------------------------------------------------------- */
  /*  ViewerHandle – Fly navigation (v0.2, KTD6)                      */
  /* ---------------------------------------------------------------- */

  getNavigationMode(): 'orbit' | 'fly' {
    return this.navigationMode
  }

  setNavigationMode(mode: 'orbit' | 'fly'): void {
    if (mode === this.navigationMode) return
    this.cancelCurrentTween()
    this.restoreFlyAfterTween = false
    if (mode === 'fly') {
      this.flyDistance = this.camera.position.distanceTo(this.controls.target) || 3
      const radius = this.coreBounds()?.radius ?? 3
      this.flySpeed = Math.max(radius * 0.6, 0.5)
      this.activeDirections.clear()
      this.emitMovementChange()
      this.controls.enabled = false
    } else {
      // Hand the orbit controller a coherent target: forward-projected at the
      // carried distance, so there is no jump on re-entry.
      const dir = this.camera.getWorldDirection(new THREE.Vector3())
      this.controls.target.copy(this.camera.position).add(dir.multiplyScalar(this.flyDistance))
      this.controls.enabled = true
      this.controls.update()
      this.activeDirections.clear()
      this.emitMovementChange()
      this.lookActive = false
    }
    this.navigationMode = mode
    this.emitStateChange()
  }

  /**
   * Velocity-style movement input — the ONE entry point shared by keyboard,
   * the on-screen pad, and the agent's move_camera tool (R13: any source
   * lights the pad). Movement works in BOTH nav modes and never forces a
   * switch: in orbit it translates the camera and its target together so the
   * mouse keeps orbiting (Bug 2 fix — no fly-mode trap); in fly it drives
   * free flight.
   */
  setMovementInput(direction: MoveDirection, active: boolean): void {
    const had = this.activeDirections.has(direction)
    if (active === had) return
    if (active) this.activeDirections.add(direction)
    else this.activeDirections.delete(direction)
    this.emitMovementChange()
  }

  getActiveDirections(): MoveDirection[] {
    return Array.from(this.activeDirections)
  }

  private emitMovementChange(): void {
    this.onMovementChange?.(this.getActiveDirections())
  }

  private stepFly(dt: number): void {
    if (this.activeDirections.size === 0) return
    const fwd = this.camera.getWorldDirection(new THREE.Vector3())
    const right = new THREE.Vector3().crossVectors(fwd, this.camera.up).normalize()
    const [dx, dy, dz] = composeMove(
      this.activeDirections,
      [fwd.x, fwd.y, fwd.z],
      [right.x, right.y, right.z],
      [0, 1, 0],
      this.flySpeed,
      dt,
    )
    this.camera.position.x += dx
    this.camera.position.y += dy
    this.camera.position.z += dz
  }

  /**
   * Orbit-mode movement (Bug 2): translate the camera AND its orbit target by
   * the same per-frame delta, so free WASD/pad motion never disables or fights
   * OrbitControls — the mouse keeps orbiting before, during, and after a move.
   * Speed scales with orbit distance so it feels consistent at any zoom.
   */
  private stepOrbitMove(dt: number): void {
    if (this.activeDirections.size === 0) return
    const fwd = this.camera.getWorldDirection(new THREE.Vector3())
    const right = new THREE.Vector3().crossVectors(fwd, this.camera.up).normalize()
    const dist = this.camera.position.distanceTo(this.controls.target)
    const speed = Math.max(dist * 0.6, 0.5)
    const [dx, dy, dz] = composeMove(
      this.activeDirections,
      [fwd.x, fwd.y, fwd.z],
      [right.x, right.y, right.z],
      [0, 1, 0],
      speed,
      dt,
    )
    this.camera.position.x += dx
    this.camera.position.y += dy
    this.camera.position.z += dz
    this.controls.target.x += dx
    this.controls.target.y += dy
    this.controls.target.z += dz
  }

  /* Rotate control (R7/R8) — button-based direction changes, both nav modes */

  /** Velocity-style rotation input from the on-screen rotate pad. Unlike
   *  movement, rotation works in BOTH nav modes and never forces a switch. */
  setRotationInput(direction: RotateDirection, active: boolean): void {
    const had = this.activeRotations.has(direction)
    if (active === had) return
    if (active) this.activeRotations.add(direction)
    else this.activeRotations.delete(direction)
    this.emitRotationChange()
  }

  getActiveRotations(): RotateDirection[] {
    if (this.agentRotationPulse.size === 0) return Array.from(this.activeRotations)
    return Array.from(new Set([...this.activeRotations, ...this.agentRotationPulse]))
  }

  private emitRotationChange(): void {
    this.onRotationChange?.(this.getActiveRotations())
  }

  /** Flash the rotate pad for agent-driven rotation (R8). Highlight only —
   *  the pulse set is never consumed by the rotation math. Called per frame
   *  during agent tweens, so React is only notified when the set changes;
   *  the timer reset still runs every call to keep a long tween lit. */
  private pulseRotationHighlight(dirs: RotateDirection[]): void {
    if (dirs.length === 0) return
    let changed = false
    dirs.forEach((d) => {
      if (!this.agentRotationPulse.has(d)) {
        this.agentRotationPulse.add(d)
        changed = true
      }
    })
    if (changed) this.emitRotationChange()
    if (this.agentPulseTimer) clearTimeout(this.agentPulseTimer)
    this.agentPulseTimer = setTimeout(() => {
      this.agentPulseTimer = null
      this.agentRotationPulse.clear()
      this.emitRotationChange()
    }, 250)
  }

  private stepRotate(dt: number): void {
    if (this.activeRotations.size === 0) return
    const [dYaw, dPitch] = composeLook(this.activeRotations, this.rotateSpeed, dt)
    this.applyLook(dYaw, dPitch)
  }

  /** Camera orientation as a YXZ euler — the order is load-bearing: yaw (y)
   *  and pitch (x) stay independent, matching the drag-look math. */
  private cameraEuler(): THREE.Euler {
    return new THREE.Euler(0, 0, 0, 'YXZ').setFromQuaternion(this.camera.quaternion)
  }

  /** Rotate the view by yaw/pitch radians, honoring the current nav mode:
   *  orbit rotates around the target, fly turns the camera in place. */
  private applyLook(dYaw: number, dPitch: number): void {
    if (this.navigationMode === 'orbit') {
      this.controls.rotateLeft(dYaw)
      this.controls.rotateUp(dPitch)
      this.controls.update()
    } else {
      const euler = this.cameraEuler()
      euler.y += dYaw
      euler.x = Math.max(-MAX_PITCH, Math.min(MAX_PITCH, euler.x + dPitch))
      this.camera.quaternion.setFromEuler(euler)
    }
  }

  /* Drag-to-look (fly mode only; orbit mode keeps OrbitControls' own drag) */

  private onLookStart = (e: PointerEvent): void => {
    if (this.navigationMode !== 'fly') return
    this.lookActive = true
    this.lookLast = { x: e.clientX, y: e.clientY }
  }

  private onLookMove = (e: PointerEvent): void => {
    if (!this.lookActive || this.navigationMode !== 'fly') return
    const dx = e.clientX - this.lookLast.x
    const dy = e.clientY - this.lookLast.y
    this.lookLast = { x: e.clientX, y: e.clientY }
    const euler = this.cameraEuler()
    euler.y -= dx * 0.004
    euler.x = Math.max(-MAX_PITCH, Math.min(MAX_PITCH, euler.x - dy * 0.004))
    this.camera.quaternion.setFromEuler(euler)
  }

  private onLookEnd = (): void => {
    this.lookActive = false
  }

  lookAt(target: THREE.Vector3, animate = true): void {
    this.setCameraPose(this.camera.position.clone(), target, animate)
  }

  setView(preset: ViewPreset, animate = true): void {
    const bounds = this.coreBounds()
    const center = bounds
      ? new THREE.Vector3(bounds.center[0], bounds.center[1], bounds.center[2])
      : new THREE.Vector3()
    const radius = bounds ? bounds.radius : 3

    const posMap: Record<ViewPreset, THREE.Vector3> = {
      front: new THREE.Vector3(center.x, center.y, center.z + radius),
      back: new THREE.Vector3(center.x, center.y, center.z - radius),
      top: new THREE.Vector3(center.x, center.y + radius, center.z),
      right: new THREE.Vector3(center.x + radius, center.y, center.z),
      left: new THREE.Vector3(center.x - radius, center.y, center.z),
      iso: new THREE.Vector3(
        center.x + radius * 0.57,
        center.y + radius * 0.57,
        center.z + radius * 0.57,
      ),
    }

    // Preset cameras sit at `radius` (or `radius * 0.57 * √3 ≈ radius` for iso)
    // from the target. Derive near/far from that distance + scene radius so
    // large scenes keep usable depth precision after a preset jump.
    const distance = posMap[preset].distanceTo(center)
    const { near, far } = nearFarForDistance(distance, radius)
    this.camera.near = near
    this.camera.far = far
    this.camera.updateProjectionMatrix()

    this.setCameraPose(posMap[preset], center, animate)
  }

  orbit(dx: number, dy: number): void {
    // Convert degrees to radians – the agent/tool sends degrees
    this.controls.rotateLeft((dx * Math.PI) / 180)
    this.controls.rotateUp((dy * Math.PI) / 180)
    this.controls.update()
    const dirs: RotateDirection[] = []
    if (dx !== 0) dirs.push(dx > 0 ? 'yaw-left' : 'yaw-right')
    if (dy !== 0) dirs.push(dy > 0 ? 'pitch-up' : 'pitch-down')
    this.pulseRotationHighlight(dirs)
    this.emitStateChange()
  }

  dolly(amount: number): void {
    if (amount > 0) {
      this.controls.dollyIn(amount)
    } else {
      this.controls.dollyOut(-amount)
    }
    this.controls.update()
    this.emitStateChange()
  }

  /* ---------------------------------------------------------------- */
  /*  ViewerHandle – Capture                                          */
  /* ---------------------------------------------------------------- */

  async captureFrame(): Promise<string> {
    // Force one synchronous render so the buffer is fresh
    this.spark.render(this.scene, this.camera)
    return this.renderer.domElement.toDataURL('image/jpeg', 0.8)
  }

  /* ---------------------------------------------------------------- */
  /*  Agent overlay hook (additive — used by /frontend/src/agent)     */
  /* ---------------------------------------------------------------- */

  private overlayGroup: THREE.Group | null = null

  /** Scene-space group the agent overlay (markers, trail) attaches to.
   *  Created lazily and drawn every frame by the existing render loop. */
  getOverlayGroup(): THREE.Group {
    if (!this.overlayGroup) {
      const group = new THREE.Group()
      group.name = 'agent-overlay'
      // Overlay is in world space; do NOT inherit the splat Y-flip.
      this.scene.add(group)
      this.overlayGroup = group
    }
    return this.overlayGroup
  }

  getCamera(): THREE.PerspectiveCamera {
    return this.camera
  }

  getRenderer(): THREE.WebGLRenderer {
    return this.renderer
  }

  /** Force one synchronous render of the current scene + camera. */
  renderOnce(): void {
    this.controls.update()
    this.spark.render(this.scene, this.camera)
  }

  /* ---------------------------------------------------------------- */
  /*  ViewerHandle – Scene info                                       */
  /* ---------------------------------------------------------------- */

  getSplatCount(): number {
    if (!this.splatMesh?.packedSplats) return 0
    return this.splatMesh.packedSplats.numSplats
  }

  getBoundingBox(): THREE.Box3 | null {
    if (!this.splatMesh) return null
    return this.splatMesh.getBoundingBox()
  }

  /**
   * World-space robust scene center + radius (the same framing core the view
   * presets use). Public so the agent's camera tools can aim at the real
   * scene: `getBoundingBox()` is mesh-LOCAL (packedSplats carry a rotation.x=π
   * Y/Z flip), so its center is mirrored for any off-origin scene. This is
   * world-space and safe to hand a camera pose.
   */
  getSceneCore(): { center: [number, number, number]; radius: number } | null {
    return this.coreBounds()
  }

  isLoaded(): boolean {
    return this.splatMesh !== null && this.splatMesh.isInitialized
  }

  /* ---------------------------------------------------------------- */
  /*  ViewerHandle – Loading                                          */
  /* ---------------------------------------------------------------- */

  async loadSplat(url: string, opts?: { keepCamera?: boolean }): Promise<void> {
    this.loading = true
    this.emitStateChange()

    try {
      this.disposeSplatMesh()
      this.undoStack = []

      const parts = url.split('/')
      this.fileName = parts[parts.length - 1] ?? url

      const mesh = new SplatMesh({
        url,
        editable: true,
      })
      // Flip Y — most splats are trained in COLMAP coords (Y-down)
      mesh.rotation.x = Math.PI
      this.scene.add(mesh)
      this.splatMesh = mesh

      await mesh.initialized

      // Fresh identity map: original IDs 0..N-1 (KTD3). Backend-driven
      // reloads overwrite this via setIdMapFromIds with the alive-ID list.
      this.idMap = new IdMap(mesh.packedSplats?.numSplats ?? 0)
      this.selection.clear()
      this.emitSelectionChange()

      if (opts?.keepCamera) {
        // Authoritative reload of the SAME scene: hold the operator's pose.
        // Still refresh the core cache — the alive set may have changed.
        this.cacheSceneCore()
      } else {
        this.frameScene()
      }
    } finally {
      this.loading = false
      this.emitStateChange()
    }
  }

  async loadSplatFile(file: File): Promise<void> {
    this.loading = true
    this.emitStateChange()

    try {
      this.disposeSplatMesh()
      this.undoStack = []

      this.fileName = file.name

      const buffer = await file.arrayBuffer()

      const mesh = new SplatMesh({
        fileBytes: new Uint8Array(buffer),
        editable: true,
      })
      mesh.rotation.x = Math.PI
      this.scene.add(mesh)
      this.splatMesh = mesh

      await mesh.initialized

      // Fresh identity map: original IDs 0..N-1 (KTD3). Backend-driven
      // reloads overwrite this via setIdMapFromIds with the alive-ID list.
      this.idMap = new IdMap(mesh.packedSplats?.numSplats ?? 0)
      this.selection.clear()
      this.emitSelectionChange()

      this.frameScene()
    } finally {
      this.loading = false
      this.emitStateChange()
    }
  }

  /* ---------------------------------------------------------------- */
  /*  ViewerHandle – Cleanup operations                               */
  /* ---------------------------------------------------------------- */

  cleanOpacity(threshold: number): number {
    const packed = this.splatMesh?.packedSplats
    if (!packed) return 0

    this.pushUndoSnapshot('Clean opacity')

    const total = packed.numSplats
    let writeIdx = 0

    for (let i = 0; i < total; i++) {
      const splat = packed.getSplat(i)
      if (splat.opacity >= threshold) {
        if (writeIdx !== i) {
          packed.setSplat(
            writeIdx,
            splat.center,
            splat.scales,
            splat.quaternion,
            splat.opacity,
            splat.color,
          )
        }
        this.idMap?.retain(writeIdx, i)
        writeIdx++
      }
    }

    const removed = total - writeIdx
    packed.numSplats = writeIdx
    this.idMap?.setLive(writeIdx)
    this.markSplatDirty()
    this.emitStateChange()
    return removed
  }

  removeOutliers(k: number, stdFactor = 1.0): number {
    const packed = this.splatMesh?.packedSplats
    if (!packed || packed.numSplats === 0) return 0

    this.pushUndoSnapshot('Remove outliers')

    const n = packed.numSplats

    // Compute mean position
    const mean = new THREE.Vector3()
    for (let i = 0; i < n; i++) {
      const s = packed.getSplat(i)
      mean.add(s.center)
    }
    mean.divideScalar(n)

    // Compute standard deviation of distances from mean
    let sumSqDist = 0
    for (let i = 0; i < n; i++) {
      const s = packed.getSplat(i)
      sumSqDist += s.center.distanceToSquared(mean)
    }
    const stdDev = Math.sqrt(sumSqDist / n)

    const maxDist = k * stdFactor * stdDev
    const maxDistSq = maxDist * maxDist

    let writeIdx = 0
    for (let i = 0; i < n; i++) {
      const splat = packed.getSplat(i)
      if (splat.center.distanceToSquared(mean) <= maxDistSq) {
        if (writeIdx !== i) {
          packed.setSplat(
            writeIdx,
            splat.center,
            splat.scales,
            splat.quaternion,
            splat.opacity,
            splat.color,
          )
        }
        this.idMap?.retain(writeIdx, i)
        writeIdx++
      }
    }

    const removed = n - writeIdx
    packed.numSplats = writeIdx
    this.idMap?.setLive(writeIdx)
    this.markSplatDirty()
    this.emitStateChange()
    return removed
  }

  cropBbox(min: THREE.Vector3, max: THREE.Vector3): number {
    const packed = this.splatMesh?.packedSplats
    if (!packed) return 0

    this.pushUndoSnapshot('Crop bounding box')

    const total = packed.numSplats
    let writeIdx = 0

    for (let i = 0; i < total; i++) {
      const splat = packed.getSplat(i)
      const c = splat.center
      if (
        c.x >= min.x && c.x <= max.x &&
        c.y >= min.y && c.y <= max.y &&
        c.z >= min.z && c.z <= max.z
      ) {
        if (writeIdx !== i) {
          packed.setSplat(
            writeIdx,
            splat.center,
            splat.scales,
            splat.quaternion,
            splat.opacity,
            splat.color,
          )
        }
        this.idMap?.retain(writeIdx, i)
        writeIdx++
      }
    }

    const removed = total - writeIdx
    packed.numSplats = writeIdx
    this.idMap?.setLive(writeIdx)
    this.markSplatDirty()
    this.emitStateChange()
    return removed
  }

  /* ---------------------------------------------------------------- */
  /*  ViewerHandle – Selection (v0.2)                                 */
  /* ---------------------------------------------------------------- */

  getSelectionIds(): Uint32Array {
    return Uint32Array.from(this.selection)
  }

  getSelectionCount(): number {
    return this.selection.size
  }

  /** Add or remove original IDs from the current selection. */
  updateSelection(ids: Iterable<number>, mode: 'add' | 'remove' = 'add'): number {
    for (const id of ids) {
      if (mode === 'add') this.selection.add(id)
      else this.selection.delete(id)
    }
    this.emitSelectionChange()
    return this.selection.size
  }

  clearSelection(): number {
    this.selection.clear()
    this.emitSelectionChange()
    return 0
  }

  invertSelection(): number {
    const next = new Set<number>()
    const live = this.idMap?.liveIds()
    if (live) {
      for (const id of live) if (!this.selection.has(id)) next.add(id)
    }
    this.selection = next
    this.emitSelectionChange()
    return this.selection.size
  }

  /**
   * Count + bbox of the current selection in BACKEND coordinates (mesh-local,
   * pre-flip) — matches the backend's selection_state so agent and human read
   * the same numbers.
   */
  getSelectionSummary(): { count: number; bbox: { min: number[]; max: number[] } | null } {
    const packed = this.splatMesh?.packedSplats
    if (this.selection.size === 0 || !packed || !this.idMap) {
      return { count: this.selection.size, bbox: null }
    }
    let minX = Infinity, minY = Infinity, minZ = Infinity
    let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity
    const n = packed.numSplats
    let found = 0
    for (let i = 0; i < n; i++) {
      if (!this.selection.has(this.idMap.idAt(i))) continue
      const c = packed.getSplat(i).center
      if (c.x < minX) minX = c.x; if (c.y < minY) minY = c.y; if (c.z < minZ) minZ = c.z
      if (c.x > maxX) maxX = c.x; if (c.y > maxY) maxY = c.y; if (c.z > maxZ) maxZ = c.z
      found++
    }
    if (found === 0) return { count: this.selection.size, bbox: null }
    return {
      count: this.selection.size,
      bbox: { min: [minX, minY, minZ], max: [maxX, maxY, maxZ] },
    }
  }

  /**
   * TIGHT core box in BACKEND coordinates (mesh-local, pre-flip) — the "good
   * cube" seed for the agent's crop proposal. Fits SOLID splats only (the junk
   * halo is mostly near-transparent, and on post-disaster captures it can be
   * >90% of the scene — a percentile box over everything just re-derives the
   * whole scene), then density-clusters away solid stragglers
   * (computeTightCoreBox). Null when no mesh.
   */
  getCoreBoundsBox(): { min: number[]; max: number[]; count: number } | null {
    const packed = this.splatMesh?.packedSplats
    if (!packed) return null
    const n = packed.numSplats
    if (n === 0) return null
    // Strided sample with the same 100k cap as sampleWorldPoints: the percentile
    // fit sorts three full-length arrays, so an unbounded pass would block the
    // UI thread for seconds on multi-million-splat scenes. The count is scaled
    // back by the stride — an estimate above 100k splats, exact below.
    const stride = Math.max(1, Math.floor(n / 100_000))
    const pts: Vec3[] = []
    const solid: Vec3[] = []
    const faint: Vec3[] = []
    for (let i = 0; i < n; i += stride) {
      const s = packed.getSplat(i)
      const p = { x: s.center.x, y: s.center.y, z: s.center.z }
      pts.push(p)
      if (s.opacity >= 0.3) solid.push(p)
      else if (s.opacity >= 0.03) faint.push(p)
    }
    // Opacity ladder: prefer solid structure; a scene stored with globally low
    // opacities falls back to non-near-transparent, then to everything.
    const minSample = Math.max(200, pts.length * 0.005)
    const fitPts = solid.length >= minSample
      ? solid
      : solid.length + faint.length >= minSample
        ? solid.concat(faint)
        : pts
    const box = computeTightCoreBox(fitPts)
    if (!box) return null
    const [minX, minY, minZ] = box.min
    const [maxX, maxY, maxZ] = box.max
    let sampledInside = 0
    for (const c of pts) {
      if (
        c.x >= minX && c.x <= maxX &&
        c.y >= minY && c.y <= maxY &&
        c.z >= minZ && c.z <= maxZ
      ) sampledInside++
    }
    return { min: box.min, max: box.max, count: Math.min(n, sampledInside * stride) }
  }

  /** Delete the selected splats locally. Returns the IDs that were deleted. */
  deleteSelection(): Uint32Array {
    const ids = this.getSelectionIds()
    if (ids.length === 0) return ids
    // Untint BEFORE the compaction snapshots the buffer, so the undo entry —
    // and the deleted splats themselves — carry their true colors, never a
    // frozen highlight.
    this.restoreSelectionTint()
    this.deleteByIds(ids)
    this.clearSelection()
    return ids
  }

  /** Keep only the selected splats locally. Returns the kept IDs. */
  keepSelection(): Uint32Array {
    const ids = this.getSelectionIds()
    if (ids.length === 0) return ids
    // Kept splats are the tinted ones; untint before the compaction so both the
    // survivors and the undo snapshot hold true colors.
    this.restoreSelectionTint()
    this.keepOnlyIds(ids)
    this.clearSelection()
    return ids
  }

  /**
   * Single tint driver: restore any prior tint, then re-apply for the current
   * (non-empty) selection. Called on EVERY selection change, so manual tools
   * and agent tools tint identically. Restore-then-apply keeps it idempotent —
   * a re-tint always reads true colors, never an already-tinted value.
   */
  private emitSelectionChange(): void {
    this.restoreSelectionTint()
    if (this.selection.size > 0) this.applySelectionTint()
    this.onSelectionChange?.(this.selection.size)
  }

  /**
   * Tint the currently-selected splats warm. Stores each splat's true color the
   * first time only (TintStore), then lerps toward the highlight and writes it
   * back with the same getSplat/setSplat pattern the delete path uses.
   */
  private applySelectionTint(): void {
    const packed = this.splatMesh?.packedSplats
    if (!packed || !this.idMap || this.selection.size === 0) return
    const n = packed.numSplats
    let touched = false
    for (let i = 0; i < n; i++) {
      const id = this.idMap.idAt(i)
      if (!this.selection.has(id)) continue
      const splat = packed.getSplat(i)
      const c = splat.color
      this.tint.remember(id, [c.r, c.g, c.b])
      const [r, g, b] = tintedColor(this.tint.original(id)!)
      splat.color.setRGB(r, g, b)
      packed.setSplat(i, splat.center, splat.scales, splat.quaternion, splat.opacity, splat.color)
      touched = true
    }
    if (touched) this.markColorsDirty()
  }

  /**
   * Write every remembered original color back to whatever packed index now
   * holds that original ID (robust to compaction), then clear the store. No-op
   * when nothing is tinted.
   */
  private restoreSelectionTint(): void {
    if (this.tint.size === 0) return
    const packed = this.splatMesh?.packedSplats
    if (!packed || !this.idMap) {
      this.tint.clear()
      return
    }
    const n = packed.numSplats
    for (let i = 0; i < n; i++) {
      const orig = this.tint.original(this.idMap.idAt(i))
      if (!orig) continue
      const splat = packed.getSplat(i)
      splat.color.setRGB(orig[0], orig[1], orig[2])
      packed.setSplat(i, splat.center, splat.scales, splat.quaternion, splat.opacity, splat.color)
    }
    this.tint.clear()
    this.markColorsDirty()
  }

  /**
   * GPU re-upload after an in-place COLOR-only write (selection tint). Unlike
   * markSplatDirty this deliberately does NOT bump the scene revision or
   * re-cache the framing core: a cosmetic recolor moves no geometry, so it must
   * not flag captured percepts stale or shift near/far.
   */
  private markColorsDirty(): void {
    if (!this.splatMesh?.packedSplats) return
    this.splatMesh.packedSplats.needsUpdate = true
    this.splatMesh.updateVersion()
  }

  /* ---- SDF dim-preview for sphere/box volume selection (KTD5) ---- */

  /**
   * Live non-destructive preview: splats inside the volume dim to ~25%.
   * The SplatEdit is parented to the SPLAT MESH so its coordinates are
   * mesh-local (= backend space) and inherit the Y-flip — preview and CPU
   * containment agree by construction. Never a substitute for the commit.
   */
  showSelectionPreview(shape: 'sphere' | 'box', center: number[], size: number[]): void {
    const mesh = this.splatMesh
    if (!mesh) return
    if (!this.sdfPreviewEdit) {
      const edit = new SplatEdit({ rgbaBlendMode: SplatEditRgbaBlendMode.MULTIPLY })
      const sdf = new SplatEditSdf({
        type: shape === 'sphere' ? SplatEditSdfType.SPHERE : SplatEditSdfType.BOX,
        opacity: 0.25,
        color: new THREE.Color(1.4, 1.4, 0.6),
      })
      edit.addSdf(sdf)
      edit.add(sdf)
      mesh.add(edit)
      this.sdfPreviewEdit = edit
      this.sdfPreviewSdf = sdf
    }
    const sdf = this.sdfPreviewSdf!
    sdf.type = shape === 'sphere' ? SplatEditSdfType.SPHERE : SplatEditSdfType.BOX
    sdf.position.set(center[0], center[1], center[2])
    if (shape === 'sphere') {
      sdf.radius = size[0]
      sdf.scale.set(1, 1, 1)
    } else {
      sdf.radius = 0
      sdf.scale.set(Math.max(size[0], 1e-4), Math.max(size[1], 1e-4), Math.max(size[2], 1e-4))
    }
  }

  clearSelectionPreview(): void {
    if (this.sdfPreviewEdit && this.splatMesh) {
      this.splatMesh.remove(this.sdfPreviewEdit)
    }
    this.sdfPreviewEdit = null
    this.sdfPreviewSdf = null
  }

  /* ---- Persistent proposal box (v0.5, agent-cleanup-proposals) ---- */
  // Amber/warm — the agent's parked review box (fix pass 2, IMPORTANT 1: own
  // channel, independent of the operator's crop-box tool below).
  private proposalBoxOverlay = new BoxOverlay(() => this.splatMesh, 0xffcc44, new THREE.Color(1.4, 1.4, 0.6))

  /* ---- Operator crop-box tool ---- */
  // Cyan/cool — visually distinct from the agent's amber proposal box so the
  // operator can tell the two channels apart at a glance.
  private cropBoxOverlay = new BoxOverlay(() => this.splatMesh, 0x44ccff, new THREE.Color(0.6, 1.4, 1.4))
  private cropGizmo: CropBoxGizmo | null = null
  private cropSample: Float32Array | null = null   // strided centers, backend coords
  private cropStride = 1
  private cropCount = 0

  /** Persistent SDF dim + crisp wireframe, parented to the splat mesh so both
   *  live in backend coords and appear in captures. Stays until cleared.
   *  Agent-only channel (see `bridge.ts`) — never touched by the crop-box
   *  tool, which drives its own `cropBoxOverlay` instance (IMPORTANT 1). */
  showProposalBox(min: number[], max: number[]): void {
    this.proposalBoxOverlay.show(min, max)
  }

  clearProposalBox(): void {
    this.proposalBoxOverlay.clear()
  }

  getProposalBox(): { min: number[]; max: number[] } | null {
    return this.proposalBoxOverlay.getState()
  }

  /* ---- Operator crop-box tool ---- */

  /** Start the crop-box tool. `seed` defaults to the tight core box. */
  beginCropBox(seed?: Box): void {
    const mesh = this.splatMesh
    if (!mesh) return
    const box = seed ?? this.getCoreBoundsBox() ?? null
    if (!box) return
    this.buildCropSample()
    if (!this.cropGizmo) {
      this.cropGizmo = new CropBoxGizmo({
        camera: this.camera,
        domElement: this.renderer.domElement,
        scene: this.scene,
        parent: mesh,
        setOrbitEnabled: (on) => { this.controls.enabled = on },
      })
      this.cropGizmo.onChange = (b) => {
        this.cropBoxOverlay.show(b.min, b.max)   // wireframe + SDF dim of the outside
        // cropSample can be null if buildCropSample() found nothing to sample
        // (MINOR 8 — no non-null assertion on a field endCropBox() nulls).
        this.cropCount = this.cropSample ? countInsideSampled(this.cropSample, b) * this.cropStride : 0
      }
    }
    this.cropGizmo.attach({ min: box.min as Box['min'], max: box.max as Box['max'] })
  }

  /** No-op when no crop-box session is active (IMPORTANT 4) — otherwise every
   *  tool switch (and first render) would clear the live crop-box preview. */
  endCropBox(): void {
    if (!this.cropGizmo || this.cropGizmo.getBox() === null) return
    this.cropGizmo.detach()
    this.cropBoxOverlay.clear()
    this.cropSample = null
    this.cropCount = 0
  }

  getCropBox(): Box | null {
    return this.cropGizmo?.getBox() ?? null
  }

  /** Approximate splat count inside the box, from the strided sample. */
  cropBoxCount(): number {
    return this.cropCount
  }

  /** Keep only splats inside the box. Returns the kept stable IDs (exact). */
  cropToBox(): Uint32Array {
    const box = this.getCropBox()
    const packed = this.splatMesh?.packedSplats
    if (!box || !packed || !this.idMap) return new Uint32Array(0)
    const keep: number[] = []
    for (let i = 0; i < packed.numSplats; i++) {
      const c = packed.getSplat(i).center
      // Shared predicate with countInsideSampled (IMPORTANT 6) — normalizes
      // internally, so an inverted box crops exactly what the readout showed.
      if (isInsideBox(c.x, c.y, c.z, box)) keep.push(this.idMap.idAt(i))
    }
    const ids = new Uint32Array(keep)
    // End the session BEFORE mutating (fix pass 2, MINOR 5): keepOnlyIds()
    // below runs through markSplatDirty() -> refreshCropSampleIfActive(),
    // which rebuilds the O(N) cropSample whenever the gizmo still reports a
    // box. Detaching first (endCropBox() clears the gizmo's box) makes that
    // refresh a no-op instead of doing a full rebuild this method immediately
    // throws away.
    this.endCropBox()
    // Skip the mutation (and its undo snapshot) when the box already contains
    // every alive splat, or contains nothing: keepOnlyIds would be a no-op
    // edit that still pushes a local history entry with no backend
    // counterpart. The next Undo would pop that entry (no visible change) and
    // still fire historyOp('undo'), rolling back the backend's PREVIOUS edit
    // instead (CRITICAL 2). Extracted to a named predicate (fix pass 2, TEST
    // GAP) and unit-tested directly — this is the guard that caused that bug.
    if (shouldCommitCrop(ids.length, packed.numSplats)) {
      this.keepOnlyIds(ids)
    }
    return ids
  }

  /** Strided centers for the live readout — an exact per-frame count is O(N)
   *  and unusable at 2M splats (same 100k cap as getCoreBoundsBox). */
  private buildCropSample(): void {
    const packed = this.splatMesh?.packedSplats
    if (!packed) return
    const n = packed.numSplats
    this.cropStride = Math.max(1, Math.floor(n / 100_000))
    const out: number[] = []
    for (let i = 0; i < n; i += this.cropStride) {
      const c = packed.getSplat(i).center
      out.push(c.x, c.y, c.z)
    }
    this.cropSample = new Float32Array(out)
  }

  /** Re-sample the crop-box readout after the splat buffer changes shape
   *  in place. Called from the single choke point every mutating path already
   *  runs through — `markSplatDirty()` (fix pass 2, IMPORTANT 2) — so undo(),
   *  cleanOpacity/removeOutliers/cropBbox/filterBy*, and compaction all keep
   *  the readout current, not just compaction. Without this, `cropSample`
   *  would keep stale centers/count from before the edit even though the mesh
   *  instance and gizmo session are unchanged. No-op when the tool isn't
   *  active, and cheap when it is (bounded to the same 100k sample cap), and
   *  never runs from the frame loop — only from these edit paths. */
  private refreshCropSampleIfActive(): void {
    if (!this.cropGizmo) return
    const box = this.cropGizmo.getBox()
    if (!box) return
    this.buildCropSample()
    this.cropCount = this.cropSample ? countInsideSampled(this.cropSample, box) * this.cropStride : 0
  }

  /* ---------------------------------------------------------------- */
  /*  ViewerHandle – Stable-ID editing (v0.2, KTD2/KTD3)              */
  /* ---------------------------------------------------------------- */

  /**
   * Adopt the backend's alive original-ID list after a backend-driven reload
   * (packed index i ↔ backend's i-th alive Gaussian). Without this, a reload
   * would reset IDs to 0..M-1 and diverge from the backend's ID space.
   */
  setIdMapFromIds(ids: ArrayLike<number>): void {
    this.idMap = new IdMap(ids)
    this.selection.clear()
    // The reloaded buffer is untinted and its ID space is redefined; drop stale
    // originals so the (now empty-selection) emitSelectionChange restore can't
    // write an old color onto a reused ID.
    this.tint.clear()
    this.emitSelectionChange()
  }

  /** Original splat IDs currently alive (what the backend edit path consumes). */
  getLiveIds(): Uint32Array {
    return this.idMap?.liveIds() ?? new Uint32Array(0)
  }

  /** Delete splats by ORIGINAL id. Returns the number removed. */
  deleteByIds(ids: Iterable<number>): number {
    return this.compactByIds(new Set(ids), /* keepListed */ false, 'Delete selection')
  }

  /** Keep only splats with the given ORIGINAL ids (delete the inverse). */
  keepOnlyIds(ids: Iterable<number>): number {
    return this.compactByIds(new Set(ids), /* keepListed */ true, 'Keep selection')
  }

  private compactByIds(idSet: Set<number>, keepListed: boolean, label: string): number {
    const packed = this.splatMesh?.packedSplats
    if (!packed || !this.idMap) return 0
    if (!keepListed && idSet.size === 0) return 0 // deleting nothing is a no-op

    this.pushUndoSnapshot(label)

    const total = packed.numSplats
    let writeIdx = 0
    for (let i = 0; i < total; i++) {
      const listed = idSet.has(this.idMap.idAt(i))
      if (listed === keepListed) {
        if (writeIdx !== i) {
          const splat = packed.getSplat(i)
          packed.setSplat(writeIdx, splat.center, splat.scales, splat.quaternion, splat.opacity, splat.color)
        }
        this.idMap.retain(writeIdx, i)
        writeIdx++
      }
    }

    const removed = total - writeIdx
    packed.numSplats = writeIdx
    this.idMap.setLive(writeIdx)
    this.markSplatDirty() // also refreshes the crop-box readout, see markSplatDirty()
    this.emitStateChange()
    return removed
  }

  /**
   * All live splat centers in WORLD space (matrixWorld applied — resolves the
   * COLMAP Y-flip) plus their parallel original IDs. Full pass, not strided:
   * selection containment needs every candidate.
   */
  getCentersWorld(): { centers: Float32Array; ids: Uint32Array } | null {
    const packed = this.splatMesh?.packedSplats
    const n = packed?.numSplats ?? 0
    if (!packed || n === 0 || !this.idMap) return null

    this.splatMesh!.updateMatrixWorld()
    const local = new Float32Array(n * 3)
    for (let i = 0; i < n; i++) {
      const c = packed.getSplat(i).center
      local[i * 3] = c.x
      local[i * 3 + 1] = c.y
      local[i * 3 + 2] = c.z
    }
    return {
      centers: transformPoints(local, this.splatMesh!.matrixWorld.elements),
      ids: this.idMap.liveIds(),
    }
  }

  /* ---------------------------------------------------------------- */
  /*  ViewerHandle – Advanced cleanup                                 */
  /* ---------------------------------------------------------------- */

  filterByScale(minScale?: number, maxScale?: number): number {
    const packed = this.splatMesh?.packedSplats
    if (!packed) return 0

    this.pushUndoSnapshot('Filter by scale')

    const total = packed.numSplats
    let writeIdx = 0

    for (let i = 0; i < total; i++) {
      const splat = packed.getSplat(i)
      const maxS = Math.max(splat.scales.x, splat.scales.y, splat.scales.z)
      const aboveMin = minScale === undefined || maxS >= minScale
      const belowMax = maxScale === undefined || maxS <= maxScale
      if (aboveMin && belowMax) {
        if (writeIdx !== i) {
          packed.setSplat(writeIdx, splat.center, splat.scales, splat.quaternion, splat.opacity, splat.color)
        }
        this.idMap?.retain(writeIdx, i)
        writeIdx++
      }
    }

    const removed = total - writeIdx
    packed.numSplats = writeIdx
    this.idMap?.setLive(writeIdx)
    this.markSplatDirty()
    this.emitStateChange()
    return removed
  }

  filterByColor(targetR: number, targetG: number, targetB: number, tolerance: number): number {
    const packed = this.splatMesh?.packedSplats
    if (!packed) return 0

    this.pushUndoSnapshot('Filter by color')

    // Convert target to HSL
    const targetHSL = { h: 0, s: 0, l: 0 }
    new THREE.Color(targetR, targetG, targetB).getHSL(targetHSL)

    const total = packed.numSplats
    let writeIdx = 0
    const splatHSL = { h: 0, s: 0, l: 0 }
    const tmpColor = new THREE.Color()

    for (let i = 0; i < total; i++) {
      const splat = packed.getSplat(i)
      tmpColor.copy(splat.color)
      tmpColor.getHSL(splatHSL)

      // Hue is circular: shortest angular distance
      let dh = Math.abs(splatHSL.h - targetHSL.h)
      if (dh > 0.5) dh = 1.0 - dh
      const ds = splatHSL.s - targetHSL.s
      const dl = splatHSL.l - targetHSL.l

      // Weighted HSL distance (hue weighted 2x)
      const dist = Math.sqrt(dh * dh * 4 + ds * ds + dl * dl)

      if (dist > tolerance) {
        // KEEP splats that do NOT match the target color
        if (writeIdx !== i) {
          packed.setSplat(writeIdx, splat.center, splat.scales, splat.quaternion, splat.opacity, splat.color)
        }
        this.idMap?.retain(writeIdx, i)
        writeIdx++
      }
    }

    const removed = total - writeIdx
    packed.numSplats = writeIdx
    this.idMap?.setLive(writeIdx)
    this.markSplatDirty()
    this.emitStateChange()
    return removed
  }

  filterByDensity(minNeighbors: number, radius: number): number {
    const packed = this.splatMesh?.packedSplats
    if (!packed || packed.numSplats === 0) return 0

    this.pushUndoSnapshot('Filter by density')

    const total = packed.numSplats
    const radiusSq = radius * radius
    const cellSize = radius

    // Phase 1: Extract positions into flat array (avoid double getSplat)
    const positions = new Float32Array(total * 3)
    for (let i = 0; i < total; i++) {
      const s = packed.getSplat(i)
      positions[i * 3] = s.center.x
      positions[i * 3 + 1] = s.center.y
      positions[i * 3 + 2] = s.center.z
    }

    // Phase 2: Build spatial hash (grid cells of size=radius)
    const grid = new Map<string, number[]>()
    for (let i = 0; i < total; i++) {
      const ix = Math.floor(positions[i * 3] / cellSize)
      const iy = Math.floor(positions[i * 3 + 1] / cellSize)
      const iz = Math.floor(positions[i * 3 + 2] / cellSize)
      const key = `${ix},${iy},${iz}`
      let bucket = grid.get(key)
      if (!bucket) {
        bucket = []
        grid.set(key, bucket)
      }
      bucket.push(i)
    }

    // Phase 3: Count neighbors per splat
    const keep = new Uint8Array(total) // 1 = keep
    for (let i = 0; i < total; i++) {
      const px = positions[i * 3]
      const py = positions[i * 3 + 1]
      const pz = positions[i * 3 + 2]
      const ix = Math.floor(px / cellSize)
      const iy = Math.floor(py / cellSize)
      const iz = Math.floor(pz / cellSize)

      let count = 0
      let done = false
      for (let dx = -1; dx <= 1 && !done; dx++) {
        for (let dy = -1; dy <= 1 && !done; dy++) {
          for (let dz = -1; dz <= 1 && !done; dz++) {
            const bucket = grid.get(`${ix + dx},${iy + dy},${iz + dz}`)
            if (!bucket) continue
            for (let b = 0; b < bucket.length; b++) {
              const j = bucket[b]
              if (j === i) continue
              const ddx = positions[j * 3] - px
              const ddy = positions[j * 3 + 1] - py
              const ddz = positions[j * 3 + 2] - pz
              if (ddx * ddx + ddy * ddy + ddz * ddz <= radiusSq) {
                count++
                if (count >= minNeighbors) { done = true; break }
              }
            }
          }
        }
      }
      if (count >= minNeighbors) keep[i] = 1
    }

    // Phase 4: Compact
    let writeIdx = 0
    for (let i = 0; i < total; i++) {
      if (keep[i]) {
        if (writeIdx !== i) {
          const splat = packed.getSplat(i)
          packed.setSplat(writeIdx, splat.center, splat.scales, splat.quaternion, splat.opacity, splat.color)
        }
        this.idMap?.retain(writeIdx, i)
        writeIdx++
      }
    }

    const removed = total - writeIdx
    packed.numSplats = writeIdx
    this.idMap?.setLive(writeIdx)
    this.markSplatDirty()
    this.emitStateChange()
    return removed
  }

  filterByHeight(minY?: number, maxY?: number): number {
    const packed = this.splatMesh?.packedSplats
    if (!packed) return 0

    this.pushUndoSnapshot('Filter by height')

    const total = packed.numSplats
    let writeIdx = 0

    for (let i = 0; i < total; i++) {
      const splat = packed.getSplat(i)
      const y = splat.center.y
      const aboveMin = minY === undefined || y >= minY
      const belowMax = maxY === undefined || y <= maxY
      if (aboveMin && belowMax) {
        if (writeIdx !== i) {
          packed.setSplat(writeIdx, splat.center, splat.scales, splat.quaternion, splat.opacity, splat.color)
        }
        this.idMap?.retain(writeIdx, i)
        writeIdx++
      }
    }

    const removed = total - writeIdx
    packed.numSplats = writeIdx
    this.idMap?.setLive(writeIdx)
    this.markSplatDirty()
    this.emitStateChange()
    return removed
  }

  /* ---------------------------------------------------------------- */
  /*  ViewerHandle – Analysis                                         */
  /* ---------------------------------------------------------------- */

  getSceneStats(): SceneStats | null {
    const packed = this.splatMesh?.packedSplats
    if (!packed || packed.numSplats === 0) return null

    const n = packed.numSplats

    let sumX = 0, sumY = 0, sumZ = 0
    let minX = Infinity, minY = Infinity, minZ = Infinity
    let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity

    const opacityHist = new Array<number>(10).fill(0)
    const scales = new Float32Array(n)

    // Color quantization: 12 hue bins x 4 lightness bins
    const colorBuckets = new Map<number, { r: number; g: number; b: number; count: number }>()
    const tmpHSL = { h: 0, s: 0, l: 0 }
    const tmpColor = new THREE.Color()

    for (let i = 0; i < n; i++) {
      const s = packed.getSplat(i)
      const cx = s.center.x, cy = s.center.y, cz = s.center.z
      sumX += cx; sumY += cy; sumZ += cz
      if (cx < minX) minX = cx; if (cy < minY) minY = cy; if (cz < minZ) minZ = cz
      if (cx > maxX) maxX = cx; if (cy > maxY) maxY = cy; if (cz > maxZ) maxZ = cz

      opacityHist[Math.min(Math.floor(s.opacity * 10), 9)]++
      scales[i] = Math.max(s.scales.x, s.scales.y, s.scales.z)

      tmpColor.copy(s.color)
      tmpColor.getHSL(tmpHSL)
      const bucketKey = Math.min(Math.floor(tmpHSL.h * 12), 11) * 4 + Math.min(Math.floor(tmpHSL.l * 4), 3)
      const existing = colorBuckets.get(bucketKey)
      if (existing) {
        existing.r = (existing.r * existing.count + s.color.r) / (existing.count + 1)
        existing.g = (existing.g * existing.count + s.color.g) / (existing.count + 1)
        existing.b = (existing.b * existing.count + s.color.b) / (existing.count + 1)
        existing.count++
      } else {
        colorBuckets.set(bucketKey, { r: s.color.r, g: s.color.g, b: s.color.b, count: 1 })
      }
    }

    const meanX = sumX / n, meanY = sumY / n, meanZ = sumZ / n

    // Std deviation
    let varX = 0, varY = 0, varZ = 0
    for (let i = 0; i < n; i++) {
      const s = packed.getSplat(i)
      const dx = s.center.x - meanX, dy = s.center.y - meanY, dz = s.center.z - meanZ
      varX += dx * dx; varY += dy * dy; varZ += dz * dz
    }

    // Scale histogram (log10)
    let minLogScale = Infinity, maxLogScale = -Infinity
    for (let i = 0; i < n; i++) {
      if (scales[i] > 0) {
        const ls = Math.log10(scales[i])
        if (ls < minLogScale) minLogScale = ls
        if (ls > maxLogScale) maxLogScale = ls
      }
    }
    const scaleRange = maxLogScale - minLogScale || 1
    const scaleBuckets = new Array<number>(10).fill(0)
    for (let i = 0; i < n; i++) {
      if (scales[i] > 0) {
        const ls = Math.log10(scales[i])
        scaleBuckets[Math.min(Math.floor(((ls - minLogScale) / scaleRange) * 10), 9)]++
      }
    }

    // Top 5 dominant colors
    const colorEntries = Array.from(colorBuckets.values())
    colorEntries.sort((a, b) => b.count - a.count)

    // Estimated density radius from bbox diagonal
    const diagonal = Math.sqrt(
      (maxX - minX) ** 2 + (maxY - minY) ** 2 + (maxZ - minZ) ** 2,
    )

    return {
      count: n,
      bbox: { min: { x: minX, y: minY, z: minZ }, max: { x: maxX, y: maxY, z: maxZ } },
      meanPosition: { x: meanX, y: meanY, z: meanZ },
      stdPosition: { x: Math.sqrt(varX / n), y: Math.sqrt(varY / n), z: Math.sqrt(varZ / n) },
      opacityHistogram: opacityHist,
      scaleHistogram: { buckets: scaleBuckets, minLog: minLogScale, maxLog: maxLogScale },
      dominantColors: colorEntries.slice(0, 5),
      estimatedDensityRadius: diagonal / 50,
    }
  }

  /* ---------------------------------------------------------------- */
  /*  ViewerHandle – Undo                                             */
  /* ---------------------------------------------------------------- */

  undo(): boolean {
    const entry = this.undoStack.pop()
    if (!entry) return false

    const packed = this.splatMesh?.packedSplats
    if (!packed) return false

    // Restore raw packed data
    if (packed.packedArray) {
      packed.packedArray.set(entry.data)
    }
    packed.numSplats = entry.numSplats
    // ID map restores with the buffer — a stale map would make later
    // selections target the wrong splats (undo symmetry, KTD3).
    if (entry.idMapSnap && this.idMap) {
      this.idMap.restore(entry.idMapSnap)
    }
    this.markSplatDirty()
    this.emitStateChange()
    return true
  }

  canUndo(): boolean {
    return this.undoStack.length > 0
  }

  getUndoStackLabels(): string[] {
    return this.undoStack.map((e) => e.label)
  }

  /* ---------------------------------------------------------------- */
  /*  Private helpers                                                 */
  /* ---------------------------------------------------------------- */

  private cancelCurrentTween(): void {
    if (this.cancelTween) {
      this.cancelTween()
      this.cancelTween = null
    }
  }

  private disposeSplatMesh(): void {
    if (this.splatMesh) {
      // The crop gizmo's box proxy is parented to `splatMesh` (CRITICAL 1):
      // caching the gizmo across a mesh swap would re-parent `attach()` onto
      // a disposed, scene-detached mesh next time the tool opens, so its
      // matrixWorld would never be traversed and the box would render at a
      // stale transform. Dispose it here and null the field — the next
      // beginCropBox() builds a fresh one against the new mesh.
      this.cropGizmo?.dispose()
      this.cropGizmo = null
      this.cropSample = null
      this.cropCount = 0
      this.clearSelectionPreview()
      this.clearProposalBox()
      // Both overlay channels are parented to THIS mesh (IMPORTANT 1) — clear
      // the crop-box one too, or it would keep a stale wireframe/SDF alive
      // referencing an object about to be disposed.
      this.cropBoxOverlay.clear()
      // Drop remembered tint colors — they belong to the buffer being torn
      // down; a fresh scene reuses the same original-ID space.
      this.tint.clear()
      this.scene.remove(this.splatMesh)
      this.splatMesh.dispose()
      this.splatMesh = null
    }
  }

  /**
   * Strided sample of splat centers, transformed into world space.
   *
   * packedSplats centers are mesh-local and the mesh carries a Y-flip
   * (rotation.x = π); the framing helpers assume world up = +Y, so we resolve
   * the transform here. Strided so multi-million-splat scenes sample instantly.
   * Returns null when there is nothing to sample.
   */
  private sampleWorldPoints(): Vec3[] | null {
    const packed = this.splatMesh?.packedSplats
    const n = packed?.numSplats ?? 0
    if (!packed || n === 0) return null

    this.splatMesh!.updateMatrixWorld()
    const m = this.splatMesh!.matrixWorld
    const stride = Math.max(1, Math.floor(n / 100_000))
    const v = new THREE.Vector3()
    const pts: Vec3[] = []
    for (let i = 0; i < n; i += stride) {
      const c = packed.getSplat(i).center
      v.set(c.x, c.y, c.z).applyMatrix4(m)
      pts.push({ x: v.x, y: v.y, z: v.z })
    }
    return pts
  }

  /**
   * Robust core center + radius for view presets. Falls back to the raw
   * bounding box when there are no packed splats to sample.
   */
  private coreBounds(): { center: [number, number, number]; radius: number } | null {
    const pts = this.sampleWorldPoints()
    if (pts) {
      const bounds = computeCoreBounds(pts)
      if (bounds) return bounds
    }
    const bbox = this.getBoundingBox()
    if (!bbox) return null
    const c = bbox.getCenter(new THREE.Vector3())
    return { center: [c.x, c.y, c.z], radius: bbox.getSize(new THREE.Vector3()).length() * 0.6 || 3 }
  }

  /**
   * After loading, place the camera at an aspect-aware default pose: a
   * non-grazing elevation for wide/flat scenes, framed on the robust core so
   * far floaters don't shrink or tilt the view. See framing.ts.
   */
  private frameScene(): void {
    this.cacheSceneCore()  // seed the frustum-tracking cache for this scene
    const pts = this.sampleWorldPoints()
    if (pts) {
      const framing = computeFraming(pts, this.camera.fov, this.camera.aspect || 1)
      if (framing) {
        this.camera.position.set(framing.position[0], framing.position[1], framing.position[2])
        this.controls.target.set(framing.target[0], framing.target[1], framing.target[2])
        this.controls.update()
        // Derive near/far from the framed distance + scene radius so large
        // outdoor scenes keep usable depth precision and aren't clipped.
        const radius = computeCoreBounds(pts)?.radius ?? 0
        this.updateNearFar(radius)
        return
      }
    }
    // Fallback: frame the bounding box.
    const bbox = this.getBoundingBox()
    if (!bbox) return
    const center = bbox.getCenter(new THREE.Vector3())
    const radius = bbox.getSize(new THREE.Vector3()).length() * 0.6 || 3
    this.camera.position.set(center.x + radius * 0.6, center.y + radius * 0.6, center.z + radius)
    this.controls.target.copy(center)
    this.controls.update()
    this.updateNearFar(radius)
  }

  /**
   * Recompute camera near/far from the current camera-to-target distance and
   * the given scene radius, then refresh the projection matrix. See BUG C in
   * framing.ts (nearFarForDistance).
   */
  private updateNearFar(sceneRadius: number): void {
    const distance = this.camera.position.distanceTo(this.controls.target)
    const { near, far } = nearFarForDistance(distance, sceneRadius)
    this.camera.near = near
    this.camera.far = far
    this.camera.updateProjectionMatrix()
  }

  /**
   * Cache the world-space scene core (center + radius) so `refreshNearFar` can
   * track the frustum cheaply every frame. Called on load/frame and after every
   * edit (via markSplatDirty).
   */
  private cacheSceneCore(): void {
    const core = this.coreBounds()
    if (!core) return
    this.sceneCenter.set(core.center[0], core.center[1], core.center[2])
    this.sceneRadius = core.radius
  }

  /**
   * Keep the frustum bracketing the scene as the camera moves. The agent's
   * camera flights leave the load pose far behind; without this the splat
   * crosses the STALE far plane (near/far were only set once, on load) and gets
   * clipped — the "blank / glitch" on agent navigation. Cheap: one distance +
   * a matrix rebuild only when the planes actually change. Based on distance to
   * the scene CENTER (not the orbit target, which drifts in fly mode).
   */
  private refreshNearFar(): void {
    if (this.sceneRadius <= 0) return
    const dist = this.camera.position.distanceTo(this.sceneCenter)
    const { near, far } = nearFarForDistance(dist, this.sceneRadius)
    if (near !== this.camera.near || far !== this.camera.far) {
      this.camera.near = near
      this.camera.far = far
      this.camera.updateProjectionMatrix()
    }
  }

  /**
   * Push a copy of the current PackedSplats data onto the undo stack.
   *
   * The buffer may be TINTED right now — filters (cleanOpacity/cropBbox/
   * filterBy*) run without touching the selection, so the operator's warm
   * highlight is still baked into the packed colors. Snapshotting those tinted
   * bytes would poison the undo entry: a later deselect empties the TintStore,
   * then undo() writes the tinted snapshot back with nothing left to un-tint,
   * and the highlight locks in as the new "original" (permanent corruption).
   * So restore true colors BEFORE slicing, then re-apply so the live highlight
   * doesn't silently vanish mid-filter. Guarded by `wasTinted` — the delete/
   * keep paths already restored (store empty), so this is a no-op for them and
   * never re-tints splats they are about to compact away.
   */
  private pushUndoSnapshot(label: string): void {
    const packed = this.splatMesh?.packedSplats
    if (!packed?.packedArray) return

    const wasTinted = this.tint.size > 0
    if (wasTinted) this.restoreSelectionTint()

    const splatDataLen = packed.numSplats * INTS_PER_SPLAT
    const snapshot = packed.packedArray.slice(0, splatDataLen)

    this.undoStack.push({
      label,
      data: snapshot,
      numSplats: packed.numSplats,
      idMapSnap: this.idMap?.snapshot() ?? null,
    })

    if (wasTinted && this.selection.size > 0) this.applySelectionTint()
  }

  /**
   * Mark the SplatMesh as needing a GPU re-upload after in-place edits.
   *
   * Single choke point for every path that changes the alive-splat count in
   * place — cleanOpacity, removeOutliers, cropBbox, compactByIds (delete/keep/
   * crop), filterByScale/Color/Density/Height, and undo() (fix pass 2,
   * IMPORTANT 2: verified each of those calls this method). Also refreshing
   * the crop-box readout here means an operator with the tool open never sees
   * a stale `~N inside` count after ANY of those paths — not just compaction.
   */
  private markSplatDirty(): void {
    if (!this.splatMesh?.packedSplats) return
    this.splatMesh.packedSplats.needsUpdate = true
    this.splatMesh.updateVersion()
    this.revision++  // percepts taken before this edit are now stale
    // Edits can move the scene's extent; refresh the cached core so near/far
    // tracking and agent framing stay accurate.
    this.cacheSceneCore()
    this.refreshCropSampleIfActive()
  }

  /** Monotonic scene revision (bumps on every edit). Tags captured percepts. */
  getSceneRevision(): number {
    return this.revision
  }

  // The operator's view at the start of an agent run — the home the agent can
  // always return to (reframe). Captured on run start; null before the first run.
  private homePose: { position: THREE.Vector3; target: THREE.Vector3 } | null = null

  setHomePose(pose: { position: THREE.Vector3; target: THREE.Vector3 }): void {
    this.homePose = { position: pose.position.clone(), target: pose.target.clone() }
  }

  getHomePose(): { position: THREE.Vector3; target: THREE.Vector3 } | null {
    if (!this.homePose) return null
    return { position: this.homePose.position.clone(), target: this.homePose.target.clone() }
  }
}
