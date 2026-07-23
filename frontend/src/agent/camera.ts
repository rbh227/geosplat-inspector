/**
 * Paced, AWAITED camera moves — the "robot inspector" feel. Never teleport.
 *
 * We drive the move ourselves (per-frame snap via the bridge's animate=false
 * path, which also keeps OrbitControls' target in sync) so we control the
 * duration and easing of every tool independently, and can `await` completion.
 */
import * as THREE from 'three'
import type { RendererBridge } from './types.ts'

const DEFAULT_MOVE_MS = 900
const DEFAULT_FRAME_MARGIN = 1.6
// Cap framing distance to a multiple of the scene radius so reset_view/frame
// never fling the camera to the far edge of a large scene (which, with a
// scene-tracking frustum, still reads as "zoomed to a dot"). Typical framing is
// ~3.8·radius; this only bites on very narrow FOV / extreme aspect.
const MAX_FRAME_FACTOR = 5

function easeOutCubic(t: number): number {
  const inv = 1 - t
  return 1 - inv * inv * inv
}

/**
 * Convert a backend-supplied splat coordinate into renderer/world space.
 *
 * The splat mesh is rendered with `rotation.x = Math.PI` (SceneManager), which
 * negates BOTH Y and Z: a backend point (x,y,z) lands at world (x,-y,-z). The
 * marker overlay compensates with the same flip (`markersGroup.rotation.x =
 * Math.PI`). Camera aim points must be flipped identically so they target the
 * Gaussians and not a mirrored, empty location.
 */
export function toRenderSpace(a: ArrayLike<number>): THREE.Vector3 {
  return new THREE.Vector3(a[0], -a[1], -a[2])
}

/**
 * World-space point to aim a camera tool at, with the origin-default backstop.
 *
 * The model tends to send [0,0,0] for look_at/orbit/capture_orbit centers,
 * which is empty space on a real (off-origin) capture. When it does — and the
 * scene really sits away from the origin — substitute the world-space scene
 * `core.center` (already render-space; returned as-is). Explicit non-origin
 * coordinates are respected and flipped to render space like any backend coord.
 */
export function resolveAimPoint(
  raw: number[] | undefined,
  core: { center: [number, number, number]; radius: number } | null,
): THREE.Vector3 {
  const isOrigin = !raw || (Number(raw[0]) === 0 && Number(raw[1]) === 0 && Number(raw[2]) === 0)
  if (isOrigin && core && Math.hypot(...core.center) > core.radius * 0.05) {
    return new THREE.Vector3(core.center[0], core.center[1], core.center[2])
  }
  return toRenderSpace(raw ?? [0, 0, 0])
}

/** Animate camera from its current pose to (toPos, toTarget). Resolves when done. */
export function animateTo(
  bridge: RendererBridge,
  toPos: THREE.Vector3,
  toTarget: THREE.Vector3,
  durationMs = DEFAULT_MOVE_MS,
): Promise<void> {
  const { position: fromPos, target: fromTarget } = bridge.getCameraPose()
  const start = performance.now()
  const tmpPos = new THREE.Vector3()
  const tmpTarget = new THREE.Vector3()

  return new Promise<void>((resolve) => {
    function tick() {
      const raw = Math.min((performance.now() - start) / durationMs, 1)
      const t = easeOutCubic(raw)
      tmpPos.lerpVectors(fromPos, toPos, t)
      tmpTarget.lerpVectors(fromTarget, toTarget, t)
      bridge.setCameraPose(tmpPos.clone(), tmpTarget.clone(), false)
      if (raw < 1) {
        requestAnimationFrame(tick)
      } else {
        bridge.setCameraPose(toPos.clone(), toTarget.clone(), false)
        resolve()
      }
    }
    requestAnimationFrame(tick)
  })
}

export function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, Math.max(0, ms)))
}

/**
 * Orbit the camera around `center` by `deg` about a world axis, arcing along
 * the circle. Unlike animateTo (a straight-line lerp from start to endpoint),
 * this interpolates the ANGLE — so a 360° orbit sweeps the whole way round
 * instead of lerping to the identical endpoint (= no motion), and partial
 * angles trace the arc instead of cutting a chord through the scene.
 */
export function animateOrbit(
  bridge: RendererBridge,
  center: THREE.Vector3,
  axis: 'x' | 'y' | 'z',
  deg: number,
  durationMs = DEFAULT_MOVE_MS,
): Promise<void> {
  const startPos = bridge.getCameraPose().position.clone()
  const start = performance.now()

  return new Promise<void>((resolve) => {
    function tick() {
      const raw = Math.min((performance.now() - start) / durationMs, 1)
      const t = easeOutCubic(raw)
      const pos = rotateAround(startPos, center, axis, deg * t)
      bridge.setCameraPose(pos, center.clone(), false)
      if (raw < 1) {
        requestAnimationFrame(tick)
      } else {
        resolve()
      }
    }
    requestAnimationFrame(tick)
  })
}

/**
 * How much of the vertical view the scene core fills, as a fraction (0..1).
 *
 * A framing signal for the agent so it stops guessing zoom (Codex boundary):
 * ~0.4-0.7 is well-framed, <~0.15 too far (a few floaters in the void),
 * >~0.9 too close. Pure geometry: the core is a sphere (center, radius); its
 * diameter over the world-space view height at the core's distance.
 */
export function sceneCoverage(
  cameraPos: THREE.Vector3,
  fovYDeg: number,
  core: { center: [number, number, number]; radius: number } | null,
): number {
  if (!core || core.radius <= 0) return 0
  const center = new THREE.Vector3(core.center[0], core.center[1], core.center[2])
  const dist = cameraPos.distanceTo(center)
  if (dist <= 1e-6) return 1
  const halfHeight = Math.tan((fovYDeg * Math.PI) / 360) * dist // tan(fov/2)·d
  if (halfHeight <= 0) return 1
  return Math.min(1, core.radius / halfHeight)
}

/**
 * Is the scene core in front of the camera and inside the frustum?
 * `coverage` is pure distance — it reads "well framed" even facing away from
 * the scene. The capture percept pairs it with this flag so the model knows
 * when the number is meaningless and it should turn toward the scene first.
 */
export function coreInView(
  camera: THREE.PerspectiveCamera,
  core: { center: [number, number, number]; radius: number } | null,
): boolean {
  if (!core || core.radius <= 0) return false
  const center = new THREE.Vector3(core.center[0], core.center[1], core.center[2])
  camera.updateMatrixWorld()
  const inCam = center.clone().applyMatrix4(camera.matrixWorldInverse)
  if (inCam.z >= 0) return false // behind the camera plane
  const ndc = center.clone().project(camera)
  return Math.abs(ndc.x) <= 1.1 && Math.abs(ndc.y) <= 1.1 // small margin off-center
}

/**
 * Clamp a camera destination to a sane distance band around the scene core —
 * an app-owned safety limit so a dolly can't bury the camera in a few floaters
 * (too close) or fling it into the void (too far), regardless of what distance
 * the model asked for. Returns the (possibly pulled-in/pushed-out) position.
 */
export function clampToCore(
  to: THREE.Vector3,
  core: { center: [number, number, number]; radius: number } | null,
  minFactor = 0.5,
  maxFactor = 12,
): THREE.Vector3 {
  if (!core || core.radius <= 0) return to
  const center = new THREE.Vector3(core.center[0], core.center[1], core.center[2])
  const dir = to.clone().sub(center)
  const dist = dir.length()
  if (dist <= 1e-6) return to
  const clamped = Math.min(Math.max(dist, core.radius * minFactor), core.radius * maxFactor)
  if (clamped === dist) return to
  return center.add(dir.multiplyScalar(clamped / dist))
}

/** Distance that frames a bounding sphere of `radius` in the current camera FOV. */
function framingDistance(camera: THREE.PerspectiveCamera, radius: number): number {
  const vFov = (camera.fov * Math.PI) / 180
  const hFov = 2 * Math.atan(Math.tan(vFov / 2) * camera.aspect)
  const fit = Math.min(vFov, hFov)
  const dist = (radius * DEFAULT_FRAME_MARGIN) / Math.sin(fit / 2)
  return Math.min(dist, radius * MAX_FRAME_FACTOR)
}

/** Compute a pose that frames the given box, viewed from the current direction. */
export function poseForBox(
  bridge: RendererBridge,
  box: THREE.Box3,
): { position: THREE.Vector3; target: THREE.Vector3 } {
  const camera = bridge.getCamera()
  const center = box.getCenter(new THREE.Vector3())
  const radius = box.getSize(new THREE.Vector3()).length() * 0.5
  const dist = framingDistance(camera, radius)
  const { position } = bridge.getCameraPose()
  const dir = position.clone().sub(center)
  if (dir.lengthSq() < 1e-8) dir.set(0.6, 0.6, 0.6)
  dir.normalize().multiplyScalar(dist)
  return { position: center.clone().add(dir), target: center }
}

/** Rotate `point` around `center` by `deg` about the given world axis. */
export function rotateAround(
  point: THREE.Vector3,
  center: THREE.Vector3,
  axis: 'x' | 'y' | 'z',
  deg: number,
): THREE.Vector3 {
  const axisVec =
    axis === 'x' ? new THREE.Vector3(1, 0, 0)
      : axis === 'y' ? new THREE.Vector3(0, 1, 0)
        : new THREE.Vector3(0, 0, 1)
  const rel = point.clone().sub(center)
  rel.applyAxisAngle(axisVec, (deg * Math.PI) / 180)
  return center.clone().add(rel)
}
