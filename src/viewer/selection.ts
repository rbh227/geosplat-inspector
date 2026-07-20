/**
 * Pure selection math for the editor tools (no THREE types in signatures).
 *
 * Projection follows the standard MVP chain; the screen-space containment
 * approach (rasterized mask sampling for brush/lasso/polygon) is adapted from
 * SuperSplat (github.com/playcanvas/supersplat, MIT © PlayCanvas Ltd).
 *
 * Matrices are 16-element column-major arrays (THREE `.elements` layout).
 * All batch inputs are flat typed arrays: centers = [x0,y0,z0, x1,y1,z1, ...].
 */

const W_EPSILON = 1e-6

/** out = a * b (column-major 4x4 multiply, THREE convention). */
export function composeMatrices(a: ArrayLike<number>, b: ArrayLike<number>): number[] {
  const out = new Array<number>(16)
  for (let col = 0; col < 4; col++) {
    for (let row = 0; row < 4; row++) {
      let sum = 0
      for (let k = 0; k < 4; k++) sum += a[k * 4 + row] * b[col * 4 + k]
      out[col * 4 + row] = sum
    }
  }
  return out
}

/** Apply an affine world matrix to a flat xyz array (returns a new array). */
export function transformPoints(centers: Float32Array, m: ArrayLike<number>): Float32Array {
  const n = Math.floor(centers.length / 3)
  const out = new Float32Array(n * 3)
  for (let i = 0; i < n; i++) {
    const x = centers[i * 3], y = centers[i * 3 + 1], z = centers[i * 3 + 2]
    out[i * 3] = m[0] * x + m[4] * y + m[8] * z + m[12]
    out[i * 3 + 1] = m[1] * x + m[5] * y + m[9] * z + m[13]
    out[i * 3 + 2] = m[2] * x + m[6] * y + m[10] * z + m[14]
  }
  return out
}

export interface ScreenPoints {
  /** Pixel coordinates, 2 per point (origin top-left). */
  xy: Float32Array
  /** 1 = in front of the camera, 0 = behind (never selectable). */
  visible: Uint8Array
}

/**
 * Project world-space centers to pixel coordinates through a combined
 * view-projection matrix (`composeMatrices(projection, viewInverse)`).
 */
export function projectToScreen(
  centersWorld: Float32Array,
  viewProj: ArrayLike<number>,
  width: number,
  height: number,
): ScreenPoints {
  const n = Math.floor(centersWorld.length / 3)
  const xy = new Float32Array(n * 2)
  const visible = new Uint8Array(n)
  for (let i = 0; i < n; i++) {
    const x = centersWorld[i * 3], y = centersWorld[i * 3 + 1], z = centersWorld[i * 3 + 2]
    const clipW = viewProj[3] * x + viewProj[7] * y + viewProj[11] * z + viewProj[15]
    if (clipW <= W_EPSILON) continue // behind the camera
    const clipX = viewProj[0] * x + viewProj[4] * y + viewProj[8] * z + viewProj[12]
    const clipY = viewProj[1] * x + viewProj[5] * y + viewProj[9] * z + viewProj[13]
    xy[i * 2] = (clipX / clipW * 0.5 + 0.5) * width
    xy[i * 2 + 1] = (-clipY / clipW * 0.5 + 0.5) * height
    visible[i] = 1
  }
  return { xy, visible }
}

/** Indices of visible points whose pixel lands on a painted (alpha > 0) mask pixel. */
export function selectInMask(
  xy: Float32Array,
  visible: Uint8Array,
  maskRGBA: Uint8ClampedArray,
  maskWidth: number,
  maskHeight: number,
): Uint32Array {
  const n = visible.length
  const hits: number[] = []
  for (let i = 0; i < n; i++) {
    if (!visible[i]) continue
    const px = Math.floor(xy[i * 2])
    const py = Math.floor(xy[i * 2 + 1])
    if (px < 0 || py < 0 || px >= maskWidth || py >= maskHeight) continue
    if (maskRGBA[(py * maskWidth + px) * 4 + 3] > 0) hits.push(i)
  }
  return Uint32Array.from(hits)
}

/** Indices of visible points within a pixel-space circle (agent brush path). */
export function selectInCircle(
  xy: Float32Array,
  visible: Uint8Array,
  cx: number,
  cy: number,
  radius: number,
): Uint32Array {
  const n = visible.length
  const r2 = radius * radius
  const hits: number[] = []
  for (let i = 0; i < n; i++) {
    if (!visible[i]) continue
    const dx = xy[i * 2] - cx
    const dy = xy[i * 2 + 1] - cy
    if (dx * dx + dy * dy <= r2) hits.push(i)
  }
  return Uint32Array.from(hits)
}

/** Indices of visible points inside a pixel-space polygon (flat [x0,y0,x1,y1,...], ray casting). */
export function selectInPolygon(
  xy: Float32Array,
  visible: Uint8Array,
  polygon: ArrayLike<number>,
): Uint32Array {
  const nVerts = Math.floor(polygon.length / 2)
  const n = visible.length
  const hits: number[] = []
  for (let i = 0; i < n; i++) {
    if (!visible[i]) continue
    const px = xy[i * 2], py = xy[i * 2 + 1]
    let inside = false
    for (let a = 0, b = nVerts - 1; a < nVerts; b = a++) {
      const ax = polygon[a * 2], ay = polygon[a * 2 + 1]
      const bx = polygon[b * 2], by = polygon[b * 2 + 1]
      if ((ay > py) !== (by > py) && px < ((bx - ax) * (py - ay)) / (by - ay) + ax) {
        inside = !inside
      }
    }
    if (inside) hits.push(i)
  }
  return Uint32Array.from(hits)
}

/** Indices of centers inside a world-space sphere (boundary exclusive above radius). */
export function selectInSphere(
  centersWorld: Float32Array,
  center: ArrayLike<number>,
  radius: number,
): Uint32Array {
  const n = Math.floor(centersWorld.length / 3)
  const r2 = radius * radius
  const cx = center[0], cy = center[1], cz = center[2]
  const hits: number[] = []
  for (let i = 0; i < n; i++) {
    const dx = centersWorld[i * 3] - cx
    const dy = centersWorld[i * 3 + 1] - cy
    const dz = centersWorld[i * 3 + 2] - cz
    if (dx * dx + dy * dy + dz * dz <= r2) hits.push(i)
  }
  return Uint32Array.from(hits)
}

/** Indices of centers inside a world-space AABB (faces inclusive). */
export function selectInBox(
  centersWorld: Float32Array,
  min: ArrayLike<number>,
  max: ArrayLike<number>,
): Uint32Array {
  const n = Math.floor(centersWorld.length / 3)
  const hits: number[] = []
  for (let i = 0; i < n; i++) {
    const x = centersWorld[i * 3], y = centersWorld[i * 3 + 1], z = centersWorld[i * 3 + 2]
    if (
      x >= min[0] && x <= max[0] &&
      y >= min[1] && y <= max[1] &&
      z >= min[2] && z <= max[2]
    ) hits.push(i)
  }
  return Uint32Array.from(hits)
}
