import { useState } from 'react'
import {
  Box,
  Brush,
  CircleDashed,
  Hexagon,
  Eraser,
  Lasso,
  MousePointer2,
  Redo2,
  Trash2,
  Undo2,
  XCircle,
  FlipHorizontal2,
  Crop,
  HelpCircle,
} from 'lucide-react'
import type { SelectionTool } from '../viewer/SelectionOverlay.tsx'

/**
 * Left vertical tool rail (R1/R4/R5) — classic editor chrome in the Postshot
 * mold: quiet icon buttons, active tool highlighted, action group below.
 */

interface EditorToolbarProps {
  activeTool: SelectionTool | null
  onToolChange: (tool: SelectionTool | null) => void
  eraseMode: boolean
  onEraseModeChange: (on: boolean) => void
  selectionCount: number
  onDeleteSelection: () => void
  onKeepSelection: () => void
  onInvertSelection: () => void
  onClearSelection: () => void
  onUndo: () => void
  onRedo: () => void
  disabled?: boolean
}

// eslint-disable-next-line react-refresh/only-export-components
export const TOOLS: Array<{
  tool: SelectionTool
  icon: typeof Brush
  title: string
  description: string
}> = [
  { tool: 'brush', icon: Brush, title: 'Brush select', description: 'Paint over splats to select them. [ and ] resize the brush.' },
  { tool: 'lasso', icon: Lasso, title: 'Lasso select', description: 'Draw a freehand outline; everything inside it is selected.' },
  { tool: 'polygon', icon: Hexagon, title: 'Polygon select', description: 'Click points to outline a region; double-click to close it.' },
  { tool: 'sphere', icon: CircleDashed, title: 'Sphere select', description: 'Drag out a sphere; splats inside it are selected.' },
  { tool: 'box', icon: Box, title: 'Box select', description: 'Drag out a box; splats inside it are selected.' },
]

// eslint-disable-next-line react-refresh/only-export-components
export const ACTION_DESCRIPTIONS = {
  erase: 'Selections delete the moment you finish the gesture, instead of building up.',
  delete: 'Delete the selected splats.',
  keep: 'Delete everything except the selection.',
  invert: 'Swap what is selected for what is not.',
  clear: 'Deselect everything; nothing is deleted.',
  undo: 'Step back one edit.',
  redo: 'Re-apply the edit you just undid.',
} as const

function RailButton({
  title, onClick, active = false, disabled = false, activeClass = 'bg-accent-cyan/90 text-white', children,
}: {
  title: string
  onClick: () => void
  active?: boolean
  disabled?: boolean
  /** Override for destructive modes (erase) so their active state never reads as tool selection. */
  activeClass?: string
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      title={title}
      disabled={disabled}
      onClick={onClick}
      className={[
        'flex h-7 w-7 items-center justify-center rounded-[2px] transition-colors duration-75',
        active
          ? activeClass
          : 'text-text-dim hover:bg-bg-hover hover:text-text-primary',
        disabled ? 'opacity-35 cursor-default' : 'cursor-pointer',
      ].join(' ')}
    >
      {children}
    </button>
  )
}

export default function EditorToolbar({
  activeTool,
  onToolChange,
  eraseMode,
  onEraseModeChange,
  selectionCount,
  onDeleteSelection,
  onKeepSelection,
  onInvertSelection,
  onClearSelection,
  onUndo,
  onRedo,
  disabled = false,
}: EditorToolbarProps) {
  const hasSelection = selectionCount > 0
  const [showHelp, setShowHelp] = useState(false)
  return (
    <div className={`absolute left-0 top-0 bottom-0 z-20 flex ${showHelp ? 'w-[230px]' : 'w-[34px]'} flex-col items-stretch gap-0.5 border-r border-border-panel bg-bg-topbar pt-2 transition-[width] duration-100`}>
      {/* Pointer mode: no tool active — drags reach the camera controls (R4/R5) */}
      <RailButton
        title="Pointer / navigate (drag rotates the view)"
        active={activeTool === null}
        disabled={disabled}
        onClick={() => onToolChange(null)}
      >
        <MousePointer2 size={15} />
      </RailButton>

      <div className="my-1 h-px w-5 bg-border-mid" />

      {TOOLS.map(({ tool, icon: Icon, title, description }) => (
        <div key={tool} className="flex items-center gap-2 px-[3px]">
          <RailButton
            title={showHelp ? title : `${title} — ${description}`}
            active={activeTool === tool}
            disabled={disabled}
            onClick={() => onToolChange(activeTool === tool ? null : tool)}
          >
            <Icon size={15} />
          </RailButton>
          {showHelp && (
            <div className="min-w-0 flex-1 leading-tight">
              <div className="text-[10px] font-medium text-text-primary">{title}</div>
              <div className="text-[9px] text-text-dim">{description}</div>
            </div>
          )}
        </div>
      ))}

      {/* Erase mode: a modifier on the tools above — gestures delete on commit (R1) */}
      <RailButton
        title={eraseMode ? 'Erase mode ON — selections delete immediately (click to turn off)' : 'Erase mode — selections delete immediately'}
        active={eraseMode}
        activeClass="bg-red-500/85 text-white"
        disabled={disabled}
        onClick={() => onEraseModeChange(!eraseMode)}
      >
        <Eraser size={15} />
      </RailButton>

      <div className="my-1 h-px w-5 bg-border-mid" />

      <RailButton title="Delete selected" disabled={disabled || !hasSelection} onClick={onDeleteSelection}>
        <Trash2 size={15} />
      </RailButton>
      <RailButton title="Keep only selected" disabled={disabled || !hasSelection} onClick={onKeepSelection}>
        <Crop size={15} />
      </RailButton>
      <RailButton title="Invert selection" disabled={disabled} onClick={onInvertSelection}>
        <FlipHorizontal2 size={15} />
      </RailButton>
      <RailButton title="Clear selection" disabled={disabled || !hasSelection} onClick={onClearSelection}>
        <XCircle size={15} />
      </RailButton>

      <div className="my-1 h-px w-5 bg-border-mid" />

      <RailButton title="Undo" disabled={disabled} onClick={onUndo}>
        <Undo2 size={15} />
      </RailButton>
      <RailButton title="Redo" disabled={disabled} onClick={onRedo}>
        <Redo2 size={15} />
      </RailButton>

      <div className="mt-auto mb-2 flex items-center gap-2 px-[3px]">
        <RailButton
          title={showHelp ? 'Hide tool descriptions' : 'Show tool descriptions'}
          active={showHelp}
          onClick={() => setShowHelp(!showHelp)}
        >
          <HelpCircle size={15} />
        </RailButton>
        {showHelp && <div className="text-[9px] text-text-dim">Hide descriptions</div>}
      </div>

      {hasSelection && (
        <div className="mt-1 px-0.5 text-center font-mono text-[9px] leading-tight text-text-dim">
          {selectionCount.toLocaleString()}
        </div>
      )}
    </div>
  )
}
