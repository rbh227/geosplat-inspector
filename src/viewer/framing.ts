/**
 * Pure scene-framing math (no THREE dependency, so it is unit-testable).
 *
 * The viewer's old default framing parked the camera at a fixed ~19° elevation
 * and a std-based distance. For wide/flat outdoor captures that is a grazing
 * view that collapses the scene into a thin streak. These functions instead:
 *   - find a robust core (5th/95th percentile bounds) that ignores far floaters,
 *   - pick a camera elevation from the scene's vertical-vs-horizontal aspect
 *     (flat/wide → high angle, tall → low angle), and
 *   - pick a distance that fits the core within the camera's limiting FOV.
 *
 * All inputs/outputs are world-space; the caller resolves the mesh Y-flip
 * before sampling so world up is +Y.
 */

export interface Vec3 {
  x: number
  y: number
  z: number
}

export interface Framing {
  target: [number, number, number]
  position: [number, number, number]
}

export interface CoreBounds {
  center: [number, number, number]
  radius: number
}

const DEG = Math.PI / 180

function clamp(v: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, v))
}

/** Linear-interpolated percentile of an already-sorted ascending array. */
function percentile(sorted: number[], p: number): number {
  if (sorted.length === 0) return 0
  const idx = (sorted.length - 1) * p
  const lo = Math.floor(idx)
  const hi = Math.ceil(idx)
  if (lo === hi) return sorted[lo]
  const frac = idx - lo
  return sorted[lo] * (1 - frac) + sorted[hi] * frac
}

interface RobustBounds {
  center: [number, number, number]
  ex: number
  ey: number
  ez: number
}

/** Per-axis 5th/95th percentile bounds — robust to far-flung floaters. */
function robustBounds(points: readonly Vec3[]): RobustBounds | null {
  const n = points.length
  if (n === 0) return null

  const xs = new Array<number>(n)
  const ys = new Array<number>(n)
  const zs = new Array<number>(n)
  for (let i = 0; i < n; i++) {
    xs[i] = points[i].x
    ys[i] = points[i].y
    zs[i] = points[i].z
  }
  xs.sort((a, b) => a - b)
  ys.sort((a, b) => a - b)
  zs.sort((a, b) => a - b)

  const xLo = percentile(xs, 0.05), xHi = percentile(xs, 0.95)
  const yLo = percentile(ys, 0.05), yHi = percentile(ys, 0.95)
  const zLo = percentile(zs, 0.05), zHi = percentile(zs, 0.95)

  return {
    center: [(xLo + xHi) / 2, (yLo + yHi) / 2, (zLo + zHi) / 2],
    ex: xHi - xLo,
    ey: yHi - yLo,
    ez: zHi - zLo,
  }
}

/** Robust core center + bounding-sphere radius (used for view presets). */
export function computeCoreBounds(points: readonly Vec3[]): CoreBounds | null {
  const b = robustBounds(points)
  if (!b) return null
  return { center: b.center, radius: 0.5 * Math.hypot(b.ex, b.ey, b.ez) }
}

/**
 * Derive perspective near/far planes from the camera-to-target distance and the
 * scene's radius. A fixed near=0.1/far=1000 gives a 10000:1 ratio that wrecks
 * depth precision on large outdoor scenes (and clips them). Scaling both planes
 * with the framed distance keeps the ratio sane regardless of scene size.
 *
 * @param distance    camera-to-target distance (world units)
 * @param sceneRadius core bounding-sphere radius (world units)
 */
export function nearFarForDistance(
  distance: number,
  sceneRadius: number,
): { near: number; far: number } {
  const d = Number.isFinite(distance) && distance > 0 ? distance : 1
  const r = Number.isFinite(sceneRadius) && sceneRadius > 0 ? sceneRadius : 0
  const near = Math.max(d / 1000, 0.01)
  const far = (d + r) * 3
  return { near, far }
}

/**
 * Aspect-aware default camera pose.
 *
 * @param fovYDeg   vertical field of view in degrees
 * @param aspect    viewport width / height
 * @param azimuthDeg yaw around world-up for a 3/4 view (default 35°)
 */
export function computeFraming(
  points: readonly Vec3[],
  fovYDeg: number,
  aspect: number,
  azimuthDeg = 35,
): Framing | null {
  if (points.length < 2) return null
  const b = robustBounds(points)
  if (!b) return null

  const [cx, cy, cz] = b.center
  const horizontal = Math.hypot(b.ex, b.ez)
  const vertical = b.ey
  const ratio = horizontal > 1e-6 ? vertical / horizontal : 1

  // Flat/wide scenes (small ratio) get a high elevation so the ground plane
  // isn't viewed edge-on; tall scenes (large ratio) get a low elevation.
  const elevationDeg = clamp(35 + 22 * (1 - ratio), 22, 55)
  const elevation = elevationDeg * DEG
  const azimuth = azimuthDeg * DEG

  // Fit the core's bounding sphere within the limiting (smaller) FOV.
  const boundingRadius = Math.max(0.5 * Math.hypot(b.ex, b.ey, b.ez), 1e-3)
  const vfov = fovYDeg * DEG
  const hfov = 2 * Math.atan(Math.tan(vfov / 2) * aspect)
  const limitingFov = Math.min(vfov, hfov)
  const distance = (boundingRadius / Math.sin(limitingFov / 2)) * 1.15

  const dir = {
    x: Math.cos(elevation) * Math.sin(azimuth),
    y: Math.sin(elevation),
    z: Math.cos(elevation) * Math.cos(azimuth),
  }

  return {
    target: [cx, cy, cz],
    position: [cx + dir.x * distance, cy + dir.y * distance, cz + dir.z * distance],
  }
}
