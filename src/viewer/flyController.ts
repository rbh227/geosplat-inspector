/**
 * Fly-navigation math (KTD6). Pure — no THREE types in signatures.
 *
 * A deliberate thin custom controller instead of three/addons FlyControls:
 * FlyControls drives movement through private internal state with no public
 * velocity API and has no concept of a look target, which the rest of the
 * viewer (camera tools, orbit handoff) depends on.
 */

export type MoveDirection = 'forward' | 'back' | 'left' | 'right' | 'up' | 'down'

export const MOVE_DIRECTIONS: readonly MoveDirection[] = [
  'forward', 'back', 'left', 'right', 'up', 'down',
]

export const KEY_TO_DIRECTION: Readonly<Record<string, MoveDirection>> = {
  KeyW: 'forward',
  KeyS: 'back',
  KeyA: 'left',
  KeyD: 'right',
  KeyQ: 'up',
  KeyE: 'down',
}

export type RotateDirection = 'yaw-left' | 'yaw-right' | 'pitch-up' | 'pitch-down'

export const ROTATE_DIRECTIONS: readonly RotateDirection[] = [
  'yaw-left', 'yaw-right', 'pitch-up', 'pitch-down',
]

type Vec3 = readonly [number, number, number]

/**
 * Displacement for one frame from the active direction set and the camera
 * basis. Forward/back and left/right move in the camera plane; up/down move
 * along world up. The combined direction is normalized so diagonals are not
 * faster than a single axis.
 */
export function composeMove(
  dirs: ReadonlySet<MoveDirection>,
  forward: Vec3,
  right: Vec3,
  worldUp: Vec3,
  speed: number,
  dt: number,
): [number, number, number] {
  let x = 0, y = 0, z = 0
  if (dirs.has('forward')) { x += forward[0]; y += forward[1]; z += forward[2] }
  if (dirs.has('back')) { x -= forward[0]; y -= forward[1]; z -= forward[2] }
  if (dirs.has('right')) { x += right[0]; y += right[1]; z += right[2] }
  if (dirs.has('left')) { x -= right[0]; y -= right[1]; z -= right[2] }
  if (dirs.has('up')) { x += worldUp[0]; y += worldUp[1]; z += worldUp[2] }
  if (dirs.has('down')) { x -= worldUp[0]; y -= worldUp[1]; z -= worldUp[2] }

  const len = Math.hypot(x, y, z)
  if (len < 1e-8) return [0, 0, 0]
  const k = (speed * dt) / len
  return [x * k, y * k, z * k]
}

/**
 * Yaw/pitch deltas (radians) for one frame from the active rotate-direction
 * set. Positive yaw turns the view left, positive pitch looks up — matching
 * the drag-to-look euler math in SceneManager. Same normalization contract
 * as composeMove: a yaw+pitch diagonal is not faster than a single axis.
 */
export function composeLook(
  dirs: ReadonlySet<RotateDirection>,
  speed: number,
  dt: number,
): [number, number] {
  let yaw = 0, pitch = 0
  if (dirs.has('yaw-left')) yaw += 1
  if (dirs.has('yaw-right')) yaw -= 1
  if (dirs.has('pitch-up')) pitch += 1
  if (dirs.has('pitch-down')) pitch -= 1
  const len = Math.hypot(yaw, pitch)
  if (len < 1e-8) return [0, 0]
  const k = (speed * dt) / len
  return [yaw * k, pitch * k]
}
