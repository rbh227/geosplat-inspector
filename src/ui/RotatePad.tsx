import type { RotateDirection } from '../types/viewer.ts'

/**
 * On-screen rotate pad (R7) — arrow-key layout beside the WASD move pad:
 * look up on top, turn left / look down / turn right below.
 *
 * Like the move pad, this is a VIEW of shared rotation state plus one input
 * source among two (pad, agent rotation) — `activeRotations` drives the
 * highlight no matter who is turning the camera (R8).
 */

interface PadKey {
  label: string
  direction: RotateDirection
  gridArea: string
  title: string
}

const KEYS: PadKey[] = [
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
    <div
      className="grid gap-1 select-none"
      style={{ gridTemplateColumns: 'repeat(3, 2.25rem)', gridTemplateRows: 'repeat(2, 2.25rem)' }}
      aria-label="Rotate pad"
    >
      {KEYS.map((k) => {
        const active = activeRotations.has(k.direction)
        return (
          <button
            key={k.direction}
            type="button"
            title={k.title}
            disabled={disabled}
            style={{ gridArea: k.gridArea }}
            className={[
              'rounded-[2px] border font-mono text-[12px] transition-colors duration-75',
              active
                ? 'bg-accent-cyan/90 text-white border-accent-cyan'
                : 'bg-bg-elevated/85 text-text-dim border-border-mid hover:text-text-primary hover:border-border-active',
              disabled ? 'opacity-40 cursor-default' : 'cursor-pointer',
            ].join(' ')}
            onPointerDown={(e) => {
              e.preventDefault()
              ;(e.target as HTMLElement).setPointerCapture?.(e.pointerId)
              onInput(k.direction, true)
            }}
            onPointerUp={() => onInput(k.direction, false)}
            onPointerCancel={() => onInput(k.direction, false)}
            onPointerLeave={() => {
              if (activeRotations.has(k.direction)) onInput(k.direction, false)
            }}
          >
            {k.label}
          </button>
        )
      })}
    </div>
  )
}
