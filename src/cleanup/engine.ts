/* -------------------------------------------------------------------------- */
/*  Splat cleanup — pure functions                                            */
/* -------------------------------------------------------------------------- */

export interface SplatData {
  center: { x: number; y: number; z: number }
  scales: { x: number; y: number; z: number }
  quaternion: { x: number; y: number; z: number; w: number }
  opacity: number
  color: { r: number; g: number; b: number }
}

/* -------------------------------------------------------------------------- */
/*  Filter by opacity                                                         */
/* -------------------------------------------------------------------------- */

/**
 * Return indices of splats whose opacity is >= the given threshold.
 */
export function filterByOpacity(splats: SplatData[], threshold: number): number[] {
  const keep: number[] = []
  for (let i = 0; i < splats.length; i++) {
    if (splats[i].opacity >= threshold) {
      keep.push(i)
    }
  }
  return keep
}

/* -------------------------------------------------------------------------- */
/*  Filter outliers                                                           */
/* -------------------------------------------------------------------------- */

/**
 * Return indices of splats that lie within `kStdDev` standard deviations of
 * the mean position along every axis.
 */
export function filterOutliers(splats: SplatData[], kStdDev: number): number[] {
  const n = splats.length
  if (n === 0) return []

  // Compute mean position.
  let sumX = 0
  let sumY = 0
  let sumZ = 0
  for (let i = 0; i < n; i++) {
    sumX += splats[i].center.x
    sumY += splats[i].center.y
    sumZ += splats[i].center.z
  }
  const meanX = sumX / n
  const meanY = sumY / n
  const meanZ = sumZ / n

  // Compute standard deviation per axis.
  let varX = 0
  let varY = 0
  let varZ = 0
  for (let i = 0; i < n; i++) {
    const dx = splats[i].center.x - meanX
    const dy = splats[i].center.y - meanY
    const dz = splats[i].center.z - meanZ
    varX += dx * dx
    varY += dy * dy
    varZ += dz * dz
  }
  const stdX = Math.sqrt(varX / n)
  const stdY = Math.sqrt(varY / n)
  const stdZ = Math.sqrt(varZ / n)

  const limX = kStdDev * stdX
  const limY = kStdDev * stdY
  const limZ = kStdDev * stdZ

  const keep: number[] = []
  for (let i = 0; i < n; i++) {
    const { x, y, z } = splats[i].center
    if (
      Math.abs(x - meanX) <= limX &&
      Math.abs(y - meanY) <= limY &&
      Math.abs(z - meanZ) <= limZ
    ) {
      keep.push(i)
    }
  }

  return keep
}

/* -------------------------------------------------------------------------- */
/*  Filter by bounding box                                                    */
/* -------------------------------------------------------------------------- */

/**
 * Return indices of splats whose center lies within the given axis-aligned
 * bounding box (inclusive).
 */
export function filterByBbox(
  splats: SplatData[],
  min: { x: number; y: number; z: number },
  max: { x: number; y: number; z: number },
): number[] {
  const keep: number[] = []
  for (let i = 0; i < splats.length; i++) {
    const { x, y, z } = splats[i].center
    if (x >= min.x && x <= max.x && y >= min.y && y <= max.y && z >= min.z && z <= max.z) {
      keep.push(i)
    }
  }
  return keep
}

/* -------------------------------------------------------------------------- */
/*  Statistics                                                                */
/* -------------------------------------------------------------------------- */

export interface SplatStats {
  count: number
  meanPosition: { x: number; y: number; z: number }
  stdPosition: { x: number; y: number; z: number }
  /** 10 buckets spanning [0, 1) — bucket i covers [i*0.1, (i+1)*0.1). */
  opacityHistogram: number[]
  bbox: {
    min: { x: number; y: number; z: number }
    max: { x: number; y: number; z: number }
  }
}

/**
 * Compute aggregate statistics for a set of splats.
 */
export function computeStats(splats: SplatData[]): SplatStats {
  const n = splats.length

  if (n === 0) {
    return {
      count: 0,
      meanPosition: { x: 0, y: 0, z: 0 },
      stdPosition: { x: 0, y: 0, z: 0 },
      opacityHistogram: new Array(10).fill(0),
      bbox: {
        min: { x: 0, y: 0, z: 0 },
        max: { x: 0, y: 0, z: 0 },
      },
    }
  }

  // Single pass: accumulate sums and track bbox.
  let sumX = 0
  let sumY = 0
  let sumZ = 0

  let minX = Infinity
  let minY = Infinity
  let minZ = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  let maxZ = -Infinity

  const histogram = new Array<number>(10).fill(0)

  for (let i = 0; i < n; i++) {
    const { x, y, z } = splats[i].center
    sumX += x
    sumY += y
    sumZ += z

    if (x < minX) minX = x
    if (y < minY) minY = y
    if (z < minZ) minZ = z
    if (x > maxX) maxX = x
    if (y > maxY) maxY = y
    if (z > maxZ) maxZ = z

    // Bucket index: clamp to [0, 9].
    const bucket = Math.min(Math.floor(splats[i].opacity * 10), 9)
    histogram[bucket]++
  }

  const meanX = sumX / n
  const meanY = sumY / n
  const meanZ = sumZ / n

  // Second pass for std deviation.
  let varX = 0
  let varY = 0
  let varZ = 0
  for (let i = 0; i < n; i++) {
    const dx = splats[i].center.x - meanX
    const dy = splats[i].center.y - meanY
    const dz = splats[i].center.z - meanZ
    varX += dx * dx
    varY += dy * dy
    varZ += dz * dz
  }

  return {
    count: n,
    meanPosition: { x: meanX, y: meanY, z: meanZ },
    stdPosition: {
      x: Math.sqrt(varX / n),
      y: Math.sqrt(varY / n),
      z: Math.sqrt(varZ / n),
    },
    opacityHistogram: histogram,
    bbox: {
      min: { x: minX, y: minY, z: minZ },
      max: { x: maxX, y: maxY, z: maxZ },
    },
  }
}
