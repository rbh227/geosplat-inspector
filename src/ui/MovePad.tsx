import type { MoveDirection } from '../types/viewer.ts'

/**
 * On-screen WASD movement pad (R8). Six buttons in a 3x3 grid:
 * Q (up) / W (forward) / E (down) on top, A / S / D below.
 *
 * The pad is a VIEW of the shared movement state plus one input source among
 * three (keyboard, pad, agent move_camera) — `activeDirections` drives the
 * highlight no matter who is moving, which is what makes agent flight
 * watchable on the pad (R13/SC2).
 */

interface PadKey {
  label: string
  direction: MoveDirection
  gridArea: string
  title: string
}

const KEYS: PadKey[] = [
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
    <div
      className="absolute bottom-3 right-3 z-20 grid gap-1 select-none"
      style={{ gridTemplateColumns: 'repeat(3, 2.25rem)', gridTemplateRows: 'repeat(2, 2.25rem)' }}
      aria-label="Movement pad"
    >
      {KEYS.map((k) => {
        const active = activeDirections.has(k.direction)
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
              if (activeDirections.has(k.direction)) onInput(k.direction, false)
            }}
          >
            {k.label}
          </button>
        )
      })}
    </div>
  )
}
