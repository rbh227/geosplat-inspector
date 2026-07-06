import { useEffect, useRef, useState } from 'react'
import { ChevronDown, Download, FolderOpen, Orbit, PanelRight, Plane, RotateCcw } from 'lucide-react'
import { DEMO_SPLATS, type DemoSplat } from '../demos'
import { isBackendLoadable } from '../backend/client'

/** Workflow stages (R12): Clean = full editor, Understand = look-only analyst. */
export type Stage = 'clean' | 'understand'

interface TopBarProps {
  stage: Stage
  onStageChange: (stage: Stage) => void
  /** True while an agent run is active — the switcher locks (AE2 guard). */
  stageLocked: boolean
  navigationMode: 'orbit' | 'fly'
  onToggleNavMode: () => void
  rightOpen: boolean
  onToggleRight: () => void
  onImport: () => void
  onLoadDemo: (demo: DemoSplat) => void
  onResetView: () => void
}

/**
 * Flat single-row toolbar in the Postshot mold: small labeled buttons on the
 * left, stage switcher, wordmark on the right. Sample scenes live behind the
 * Samples dropdown — no demo grid in the viewport.
 */
export default function TopBar({
  stage, onStageChange, stageLocked,
  navigationMode, onToggleNavMode,
  rightOpen, onToggleRight, onImport, onLoadDemo, onResetView,
}: TopBarProps) {
  const [samplesOpen, setSamplesOpen] = useState(false)
  const samplesRef = useRef<HTMLDivElement>(null)

  // click-away closes the dropdown
  useEffect(() => {
    if (!samplesOpen) return
    const close = (e: MouseEvent) => {
      if (!samplesRef.current?.contains(e.target as Node)) setSamplesOpen(false)
    }
    window.addEventListener('mousedown', close)
    return () => window.removeEventListener('mousedown', close)
  }, [samplesOpen])

  return (
    <div className="h-[38px] flex-none flex items-center justify-between px-2 bg-bg-topbar border-b border-border-panel select-none">
      {/* Left: file actions */}
      <div className="flex items-center gap-1">
        <button onClick={onImport} className="topbar-btn">
          <Download size={12} />Import…
        </button>

        {/* Samples dropdown */}
        <div ref={samplesRef} className="relative">
          <button onClick={() => setSamplesOpen((p) => !p)} className="topbar-btn">
            <FolderOpen size={12} />Samples<ChevronDown size={11} />
          </button>
          {samplesOpen && (
            <div className="absolute left-0 top-[30px] z-50 min-w-[240px] border border-border-mid bg-bg-surface py-1 shadow-lg shadow-black/50">
              {DEMO_SPLATS.map((demo) => (
                <button
                  key={demo.file}
                  onClick={() => { setSamplesOpen(false); onLoadDemo(demo) }}
                  className="flex w-full flex-col items-start gap-0.5 px-3 py-1.5 text-left hover:bg-bg-hover cursor-pointer"
                >
                  <span className="text-[12px] text-text-primary">
                    {demo.name}
                    {!isBackendLoadable(demo.file) && (
                      <span className="ml-1.5 text-[10px] text-text-muted">(view only)</span>
                    )}
                  </span>
                  <span className="text-[10.5px] text-text-dim">{demo.description}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        <span className="mx-1 h-[16px] w-px bg-border-mid" />

        <button onClick={onResetView} className="topbar-btn">
          <RotateCcw size={12} />Reset view
        </button>
        <button
          onClick={onToggleNavMode}
          className="topbar-btn"
          title={navigationMode === 'fly' ? 'Fly mode (WASD + drag to look) — click for orbit' : 'Orbit mode — click for fly (WASD)'}
        >
          {navigationMode === 'fly' ? <Plane size={12} /> : <Orbit size={12} />}
          {navigationMode === 'fly' ? 'Fly' : 'Orbit'}
        </button>
      </div>

      {/* Center: stage switcher (operator-controlled, never the agent — R12) */}
      <div
        className="flex items-center border border-border-mid rounded-[3px] overflow-hidden"
        title={stageLocked ? 'Stage switching is locked while the agent is running' : 'Workflow stage'}
      >
        {(['clean', 'understand'] as const).map((s) => (
          <button
            key={s}
            onClick={() => onStageChange(s)}
            disabled={stageLocked}
            className={[
              'px-3 h-[24px] text-[11px] capitalize transition-colors',
              stage === s
                ? 'bg-accent-cyan/90 text-white'
                : 'bg-bg-elevated text-text-dim hover:text-text-secondary',
              stageLocked ? 'opacity-50 cursor-default' : 'cursor-pointer',
            ].join(' ')}
          >
            {s}
          </button>
        ))}
      </div>

      {/* Right: panel toggle + wordmark (Postshot puts the brand here) */}
      <div className="flex items-center gap-2">
        <button
          onClick={onToggleRight}
          className={`topbar-icon-btn ${rightOpen ? 'text-text-primary' : ''}`}
          title="Toggle agent panel"
        >
          <PanelRight size={13} />
        </button>
        <span className="pr-1 text-[13px] font-semibold tracking-tight text-text-secondary">
          geosplat
        </span>
      </div>

      <style>{`
        .topbar-btn {
          display: inline-flex; align-items: center; gap: 5px;
          height: 26px; padding: 0 9px; border-radius: 3px;
          border: 1px solid var(--color-border-mid);
          background: var(--color-bg-elevated);
          color: var(--color-text-secondary); font-size: 11.5px; cursor: pointer;
          font-family: var(--font-sans);
          transition: background 120ms, border-color 120ms, color 120ms;
        }
        .topbar-btn:hover {
          background: var(--color-bg-hover);
          border-color: var(--color-border-active);
          color: var(--color-text-primary);
        }
        .topbar-icon-btn {
          display: inline-flex; align-items: center; justify-content: center;
          width: 26px; height: 26px; border-radius: 3px;
          border: 1px solid var(--color-border-mid);
          background: var(--color-bg-elevated);
          color: var(--color-text-dim); cursor: pointer;
          transition: background 120ms, color 120ms, border-color 120ms;
        }
        .topbar-icon-btn:hover {
          background: var(--color-bg-hover);
          color: var(--color-text-primary);
          border-color: var(--color-border-active);
        }
      `}</style>
    </div>
  )
}
