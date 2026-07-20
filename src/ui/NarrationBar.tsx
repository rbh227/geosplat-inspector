import type { ViewerState } from '../types/viewer'

interface NarrationBarProps {
  state: ViewerState
  isRunning: boolean
  narration: string
  step: number
  maxSteps: number
}

/**
 * Thin always-visible status bar (Postshot mold): agent status + narration on
 * the left, scene/camera stats on the right. Dense, flat, small type.
 */
export default function NarrationBar({ state, isRunning, narration, step, maxSteps }: NarrationBarProps) {
  return (
    <div className="h-[24px] flex-none flex items-center gap-3 px-2.5 bg-bg-topbar border-t border-border-panel text-[11px] select-none">
      {/* Agent status */}
      <span className={`flex-none font-mono text-[10px] tracking-wide ${isRunning ? 'text-accent-cyan' : 'text-text-muted'}`}>
        {isRunning ? '● RUNNING' : '○ IDLE'}
      </span>
      {step > 0 && (
        <span className="flex-none font-mono text-[10px] text-text-dim">
          step {step}/{maxSteps}
        </span>
      )}

      {/* Narration */}
      <span className="flex-1 min-w-0 truncate text-text-secondary">
        {narration || 'Ready'}
      </span>

      {/* Scene / camera stats */}
      <span className="flex-none text-text-dim">
        {state.fileName ?? 'no scene'}
      </span>
      <span className="flex-none h-[12px] w-px bg-border-mid" />
      <span className="flex-none text-text-dim">
        {state.splatCount.toLocaleString()} splats
      </span>
      <span className="flex-none h-[12px] w-px bg-border-mid" />
      <span className={`flex-none ${state.fps > 50 ? 'text-text-dim' : state.fps > 25 ? 'text-accent-amber' : 'text-accent-red'}`}>
        {Math.round(state.fps)} fps
      </span>
      <span className="flex-none h-[12px] w-px bg-border-mid" />
      <span className="flex-none font-mono text-[10px] text-text-muted">
        {state.cameraPosition.map((v) => v.toFixed(1)).join(', ')}
      </span>
    </div>
  )
}
