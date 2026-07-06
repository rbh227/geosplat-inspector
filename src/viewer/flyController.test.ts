import { describe, expect, it } from 'vitest'
import { composeMove, KEY_TO_DIRECTION, type MoveDirection } from './flyController.ts'

const FWD = [0, 0, -1] as const
const RIGHT = [1, 0, 0] as const
const UP = [0, 1, 0] as const

const dirs = (...d: MoveDirection[]) => new Set<MoveDirection>(d)

describe('composeMove', () => {
  it('moves along camera forward for W', () => {
    const [x, y, z] = composeMove(dirs('forward'), FWD, RIGHT, UP, 2, 0.5)
    expect([x, y, z]).toEqual([0, 0, -1])
  })

  it('opposite directions cancel to zero', () => {
    expect(composeMove(dirs('forward', 'back'), FWD, RIGHT, UP, 2, 0.5)).toEqual([0, 0, 0])
    expect(composeMove(dirs('left', 'right'), FWD, RIGHT, UP, 2, 0.5)).toEqual([0, 0, 0])
  })

  it('normalizes diagonals — no speed boost', () => {
    const [x, , z] = composeMove(dirs('forward', 'right'), FWD, RIGHT, UP, 1, 1)
    expect(Math.hypot(x, z)).toBeCloseTo(1, 6)
  })

  it('up/down use world up regardless of camera pitch', () => {
    const pitchedFwd = [0, -0.707, -0.707] as const
    const [x, y, z] = composeMove(dirs('up'), pitchedFwd, RIGHT, UP, 3, 1)
    expect([x, y, z]).toEqual([0, 3, 0])
  })

  it('empty set produces zero displacement', () => {
    expect(composeMove(dirs(), FWD, RIGHT, UP, 5, 1)).toEqual([0, 0, 0])
  })
})

describe('KEY_TO_DIRECTION', () => {
  it('maps WASD + QE', () => {
    expect(KEY_TO_DIRECTION.KeyW).toBe('forward')
    expect(KEY_TO_DIRECTION.KeyS).toBe('back')
    expect(KEY_TO_DIRECTION.KeyA).toBe('left')
    expect(KEY_TO_DIRECTION.KeyD).toBe('right')
    expect(KEY_TO_DIRECTION.KeyQ).toBe('up')
    expect(KEY_TO_DIRECTION.KeyE).toBe('down')
  })
})
