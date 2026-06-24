/**
 * Frontend tool executors — the runs_on:"frontend" tools (ARCHITECTURE.md §6.5).
 *
 * Camera moves are AWAITED and paced; each completed move drops a breadcrumb on
 * the trail. Captures go through the R1-hardened PNG path.
 */
import * as THREE from 'three'
import type { RendererBridge, ToolResult } from './types.ts'
import { animateTo, poseForBox, rotateAround, sleep, vec3 } from './camera.ts'
import { capturePNG, dataUrlToBase64 } from './capture.ts'
import type { Overlay } from './overlay.ts'

function asVec3(v: unknown): THREE.Vector3 {
  const a = v as number[]
  return new THREE.Vector3(a[0], a[1], a[2])
}

export class FrontendExecutors {
  constructor(private bridge: RendererBridge, private overlay: Overlay) {}

  /** Record where the camera ended up after a move. */
  private breadcrumb(): void {
    this.overlay.pushTrailPoint(this.bridge.getCameraPose().position)
  }

  async look_at(args: { target: number[]; duration_ms?: number }): Promise<ToolResult> {
    const { position } = this.bridge.getCameraPose()
    await animateTo(this.bridge, position.clone(), asVec3(args.target), args.duration_ms)
    this.breadcrumb()
    return { ok: true }
  }

  async set_view(args: { position: number[]; target: number[]; duration_ms?: number }): Promise<ToolResult> {
    await animateTo(this.bridge, asVec3(args.position), asVec3(args.target), args.duration_ms)
    this.breadcrumb()
    return { ok: true }
  }

  async orbit(args: { center: number[]; deg: number; axis: 'x' | 'y' | 'z'; duration_ms?: number }): Promise<ToolResult> {
    const center = asVec3(args.center)
    const { position } = this.bridge.getCameraPose()
    const to = rotateAround(position, center, args.axis, args.deg)
    await animateTo(this.bridge, to, center, args.duration_ms)
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
    const to = target.clone().add(dir.multiplyScalar(newLen))
    await animateTo(this.bridge, to, target.clone(), args.duration_ms)
    this.breadcrumb()
    return { ok: true }
  }

  async frame_object(args: { bbox: { min: number[]; max: number[] }; duration_ms?: number }): Promise<ToolResult> {
    const box = new THREE.Box3(vec3(args.bbox.min), vec3(args.bbox.max))
    const pose = poseForBox(this.bridge, box)
    await animateTo(this.bridge, pose.position, pose.target, args.duration_ms)
    this.breadcrumb()
    return { ok: true }
  }

  async reset_view(_args: Record<string, never>): Promise<ToolResult> {
    void _args
    const box = this.bridge.getBoundingBox()
    if (box) {
      const pose = poseForBox(this.bridge, box)
      await animateTo(this.bridge, pose.position, pose.target)
    } else {
      await animateTo(this.bridge, new THREE.Vector3(0, 1.5, 3), new THREE.Vector3(0, 0, 0))
    }
    this.breadcrumb()
    return { ok: true }
  }

  async scan_pause(args: { ms: number }): Promise<ToolResult> {
    await sleep(args.ms)
    return { ok: true }
  }

  async capture_frame(): Promise<ToolResult> {
    return { png_base64: dataUrlToBase64(await capturePNG(this.bridge)) }
  }

  async capture_orbit(args: { center: number[]; n: number; radius?: number }): Promise<ToolResult> {
    const center = asVec3(args.center)
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
  | 'look_at' | 'set_view' | 'orbit' | 'dolly' | 'frame_object' | 'reset_view' | 'scan_pause'

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
    case 'scan_pause': return ex.scan_pause(args as never)
  }
}
