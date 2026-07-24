import type { ViewerState } from '../types/viewer'

interface NarrationBarProps {
  state: ViewerState
}

/**
 * Thin always-visible stats bar (Postshot mold): scene/camera stats only.
 * Agent activity lives in the chat panel — this bar never shows run progress.
 */
export default function NarrationBar({ state }: NarrationBarProps) {
  return (
    <div className="h-[24px] flex-none flex items-center gap-3 px-2.5 bg-bg-topbar border-t border-border-panel text-[11px] select-none">
      <span className="flex-1 min-w-0 truncate text-text-dim">
        {state.fileName ?? 'no scene'}
      </span>
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
