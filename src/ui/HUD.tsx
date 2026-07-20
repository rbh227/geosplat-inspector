import type { ViewerState } from '../types/viewer'
import AnimatedNumber from './AnimatedNumber'

interface HUDProps {
  state: ViewerState
}

function fpsColor(fps: number): string {
  if (fps > 50) return 'text-accent-green'
  if (fps > 25) return 'text-accent-amber'
  return 'text-accent-red'
}

function formatCoord(n: number): string {
  return n.toFixed(1)
}

export default function HUD({ state }: HUDProps) {
  const { fileName, splatCount, fps, cameraPosition, isLoading } = state

  return (
    <div className="absolute top-4 left-4 z-10 flex flex-wrap items-start gap-2 pointer-events-none select-none">
      {/* File name */}
      <div className="panel-dense px-3 py-1.5 flex items-center gap-2 pointer-events-auto">
        <span className="text-text-dim text-xs">FILE</span>
        <span className="font-mono text-xs text-text-primary truncate max-w-48">
          {isLoading ? (
            <span className="loading-shimmer inline-block w-24 h-3 rounded" />
          ) : (
            fileName ?? 'No scene loaded'
          )}
        </span>
      </div>

      {/* Splat count */}
      <div className="panel-dense px-3 py-1.5 flex items-center gap-2 pointer-events-auto">
        <span className="text-text-dim text-xs">SPLATS</span>
        <AnimatedNumber
          value={splatCount}
          className="font-mono text-xs text-accent-cyan"
        />
      </div>

      {/* FPS */}
      <div className="panel-dense px-3 py-1.5 flex items-center gap-2 pointer-events-auto">
        <span className="text-text-dim text-xs">FPS</span>
        <span className={`font-mono text-xs ${fpsColor(fps)}`}>
          {Math.round(fps)}
        </span>
      </div>

      {/* Camera position */}
      <div className="panel-dense px-3 py-1.5 flex items-center gap-2 pointer-events-auto">
        <span className="text-text-dim text-xs">CAM</span>
        <span className="font-mono text-xs text-text-secondary">
          {formatCoord(cameraPosition[0])},{' '}
          {formatCoord(cameraPosition[1])},{' '}
          {formatCoord(cameraPosition[2])}
        </span>
      </div>
    </div>
  )
}
