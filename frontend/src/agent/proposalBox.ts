/**
 * Pure, deterministic view-relative box math for the crop-proposal surface.
 *
 * The operator speaks in view-relative terms ("bigger", "move right"); the
 * model turns that into a small `AdjustOpts` delta and THIS module resolves it
 * against the operator's live camera. The model never does coordinate math.
 *
 * Everything here is axis-aligned and side-effect free: each view direction is
 * snapped to its dominant WORLD axis, so the box the operator sees stays a clean
 * axis-aligned crop volume (never a rotated OBB), and the same delta always
 * yields the same box for a given camera.
 *
 * Coordinate note: `ViewBasis` vectors and `Box` bounds are BACKEND coords
 * (render coords with y,z negated — see `toRenderSpace` in ./camera.ts, an
 * involution). `viewBasisFromCamera` performs that render→backend conversion.
 */
import * as THREE from 'three'

export interface Box {
  min: [number, number, number]
  max: [number, number, number]
}

/** Unit view-basis vectors in BACKEND coords. */
export interface ViewBasis {
  right: [number, number, number]
  up: [number, number, number]
  forward: [number, number, number]
}

/**
 * A view-relative box delta.
 * - `grow`     — scale ALL extents uniformly about the center.
 * - `grow_axes[i]` — scale the extent of the world axis dominant for view axis
 *                    i (0=right, 1=up, 2=forward).
 * - `shift[i]` — translate the box along that dominant world axis by
 *                `shift[i] * extent[axis] * sign` (one box-width per unit).
 */
export interface AdjustOpts {
  grow?: number
  grow_axes?: [number, number, number]
  shift?: [number, number, number]
}

type Vec3 = [number, number, number]

/**
 * Dominant WORLD axis for a view direction: `argmax |component|`, carrying the
 * sign of that component. Ties resolve to the lower index (x < y < z).
 */
function dominantAxis(v: Vec3): { axis: number; sign: number } {
  let axis = 0
  let best = Math.abs(v[0])
  for (let i = 1; i < 3; i++) {
    const m = Math.abs(v[i])
    if (m > best) {
      best = m
      axis = i
    }
  }
  return { axis, sign: v[axis] < 0 ? -1 : 1 }
}

/**
 * Apply a view-relative delta to an axis-aligned box.
 *
 * The box stays axis-aligned: each view axis snaps to its dominant world axis
 * and the op lands on that world axis. `shift` uses the ORIGINAL extents (so a
 * shift of 1 always moves exactly one box-width, independent of any grow in the
 * same call). Scale is applied about the box center.
 *
 * Degenerate case — two view axes snapping to the SAME world axis (e.g. a 45°
 * view where right and forward are equidistant): last write wins. The later
 * view axis in {right, up, forward} order overwrites the earlier one's scale
 * and shift for that world axis, rather than compounding.
 */
export function adjustBox(box: Box, basis: ViewBasis, opts: AdjustOpts): Box {
  const min = box.min
  const max = box.max
  const center: Vec3 = [
    (min[0] + max[0]) / 2,
    (min[1] + max[1]) / 2,
    (min[2] + max[2]) / 2,
  ]
  const extent: Vec3 = [max[0] - min[0], max[1] - min[1], max[2] - min[2]]
  const views: Vec3[] = [basis.right, basis.up, basis.forward]

  const uniform = opts.grow ?? 1
  const scale: Vec3 = [uniform, uniform, uniform]
  const shiftByAxis: Vec3 = [0, 0, 0]

  for (let i = 0; i < 3; i++) {
    const { axis, sign } = dominantAxis(views[i])
    // Last write wins on a shared world axis (assignment, not accumulation).
    if (opts.grow_axes) scale[axis] = uniform * opts.grow_axes[i]
    if (opts.shift) shiftByAxis[axis] = opts.shift[i] * extent[axis] * sign
  }

  const outMin: Vec3 = [0, 0, 0]
  const outMax: Vec3 = [0, 0, 0]
  for (let a = 0; a < 3; a++) {
    const half = (extent[a] * scale[a]) / 2
    outMin[a] = center[a] - half + shiftByAxis[a]
    outMax[a] = center[a] + half + shiftByAxis[a]
  }
  return { min: outMin, max: outMax }
}

function normalize(v: Vec3): Vec3 {
  const len = Math.hypot(v[0], v[1], v[2])
  if (len <= 1e-12) return [0, 0, 0]
  return [v[0] / len, v[1] / len, v[2] / len]
}

/** Render coords → backend coords (negate y,z), then normalize to a unit vector. */
function toBackendUnit(v: Vec3): Vec3 {
  return normalize([v[0], -v[1], -v[2]])
}

/**
 * Extract the camera's world basis in BACKEND coords.
 *
 * `matrixWorld` is column-major; its first two columns are the camera's world
 * right and up, and the third column is its world BACKWARD (+z toward the
 * viewer) — so forward is the negated third column. Each is then converted
 * render→backend (negate y,z) and normalized.
 */
export function viewBasisFromCamera(cam: THREE.PerspectiveCamera): ViewBasis {
  cam.updateMatrixWorld()
  const e = cam.matrixWorld.elements
  const right: Vec3 = [e[0], e[1], e[2]]
  const up: Vec3 = [e[4], e[5], e[6]]
  const forward: Vec3 = [-e[8], -e[9], -e[10]]
  return {
    right: toBackendUnit(right),
    up: toBackendUnit(up),
    forward: toBackendUnit(forward),
  }
}
