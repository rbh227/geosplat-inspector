import type { MoveDirection } from '../types/viewer.ts'
import PadGrid, { type PadKey } from './PadGrid.tsx'

/**
 * On-screen WASD movement pad (R8). Six buttons in a 3x3 grid:
 * Q (up) / W (forward) / E (down) on top, A / S / D below.
 *
 * The pad is a VIEW of the shared movement state plus one input source among
 * three (keyboard, pad, agent move_camera) — `activeDirections` drives the
 * highlight no matter who is moving, which is what makes agent flight
 * watchable on the pad (R13/SC2).
 */

const KEYS: PadKey<MoveDirection>[] = [
  { label: 'Q', direction: 'up', gridArea: '1 / 1', title: 'Up' },
  { label: 'W', direction: 'forward', gridArea: '1 / 2', title: 'Forward' },
  { label: 'E', direction: 'down', gridArea: '1 / 3', title: 'Down' },
  { label: 'A', direction: 'left', gridArea: '2 / 1', title: 'Left' },
  { label: 'S', direction: 'back', gridArea: '2 / 2', title: 'Back' },
  { label: 'D', direction: 'right', gridArea: '2 / 3', title: 'Right' },
]

interface MovePadProps {
  activeDirections: ReadonlySet<MoveDirection>
  onInput: (direction: MoveDirection, active: boolean) => void
  disabled?: boolean
}

export default function MovePad({ activeDirections, onInput, disabled = false }: MovePadProps) {
  return (
    <PadGrid
      keys={KEYS}
      activeSet={activeDirections}
      onInput={onInput}
      disabled={disabled}
      ariaLabel="Movement pad"
    />
  )
}
