interface NarrationBarProps {
  isRunning: boolean
  narration: string
  step: number
  maxSteps: number
  onPause?: () => void
}

function WaveBars() {
  const delays = [0, 0.1, 0.25, 0.15, 0.35, 0.05, 0.3]
  return (
    <div className="flex items-end gap-[2px] h-5 flex-none">
      {delays.map((d, i) => (
        <span
          key={i}
          className="w-[2.5px] h-full bg-accent-cyan rounded-sm wave-bar"
          style={{ animation: `wave 0.9s ease-in-out infinite ${d}s` }}
        />
      ))}
    </div>
  )
}

export default function NarrationBar({ isRunning, narration, step, maxSteps, onPause }: NarrationBarProps) {
  if (!isRunning && !narration) return null

  return (
    <div className="h-[58px] flex-none flex items-center gap-4 px-[18px] bg-[#0A0E12] border-t border-border-subtle">
      {/* Status indicator */}
      <div className="flex items-center gap-2.5 flex-none">
        <span className="w-2 h-2 rounded-full bg-accent-cyan animate-core-pulse" />
        <span className="font-mono text-[10.5px] font-semibold tracking-[0.16em] text-accent-cyan">
          {isRunning ? 'INSPECTING' : 'IDLE'}
        </span>
        <span className="w-px h-[18px] bg-border-mid" />
      </div>

      {/* Narration text */}
      <div className="flex-1 min-w-0 flex items-center">
        <span className="text-[13.5px] text-text-primary whitespace-nowrap overflow-hidden text-ellipsis">
          {narration || 'Ready'}
        </span>
        {isRunning && (
          <span className="inline-block w-[7px] h-[15px] bg-accent-cyan ml-1.5 animate-caret" />
        )}
      </div>

      {/* Wave bars (while running) */}
      {isRunning && <WaveBars />}

      {/* Step counter */}
      {step > 0 && (
        <span className="font-mono text-[11px] text-text-dim tracking-wide flex-none">
          STEP <span className="text-text-secondary">{String(step).padStart(2, '0')}</span> / {maxSteps}
        </span>
      )}

      {/* Pause button */}
      {isRunning && onPause && (
        <button
          onClick={onPause}
          title="Pause agent"
          className="flex-none w-[30px] h-[30px] flex items-center justify-center border border-border-active bg-bg-elevated text-text-secondary rounded-[5px] cursor-pointer hover:bg-bg-hover hover:text-text-primary transition-colors"
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor">
            <rect x="6" y="5" width="4" height="14" rx="1"/>
            <rect x="14" y="5" width="4" height="14" rx="1"/>
          </svg>
        </button>
      )}
    </div>
  )
}
