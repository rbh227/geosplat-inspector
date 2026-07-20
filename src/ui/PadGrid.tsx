/**
 * Shared button grid for the on-screen input pads (move/rotate). Each button
 * is a pointer-captured momentary switch; `activeSet` drives the highlight no
 * matter which input source set it (pad, keyboard, agent) — R8/R13.
 */

export interface PadKey<D extends string> {
  label: string
  direction: D
  gridArea: string
  title: string
}

interface PadGridProps<D extends string> {
  keys: ReadonlyArray<PadKey<D>>
  activeSet: ReadonlySet<D>
  onInput: (direction: D, active: boolean) => void
  disabled?: boolean
  ariaLabel: string
}

export default function PadGrid<D extends string>({
  keys, activeSet, onInput, disabled = false, ariaLabel,
}: PadGridProps<D>) {
  return (
    <div
      className="grid gap-1 select-none"
      style={{ gridTemplateColumns: 'repeat(3, 2.25rem)', gridTemplateRows: 'repeat(2, 2.25rem)' }}
      aria-label={ariaLabel}
    >
      {keys.map((k) => {
        const active = activeSet.has(k.direction)
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
              if (activeSet.has(k.direction)) onInput(k.direction, false)
            }}
          >
            {k.label}
          </button>
        )
      })}
    </div>
  )
}
