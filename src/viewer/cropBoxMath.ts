/**
 * Pure geometry for the operator crop box.
 *
 * The box is represented in the scene as a unit cube parented to the splat
 * mesh, so `position` is its center and `scale` its full size — both already in
 * backend (mesh-local) coordinates, because the viewer's Y-flip lives on the
 * parent. Keeping the math here means it can be tested without a WebGL context.
 */

export interface Box {
  min: [number, number, number]
  max: [number, number, number]
}

const MIN_SIZE = 1e-4

/** Center + full size of a unit cube -> min/max box. */
export function boxFromTransform(position: readonly number[], scale: readonly number[]): Box {
  const half = [scale[0] / 2, scale[1] / 2, scale[2] / 2]
  return normalizeBox({
    min: [position[0] - half[0], position[1] - half[1], position[2] - half[2]],
    max: [position[0] + half[0], position[1] + half[1], position[2] + half[2]],
  })
}

/** min/max box -> the unit cube's center and full size. */
export function transformFromBox(box: Box): {
  position: [number, number, number]
  scale: [number, number, number]
} {
  const b = normalizeBox(box)
  return {
    position: [
      (b.min[0] + b.max[0]) / 2,
      (b.min[1] + b.max[1]) / 2,
      (b.min[2] + b.max[2]) / 2,
    ],
    scale: [
      Math.max(b.max[0] - b.min[0], MIN_SIZE),
      Math.max(b.max[1] - b.min[1], MIN_SIZE),
      Math.max(b.max[2] - b.min[2], MIN_SIZE),
    ],
  }
}

/**
 * Rebuild min/max componentwise. A scale handle dragged past its opposite face
 * produces a negative scale and inverts an axis; an inverted box silently
 * contains nothing, which would read as "the crop deleted everything".
 */
export function normalizeBox(box: Box): Box {
  return {
    min: [
      Math.min(box.min[0], box.max[0]),
      Math.min(box.min[1], box.max[1]),
      Math.min(box.min[2], box.max[2]),
    ],
    max: [
      Math.max(box.min[0], box.max[0]),
      Math.max(box.min[1], box.max[1]),
      Math.max(box.min[2], box.max[2]),
    ],
  }
}

/**
 * Centers inside the box, boundary inclusive. `centers` is flat xyz triples.
 * Returns the count of centers found; callers multiply by their sampling
 * stride to estimate the full-scene total.
 */
export function countInsideSampled(centers: Float32Array, box: Box): number {
  const b = normalizeBox(box)
  let n = 0
  for (let i = 0; i < centers.length; i += 3) {
    const x = centers[i], y = centers[i + 1], z = centers[i + 2]
    if (
      x >= b.min[0] && x <= b.max[0] &&
      y >= b.min[1] && y <= b.max[1] &&
      z >= b.min[2] && z <= b.max[2]
    ) n++
  }
  return n
}
