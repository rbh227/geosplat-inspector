import type { RotateDirection } from '../types/viewer.ts'
import PadGrid, { type PadKey } from './PadGrid.tsx'

/**
 * On-screen rotate pad (R7) — arrow-key layout beside the WASD move pad:
 * look up on top, turn left / look down / turn right below.
 *
 * Like the move pad, this is a VIEW of shared rotation state plus one input
 * source among two (pad, agent rotation) — `activeRotations` drives the
 * highlight no matter who is turning the camera (R8).
 */

const KEYS: PadKey<RotateDirection>[] = [
  { label: '↑', direction: 'pitch-up', gridArea: '1 / 2', title: 'Look up' },
  { label: '←', direction: 'yaw-left', gridArea: '2 / 1', title: 'Turn left' },
  { label: '↓', direction: 'pitch-down', gridArea: '2 / 2', title: 'Look down' },
  { label: '→', direction: 'yaw-right', gridArea: '2 / 3', title: 'Turn right' },
]

interface RotatePadProps {
  activeRotations: ReadonlySet<RotateDirection>
  onInput: (direction: RotateDirection, active: boolean) => void
  disabled?: boolean
}

export default function RotatePad({ activeRotations, onInput, disabled = false }: RotatePadProps) {
  return (
    <PadGrid
      keys={KEYS}
      activeSet={activeRotations}
      onInput={onInput}
      disabled={disabled}
      ariaLabel="Rotate pad"
    />
  )
}
