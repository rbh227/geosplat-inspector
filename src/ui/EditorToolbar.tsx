import {
  Box,
  Brush,
  CircleDashed,
  Hexagon,
  Lasso,
  Redo2,
  Trash2,
  Undo2,
  XCircle,
  FlipHorizontal2,
  Crop,
} from 'lucide-react'
import type { SelectionTool } from '../viewer/SelectionOverlay.tsx'

/**
 * Left vertical tool rail (R1/R4/R5) — classic editor chrome in the Postshot
 * mold: quiet icon buttons, active tool highlighted, action group below.
 */

interface EditorToolbarProps {
  activeTool: SelectionTool | null
  onToolChange: (tool: SelectionTool | null) => void
  selectionCount: number
  onDeleteSelection: () => void
  onKeepSelection: () => void
  onInvertSelection: () => void
  onClearSelection: () => void
  onUndo: () => void
  onRedo: () => void
  disabled?: boolean
}

const TOOLS: Array<{ tool: SelectionTool; icon: typeof Brush; title: string }> = [
  { tool: 'brush', icon: Brush, title: 'Brush select (resize with [ ])' },
  { tool: 'lasso', icon: Lasso, title: 'Lasso select' },
  { tool: 'polygon', icon: Hexagon, title: 'Polygon select (double-click to close)' },
  { tool: 'sphere', icon: CircleDashed, title: 'Sphere select (drag to size)' },
  { tool: 'box', icon: Box, title: 'Box select (drag to size)' },
]

function RailButton({
  title, onClick, active = false, disabled = false, children,
}: {
  title: string
  onClick: () => void
  active?: boolean
  disabled?: boolean
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
          ? 'bg-accent-cyan/90 text-white'
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
  return (
    <div className="absolute left-0 top-0 bottom-0 z-20 flex w-[34px] flex-col items-center gap-0.5 border-r border-border-panel bg-bg-topbar pt-2">
      {TOOLS.map(({ tool, icon: Icon, title }) => (
        <RailButton
          key={tool}
          title={title}
          active={activeTool === tool}
          disabled={disabled}
          onClick={() => onToolChange(activeTool === tool ? null : tool)}
        >
          <Icon size={15} />
        </RailButton>
      ))}

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

      {hasSelection && (
        <div className="mt-1 px-0.5 text-center font-mono text-[9px] leading-tight text-text-dim">
          {selectionCount.toLocaleString()}
        </div>
      )}
    </div>
  )
}
