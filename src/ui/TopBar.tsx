import { Download, RotateCcw, PanelLeft, PanelRight } from 'lucide-react'
import type { ViewerState } from '../types/viewer'
import AnimatedNumber from './AnimatedNumber'

interface TopBarProps {
  state: ViewerState
  leftOpen: boolean
  rightOpen: boolean
  onToggleLeft: () => void
  onToggleRight: () => void
  onImport: () => void
  onResetView: () => void
}

function fpsColor(fps: number): string {
  if (fps > 50) return 'text-text-primary'
  if (fps > 25) return 'text-accent-amber'
  return 'text-accent-red'
}

export default function TopBar({
  state, leftOpen, rightOpen,
  onToggleLeft, onToggleRight, onImport, onResetView,
}: TopBarProps) {
  return (
    <div className="h-[46px] flex-none flex items-center justify-between px-3.5 bg-bg-topbar border-b border-border-panel">
      {/* Left: branding + stats */}
      <div className="flex items-center gap-3.5">
        {/* Logo */}
        <div className="flex items-center gap-2 pr-3.5 border-r border-border-mid">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#5C6A77" strokeWidth="1.7" strokeLinejoin="round">
            <path d="M21 8l-9-5-9 5v8l9 5 9-5V8z"/><path d="M3 8l9 5 9-5"/><path d="M12 13v9"/>
          </svg>
          <span className="font-mono text-xs font-semibold tracking-wide text-text-secondary">GEOSPLAT</span>
          <span className="font-mono text-[9px] font-medium tracking-widest text-accent-cyan border border-accent-cyan/40 rounded px-1 py-px">
            INSPECTOR
          </span>
        </div>

        {/* File */}
        <div className="flex items-center gap-1.5 font-mono text-[11.5px]">
          <span className="text-text-dim tracking-wide">FILE</span>
          <span className="text-text-primary">{state.fileName ?? 'No scene'}</span>
        </div>
        <span className="w-px h-4 bg-border-mid" />

        {/* Splats */}
        <div className="flex items-center gap-1.5 font-mono text-[11.5px]">
          <span className="text-text-dim tracking-wide">SPLATS</span>
          <AnimatedNumber value={state.splatCount} className="text-text-primary" />
        </div>
        <span className="w-px h-4 bg-border-mid" />

        {/* FPS */}
        <div className="flex items-center gap-1.5 font-mono text-[11.5px]">
          <span className="text-text-dim tracking-wide">FPS</span>
          <span className={fpsColor(state.fps)}>{Math.round(state.fps)}</span>
        </div>
        <span className="w-px h-4 bg-border-mid" />

        {/* Camera */}
        <div className="flex items-center gap-1.5 font-mono text-[11.5px]">
          <span className="text-text-dim tracking-wide">CAM</span>
          <span className="text-text-secondary">
            {state.cameraPosition[0].toFixed(1)}, {state.cameraPosition[1].toFixed(1)}, {state.cameraPosition[2].toFixed(1)}
          </span>
        </div>
      </div>

      {/* Right: actions + panel toggles */}
      <div className="flex items-center gap-1.5">
        <button onClick={onImport} className="topbar-btn">
          <Download size={14} />Import
        </button>
        <button onClick={onResetView} className="topbar-btn">
          <RotateCcw size={14} />Reset view
        </button>
        <span className="w-px h-[18px] bg-border-mid mx-1" />
        <button onClick={onToggleLeft} className={`topbar-icon-btn ${leftOpen ? 'text-text-primary' : ''}`} title="Toggle capabilities">
          <PanelLeft size={15} />
        </button>
        <button onClick={onToggleRight} className={`topbar-icon-btn ${rightOpen ? 'text-text-primary' : ''}`} title="Toggle inspector">
          <PanelRight size={15} />
        </button>
      </div>

      <style>{`
        .topbar-btn {
          display: inline-flex; align-items: center; gap: 6px;
          height: 29px; padding: 0 11px; border-radius: 5px;
          border: 1px solid var(--color-border-active); background: var(--color-bg-elevated);
          color: var(--color-text-primary); font-size: 12px; font-weight: 500; cursor: pointer;
          font-family: var(--font-sans);
          transition: background 150ms, border-color 150ms;
        }
        .topbar-btn:hover { background: var(--color-bg-hover); border-color: #36444F; }
        .topbar-icon-btn {
          display: inline-flex; align-items: center; justify-content: center;
          width: 30px; height: 29px; border-radius: 5px;
          border: 1px solid var(--color-border-active); background: var(--color-bg-elevated);
          color: var(--color-text-secondary); cursor: pointer;
          transition: background 150ms, color 150ms;
        }
        .topbar-icon-btn:hover { background: var(--color-bg-hover); color: var(--color-text-primary); }
      `}</style>
    </div>
  )
}
