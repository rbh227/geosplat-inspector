/**
 * Frontend tool executors — the runs_on:"frontend" tools (ARCHITECTURE.md §6.5).
 *
 * Camera moves are AWAITED and paced; each completed move drops a breadcrumb on
 * the trail. Captures go through the R1-hardened PNG path.
 */
import * as THREE from 'three'
import type { MoveDirection, PerceptTag, RendererBridge, RotateDirection, ToolResult } from './types.ts'
import { animateOrbit, animateTo, clampToCore, coreInView, poseForBox, resolveAimPoint, rotateAround, sceneCoverage, sleep, surveyPoses, toRenderSpace } from './camera.ts'
import { capturePNG, dataUrlToBase64 } from './capture.ts'
import { adjustBox, projectBoxToScreen, viewBasisFromCamera } from './proposalBox.ts'
import type { AdjustOpts, Box } from './proposalBox.ts'
import * as subjectPreview from './subjectPreview.ts'
import type { Overlay } from './overlay.ts'
// Shared pure selection math — the SAME module the manual SelectionOverlay
// uses, so agent and human selections resolve identically (R13 parity).
import {
  composeMatrices,
  projectToScreen,
  selectInBox,
  selectInCircle,
  selectInPolygon,
  selectInSphere,
} from '../../../src/viewer/selection.ts'

const MOVE_DIRECTIONS = new Set<MoveDirection>(['forward', 'back', 'left', 'right', 'up', 'down'])
const MAX_MOVE_MS = 8000

export class FrontendExecutors {
  constructor(private bridge: RendererBridge, private overlay: Overlay) {}

  // ── v0.2 editor tools: the agent drives the SAME action layer the manual
  // tools use (bridge selection state + shared math) — R13 parity ──

  /** Answer a backend get_selection pull with the current stable IDs. */
  async get_selection(): Promise<Record<string, unknown>> {
    const ids = this.bridge.getSelectionIds()
    return { ok: true, ids: Array.from(ids), count: ids.length }
  }

  /** Project all live centers to renderer pixel space (screen-space tools). */
  private projectCenters() {
    const cw = this.bridge.getCentersWorld()
    if (!cw) return null
    const cam = this.bridge.getCamera()
    cam.updateMatrixWorld()
    const el = this.bridge.getRenderer().domElement
    const w = el.clientWidth || el.width
    const h = el.clientHeight || el.height
    const viewProj = composeMatrices(
      Array.from(cam.projectionMatrix.elements),
      Array.from(cam.matrixWorldInverse.elements),
    )
    return { ...projectToScreen(cw.centers, viewProj, w, h), cw, w, h }
  }

  private commitHits(hits: Uint32Array, ids: Uint32Array, mode: 'add' | 'remove'): Record<string, unknown> {
    const selected = new Array<number>(hits.length)
    for (let i = 0; i < hits.length; i++) selected[i] = ids[hits[i]]
    this.bridge.updateSelection(selected, mode)
    const summary = this.bridge.getSelectionSummary()
    return { ok: true, count: summary.count, bbox: summary.bbox, matched: hits.length }
  }

  async runSelectionTool(tool: string, args: Record<string, unknown>): Promise<Record<string, unknown>> {
    const mode: 'add' | 'remove' = args.mode === 'remove' ? 'remove' : 'add'

    if (tool === 'clear_selection') {
      this.bridge.clearSelection()
      return { ok: true, count: 0 }
    }
    if (tool === 'invert_selection') {
      const count = this.bridge.invertSelection()
      return { ok: true, count, bbox: this.bridge.getSelectionSummary().bbox }
    }
    if (tool === 'get_selection_state') {
      const summary = this.bridge.getSelectionSummary()
      return { ok: true, count: summary.count, bbox: summary.bbox }
    }

    // v0.7 — controller tint: exact stable ids (CleanupController-dispatched,
    // never offered to the model)
    if (tool === 'select_by_ids') {
      const ids = args.ids as number[]
      if (!Array.isArray(ids)) return { ok: false, error: 'ids must be an array' }
      if (args.mode === 'replace') this.bridge.clearSelection()
      this.bridge.updateSelection(ids, args.mode === 'remove' ? 'remove' : 'add')
      const summary = this.bridge.getSelectionSummary()
      return { ok: true, count: summary.count, bbox: summary.bbox }
    }

    // v0.8 — subject lock-on preview (CleanupController-dispatched only).
    // With outside_ids it installs the nested levels (complement form) and
    // tints one; a level-only call is the controller nudging the slider.
    if (tool === 'show_subject_preview') {
      if (Array.isArray(args.outside_ids)) {
        const count = subjectPreview.setSubject(this.bridge, {
          outsideIds: args.outside_ids as number[],
          deltas: (args.deltas as number[][]) ?? [],
          counts: (args.counts as number[]) ?? [],
          level: Number(args.level ?? 0),
        })
        await sleep(350)  // paced so the operator sees the highlight land (SC2)
        return { ok: true, count }
      }
      const count = subjectPreview.applyLevel(this.bridge, Number(args.level ?? 0))
      await sleep(350)
      return { ok: true, count }
    }

    // v0.5 — proposal / good-cube surface
    if (tool === 'get_core_bounds') {
      const box = this.bridge.getCoreBoundsBox()
      return box ? { ok: true, ...box } : { ok: false, error: 'no scene loaded' }
    }
    if (tool === 'show_box_preview') {
      const mn = args.min as number[], mx = args.max as number[]
      if (!Array.isArray(mn) || !Array.isArray(mx) || mn.length !== 3 || mx.length !== 3) {
        return { ok: false, error: 'min/max must be [x,y,z]' }
      }
      this.bridge.showProposalBox(mn, mx)
      await sleep(350)  // paced so the operator sees it land (SC2)
      return { ok: true, min: mn, max: mx }
    }
    if (tool === 'adjust_box_preview') {
      const cur = this.bridge.getProposalBox()
      if (!cur) return { ok: false, error: 'no box preview active — call show_box_preview first' }
      const basis = viewBasisFromCamera(this.bridge.getCamera())
      const next = adjustBox(
        { min: cur.min as Box['min'], max: cur.max as Box['max'] },
        basis,
        args as AdjustOpts,
      )
      this.bridge.showProposalBox(next.min, next.max)
      await sleep(350)
      return { ok: true, min: next.min, max: next.max }
    }

    // World-space volume tools (backend coords → render space via the flip).
    // The SDF preview flashes before the commit so the human can SEE what the
    // agent is about to select (R13/SC2) — same visual the manual tools show.
    if (tool === 'select_by_sphere' || tool === 'select_by_box') {
      const cw = this.bridge.getCentersWorld()
      if (!cw) return { ok: false, error: 'no scene loaded' }
      if (tool === 'select_by_sphere') {
        const r = Number(args.radius)
        this.bridge.showSelectionPreview('sphere', args.center as number[], [r])
      } else {
        const mn = args.min as number[]
        const mx = args.max as number[]
        const center = [(mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, (mn[2] + mx[2]) / 2]
        const half = [(mx[0] - mn[0]) / 2, (mx[1] - mn[1]) / 2, (mx[2] - mn[2]) / 2]
        this.bridge.showSelectionPreview('box', center, half)
      }
      await sleep(500)
      this.bridge.clearSelectionPreview()
      let hits: Uint32Array
      if (tool === 'select_by_sphere') {
        const c = toRenderSpace(args.center as number[])
        hits = selectInSphere(cw.centers, [c.x, c.y, c.z], Number(args.radius))
      } else {
        // flipping corners can swap per-axis min/max — rebuild the box
        const a = toRenderSpace(args.min as number[])
        const b = toRenderSpace(args.max as number[])
        const min = [Math.min(a.x, b.x), Math.min(a.y, b.y), Math.min(a.z, b.z)]
        const max = [Math.max(a.x, b.x), Math.max(a.y, b.y), Math.max(a.z, b.z)]
        hits = selectInBox(cw.centers, min, max)
      }
      return this.commitHits(hits, cw.ids, mode)
    }

    // Screen-space tools (viewport-normalized coords per the tool contract).
    // Paced at human-visible speed so the watching operator can follow (SC2).
    if (tool === 'select_by_brush' || tool === 'select_by_lasso' || tool === 'select_by_polygon') {
      await sleep(350)
      const proj = this.projectCenters()
      if (!proj) return { ok: false, error: 'no scene loaded' }
      let hits: Uint32Array
      if (tool === 'select_by_brush') {
        const [u, v] = args.center_xy as [number, number]
        hits = selectInCircle(proj.xy, proj.visible, u * proj.w, v * proj.h, Number(args.radius) * proj.h)
      } else {
        const pts = args.points_xy as Array<[number, number]>
        if (!Array.isArray(pts) || pts.length < 3) {
          return { ok: false, error: 'points_xy needs at least 3 [u,v] points' }
        }
        const polygon: number[] = []
        for (const [u, v] of pts) polygon.push(u * proj.w, v * proj.h)
        hits = selectInPolygon(proj.xy, proj.visible, polygon)
      }
      return this.commitHits(hits, proj.cw.ids, mode)
    }

    return { ok: false, error: `unknown selection tool ${tool}` }
  }

  /** Hold a fly-mode movement input — the pad lights up because this is the
   *  same setMovementInput the keyboard and on-screen pad call (R13/SC2). */
  async move_camera(args: { direction: string; duration_ms: number }): Promise<Record<string, unknown>> {
    const direction = args.direction as MoveDirection
    if (!MOVE_DIRECTIONS.has(direction)) {
      return { ok: false, error: `unknown direction ${args.direction}` }
    }
    const holdMs = Math.max(0, Math.min(Number(args.duration_ms) || 0, MAX_MOVE_MS))
    this.bridge.setMovementInput(direction, true)
    try {
      await sleep(holdMs)
    } finally {
      this.bridge.setMovementInput(direction, false)
    }
    return { ok: true, held_ms: holdMs }
  }

  /** Hold a rotate-pad look input (yaw/pitch) — the SAME setRotationInput the
   *  on-screen rotate pad calls, so the pad lights for the agent too (R8). The
   *  tool speaks in operator terms (left/right/up/down); we map to the pad's
   *  yaw/pitch vocabulary. Relative, button-only — no coordinates. */
  async turn(args: { direction: string; duration_ms: number }): Promise<Record<string, unknown>> {
    const MAP: Record<string, RotateDirection> = {
      left: 'yaw-left', right: 'yaw-right', up: 'pitch-up', down: 'pitch-down',
    }
    const dir = MAP[args.direction as string]
    if (!dir) return { ok: false, error: `unknown turn direction ${args.direction}` }
    const holdMs = Math.max(0, Math.min(Number(args.duration_ms) || 0, MAX_MOVE_MS))
    this.bridge.setRotationInput(dir, true)
    try {
      await sleep(holdMs)
    } finally {
      this.bridge.setRotationInput(dir, false)
    }
    return { ok: true, held_ms: holdMs }
  }

  /** Record where the camera ended up after a move. */
  private breadcrumb(): void {
    this.overlay.pushTrailPoint(this.bridge.getCameraPose().position)
  }

  /** World-space aim point with the origin-default backstop (see camera.ts). */
  private resolveAimPoint(raw: number[] | undefined): THREE.Vector3 {
    return resolveAimPoint(raw, this.bridge.getSceneCore())
  }

  async look_at(args: { target: number[]; duration_ms?: number }): Promise<ToolResult> {
    const { position } = this.bridge.getCameraPose()
    await animateTo(this.bridge, position.clone(), this.resolveAimPoint(args.target), args.duration_ms)
    this.breadcrumb()
    return { ok: true }
  }

  async set_view(args: { position: number[]; target: number[]; duration_ms?: number }): Promise<ToolResult> {
    await animateTo(this.bridge, toRenderSpace(args.position), toRenderSpace(args.target), args.duration_ms)
    this.breadcrumb()
    return { ok: true }
  }

  async orbit(args: { center: number[]; deg: number; axis: 'x' | 'y' | 'z'; duration_ms?: number }): Promise<ToolResult> {
    const center = this.resolveAimPoint(args.center)
    await animateOrbit(this.bridge, center, args.axis, args.deg, args.duration_ms)
    this.breadcrumb()
    return { ok: true }
  }

  async dolly(args: { distance: number; duration_ms?: number }): Promise<ToolResult> {
    const { position, target } = this.bridge.getCameraPose()
    const dir = position.clone().sub(target)
    const len = dir.length() || 1
    dir.normalize()
    // positive distance = move toward target (in), negative = out
    const newLen = Math.max(0.05, len - args.distance)
    const rawTo = target.clone().add(dir.multiplyScalar(newLen))
    // App-owned safety limit: never zoom past a sane band around the scene core.
    const to = clampToCore(rawTo, this.bridge.getSceneCore())
    await animateTo(this.bridge, to, target.clone(), args.duration_ms)
    this.breadcrumb()
    return { ok: true }
  }

  async frame_object(args: { bbox: { min: number[]; max: number[] }; duration_ms?: number }): Promise<ToolResult> {
    // Flipping each corner can swap which is min vs max per-axis, so build the
    // box from the two flipped corners rather than passing them as (min, max).
    const box = new THREE.Box3().setFromPoints([
      toRenderSpace(args.bbox.min),
      toRenderSpace(args.bbox.max),
    ])
    const pose = poseForBox(this.bridge, box)
    await animateTo(this.bridge, pose.position, pose.target, args.duration_ms)
    this.breadcrumb()
    return { ok: true }
  }

  async reset_view(_args: Record<string, never>): Promise<ToolResult> {
    void _args
    // Prefer the world-space scene core: getBoundingBox() is mesh-local (Y/Z
    // flipped), so its center is mirrored for any off-origin scene and would
    // frame empty space. Fall back to the local bbox, then a fixed default.
    const core = this.bridge.getSceneCore()
    if (core) {
      const c = new THREE.Vector3(core.center[0], core.center[1], core.center[2])
      const box = new THREE.Box3().setFromCenterAndSize(
        c,
        new THREE.Vector3(core.radius * 2, core.radius * 2, core.radius * 2),
      )
      const pose = poseForBox(this.bridge, box)
      await animateTo(this.bridge, pose.position, pose.target)
    } else {
      const box = this.bridge.getBoundingBox()
      if (box) {
        const pose = poseForBox(this.bridge, box)
        await animateTo(this.bridge, pose.position, pose.target)
      } else {
        await animateTo(this.bridge, new THREE.Vector3(0, 1.5, 3), new THREE.Vector3(0, 0, 0))
      }
    }
    this.breadcrumb()
    return { ok: true }
  }

  /** Return the camera to the operator's start-of-run view (the home pose the
   *  app snapshotted). App-owned recovery — the model calls it when it's lost or
   *  badly framed; no coordinates involved. Falls back to framing the detected
   *  core if there is no home pose. */
  async reframe(_args: Record<string, never>): Promise<ToolResult> {
    void _args
    const home = this.bridge.getHomePose()
    if (home) {
      await animateTo(this.bridge, home.position.clone(), home.target.clone())
    } else {
      const core = this.bridge.getSceneCore()
      if (core) {
        const c = new THREE.Vector3(core.center[0], core.center[1], core.center[2])
        const box = new THREE.Box3().setFromCenterAndSize(
          c,
          new THREE.Vector3(core.radius * 2, core.radius * 2, core.radius * 2),
        )
        const pose = poseForBox(this.bridge, box)
        await animateTo(this.bridge, pose.position, pose.target)
      }
    }
    this.breadcrumb()
    return { ok: true }
  }

  async scan_pause(args: { ms: number }): Promise<ToolResult> {
    await sleep(args.ms)
    return { ok: true }
  }

  /** Clear the breadcrumb trail — routed as a camera_move (dispatch.py maps it). */
  async reset_trail(_args: Record<string, never>): Promise<ToolResult> {
    void _args
    this.overlay.resetTrail()
    return { ok: true }
  }

  async capture_frame(): Promise<ToolResult> {
    // Capture first, THEN read the pose/revision, so the tag matches exactly the
    // frame that was rendered (Codex boundary — every percept tied to state).
    const png_base64 = dataUrlToBase64(await capturePNG(this.bridge))
    const { position, target } = this.bridge.getCameraPose()
    const cam = this.bridge.getCamera()
    const coverage = sceneCoverage(position.clone(), cam.fov, this.bridge.getSceneCore())
    const percept: PerceptTag = {
      position: [position.x, position.y, position.z],
      target: [target.x, target.y, target.z],
      revision: this.bridge.getSceneRevision(),
      coverage: Math.round(coverage * 100) / 100,
      in_view: coreInView(cam, this.bridge.getSceneCore()),
    }
    // When a crop-proposal box is live, tag the capture with its projected
    // footprint — the box becomes the model's on-screen ruler (deterministic,
    // through the same camera matrices the screen-space selection tools use).
    const pbox = this.bridge.getProposalBox()
    if (pbox) {
      cam.updateMatrixWorld()
      const el = this.bridge.getRenderer().domElement
      const w = el.clientWidth || el.width
      const h = el.clientHeight || el.height
      const viewProj = composeMatrices(
        Array.from(cam.projectionMatrix.elements),
        Array.from(cam.matrixWorldInverse.elements),
      )
      const bs = projectBoxToScreen({ min: pbox.min, max: pbox.max } as Box, viewProj, w, h)
      if (bs) percept.box_screen = bs
    }
    return { png_base64, percept }
  }

  /** App-owned analyst survey (spec 2026-08-03): capture the operator's view,
   *  then fly framed top-down + oblique poses and capture each. The model
   *  never calls this — the agent loop dispatches it before the first model
   *  turn of an Understand run. `if_revision_not` lets the loop skip the
   *  flight when the scene hasn't changed since the stored survey. */
  async survey_capture(args: { if_revision_not?: number; grid?: boolean }): Promise<ToolResult> {
    const revision = this.bridge.getSceneRevision()
    if (args.if_revision_not !== undefined && args.if_revision_not === revision) {
      return { unchanged: true, revision }
    }
    const frames_base64: string[] = []
    const labels: string[] = []
    // v0.7 — one render-space camera pose per frame, index-aligned with
    // frames_base64: the cleanup controller reprojects grid marks through it.
    const poses: Array<{ position: number[]; target: number[]; fov: number; aspect: number }> = []
    const grid = args.grid === true
    const snapPose = () => {
      const { position, target } = this.bridge.getCameraPose()
      const cam = this.bridge.getCamera()
      const el = this.bridge.getRenderer().domElement
      poses.push({
        position: [position.x, position.y, position.z],
        target: [target.x, target.y, target.z],
        fov: cam.fov,
        aspect: (el.clientWidth || el.width) / ((el.clientHeight || el.height) || 1),
      })
    }

    // Frame 1 — the operator's current view ("the angle I just put in").
    frames_base64.push(dataUrlToBase64(await capturePNG(this.bridge, { grid })))
    labels.push("operator's view")
    snapPose()

    const core = this.bridge.getSceneCore()
    if (core && core.radius > 0) {
      for (const pose of surveyPoses(this.bridge.getCamera(), core)) {
        await animateTo(this.bridge, pose.position, pose.target, 600)
        await sleep(250) // let Spark's async depth-sort settle at the new pose
        frames_base64.push(dataUrlToBase64(await capturePNG(this.bridge, { grid })))
        labels.push(pose.label)
        snapPose()
      }
    }
    this.breadcrumb()
    return { frames_base64, labels, poses, revision }
  }

  async capture_orbit(args: { center: number[]; n: number; radius?: number }): Promise<ToolResult> {
    const center = this.resolveAimPoint(args.center)
    const pose0 = this.bridge.getCameraPose()
    const radius = args.radius ?? pose0.position.clone().sub(center).length()
    const start = pose0.position.clone().sub(center)
    if (start.lengthSq() < 1e-8) start.set(0, 0, radius)
    start.normalize().multiplyScalar(radius)

    const pngs: string[] = []
    const n = Math.max(1, Math.floor(args.n))
    for (let i = 0; i < n; i++) {
      const offset = rotateAround(center.clone().add(start), center, 'y', (360 * i) / n)
      await animateTo(this.bridge, offset, center.clone(), 600)
      this.breadcrumb()
      pngs.push(await capturePNG(this.bridge))
    }
    return { frames_base64: pngs.map(dataUrlToBase64) }
  }
}

export type CameraTool =
  | 'look_at' | 'set_view' | 'orbit' | 'dolly' | 'frame_object' | 'reset_view' | 'scan_pause' | 'reframe' | 'reset_trail'

/** Dispatch a `camera_move` tool by name. */
export function runCameraTool(
  ex: FrontendExecutors,
  tool: CameraTool,
  args: Record<string, unknown>,
): Promise<ToolResult> {
  switch (tool) {
    case 'look_at': return ex.look_at(args as never)
    case 'set_view': return ex.set_view(args as never)
    case 'orbit': return ex.orbit(args as never)
    case 'dolly': return ex.dolly(args as never)
    case 'frame_object': return ex.frame_object(args as never)
    case 'reset_view': return ex.reset_view(args as never)
    case 'reframe': return ex.reframe(args as never)
    case 'scan_pause': return ex.scan_pause(args as never)
    case 'reset_trail': return ex.reset_trail(args as never)
    default:
      // Malformed/unknown payloads must be rejected at the boundary, never
      // silently "succeed" (the old switch returned undefined here).
      return Promise.resolve({ ok: false, error: `unknown camera tool: ${String(tool)}` })
  }
}
