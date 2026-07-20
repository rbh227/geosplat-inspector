import * as THREE from 'three'
import type { OrbitControls } from 'three/addons/controls/OrbitControls.js'

/**
 * Attempt a cubic-ease-out curve: f(t) = 1 - (1-t)^3
 */
function easeOutCubic(t: number): number {
  const inv = 1 - t
  return 1 - inv * inv * inv
}

/**
 * Smoothly tween an OrbitControls camera from its current pose to a target
 * position and look-target over `duration` milliseconds.
 *
 * Returns a cancel function that aborts the tween immediately.
 */
export function tweenCamera(
  controls: OrbitControls,
  camera: THREE.PerspectiveCamera,
  toPosition: THREE.Vector3,
  toTarget: THREE.Vector3,
  duration: number,
  onComplete?: () => void,
): () => void {
  const startPosition = camera.position.clone()
  const startTarget = controls.target.clone()

  const startTime = performance.now()
  let rafId = 0
  let cancelled = false

  const tmpPos = new THREE.Vector3()
  const tmpTarget = new THREE.Vector3()

  function tick() {
    if (cancelled) return

    const elapsed = performance.now() - startTime
    const rawT = Math.min(elapsed / duration, 1)
    const t = easeOutCubic(rawT)

    tmpPos.lerpVectors(startPosition, toPosition, t)
    tmpTarget.lerpVectors(startTarget, toTarget, t)

    camera.position.copy(tmpPos)
    controls.target.copy(tmpTarget)
    controls.update()

    if (rawT < 1) {
      rafId = requestAnimationFrame(tick)
    } else {
      // Ensure final values are exact
      camera.position.copy(toPosition)
      controls.target.copy(toTarget)
      controls.update()
      onComplete?.()
    }
  }

  rafId = requestAnimationFrame(tick)

  return () => {
    cancelled = true
    cancelAnimationFrame(rafId)
  }
}
