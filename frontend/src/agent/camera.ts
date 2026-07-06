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

/** Distance that frames a bounding sphere of `radius` in the current camera FOV. */
function framingDistance(camera: THREE.PerspectiveCamera, radius: number): number {
  const vFov = (camera.fov * Math.PI) / 180
  const hFov = 2 * Math.atan(Math.tan(vFov / 2) * camera.aspect)
  const fit = Math.min(vFov, hFov)
  return (radius * DEFAULT_FRAME_MARGIN) / Math.sin(fit / 2)
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
