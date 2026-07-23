/**
 * Pure scene-framing math (no THREE dependency, so it is unit-testable).
 *
 * The viewer's old default framing parked the camera at a fixed ~19° elevation
 * and a std-based distance. For wide/flat outdoor captures that is a grazing
 * view that collapses the scene into a thin streak. These functions instead:
 *   - find a robust core (median center, 80th-percentile-distance radius) that
 *     ignores far floaters — the 5th/95th percentile box is used only for the
 *     elevation heuristic and computeCoreBox,
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
  const n = points.length
  if (n === 0) return null
  // Center = per-axis median, radius = 80th-percentile distance from it —
  // NOT the 5/95 percentile box: on floater-heavy captures the shell both
  // drags the box's midpoint off the dense mass and inflates its diagonal
  // severalfold, which made the agent's `coverage` percept read "too close"
  // from every sane viewpoint and sent it retreating into the void. Medians
  // and distance percentiles hug the dense mass regardless of how far the
  // shell extends.
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
  const cx = percentile(xs, 0.5)
  const cy = percentile(ys, 0.5)
  const cz = percentile(zs, 0.5)
  const dists = new Array<number>(n)
  for (let i = 0; i < n; i++) {
    dists[i] = Math.hypot(points[i].x - cx, points[i].y - cy, points[i].z - cz)
  }
  dists.sort((a, b) => a - b)
  return { center: [cx, cy, cz], radius: percentile(dists, 0.8) }
}

export interface CoreBox { min: [number, number, number]; max: [number, number, number] }

/** Robust percentile box (5th-95th per axis) — min/max form for crop/preview. */
export function computeCoreBox(points: readonly Vec3[]): CoreBox | null {
  const b = robustBounds(points)
  if (!b) return null
  const [cx, cy, cz] = b.center
  return {
    min: [cx - b.ex / 2, cy - b.ey / 2, cz - b.ez / 2],
    max: [cx + b.ex / 2, cy + b.ey / 2, cz + b.ez / 2],
  }
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
  const core = computeCoreBounds(points)
  if (!b || !core) return null

  const [cx, cy, cz] = core.center // aim at the dense mass, not the box midpoint
  const horizontal = Math.hypot(b.ex, b.ez)
  const vertical = b.ey
  const ratio = horizontal > 1e-6 ? vertical / horizontal : 1

  // Flat/wide scenes (small ratio) get a high elevation so the ground plane
  // isn't viewed edge-on; tall scenes (large ratio) get a low elevation.
  const elevationDeg = clamp(35 + 22 * (1 - ratio), 22, 55)
  const elevation = elevationDeg * DEG
  const azimuth = azimuthDeg * DEG

  // Frame the SAME core sphere the agent's coverage percept measures
  // (computeCoreBounds): the 80th-percentile radius is tighter than the old
  // 5/95 half-diagonal, so pad more (1.5 vs 1.15) to land inside the
  // percept's well-framed band (~0.4-0.7) instead of edge-to-edge.
  const boundingRadius = Math.max(core.radius, 1e-3)
  const vfov = fovYDeg * DEG
  const hfov = 2 * Math.atan(Math.tan(vfov / 2) * aspect)
  const limitingFov = Math.min(vfov, hfov)
  const distance = (boundingRadius / Math.sin(limitingFov / 2)) * 1.5

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
