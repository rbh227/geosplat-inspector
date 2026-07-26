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

/** Base (state-independent) title for each action row — erase's "ON" suffix is applied at render time. */
// eslint-disable-next-line react-refresh/only-export-components
export const ACTION_TITLES: Record<keyof typeof ACTION_DESCRIPTIONS, string> = {
  erase: 'Erase mode',
  delete: 'Delete selected',
  keep: 'Keep only selected',
  invert: 'Invert selection',
  clear: 'Clear selection',
  undo: 'Undo',
  redo: 'Redo',
}

/**
 * Collapsed-rail tooltip for a row: just the title when there's no description,
 * otherwise "title — description" (the format the tool rows use when help text
 * isn't shown inline). Shared by every rail row so collapsed and expanded states
 * always agree on the same copy.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function describedTooltip(title: string, description?: string): string {
  return description ? `${title} — ${description}` : title
}

/** Collapsed tooltip for an action-button row, built from the same title/description this component renders. */
// eslint-disable-next-line react-refresh/only-export-components
export function actionTooltip(key: keyof typeof ACTION_DESCRIPTIONS): string {
  return describedTooltip(ACTION_TITLES[key], ACTION_DESCRIPTIONS[key])
}

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

/**
 * One rail row: a centered RailButton plus, when `showHelp` is on, an inline
 * title/description block. Every row — tool, erase, and action button — goes
 * through this so collapsed alignment and the help-text treatment stay identical
 * across the whole rail (R1 alignment fix).
 */
function RailRow({
  title,
  description,
  showHelp,
  active = false,
  activeClass,
  disabled = false,
  onClick,
  children,
}: {
  title: string
  description?: string
  showHelp: boolean
  active?: boolean
  activeClass?: string
  disabled?: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <div className="flex items-center gap-2 px-[3px]">
      <RailButton
        title={showHelp ? title : describedTooltip(title, description)}
        active={active}
        activeClass={activeClass}
        disabled={disabled}
        onClick={onClick}
      >
        {children}
      </RailButton>
      {showHelp && description && (
        <div className="min-w-0 flex-1 leading-tight">
          <div className="text-[10px] font-medium text-text-primary">{title}</div>
          <div className="text-[9px] text-text-dim">{description}</div>
        </div>
      )}
    </div>
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
      <RailRow
        title="Pointer / navigate (drag rotates the view)"
        showHelp={showHelp}
        active={activeTool === null}
        disabled={disabled}
        onClick={() => onToolChange(null)}
      >
        <MousePointer2 size={15} />
      </RailRow>

      <div className="my-1 h-px w-5 bg-border-mid" />

      {TOOLS.map(({ tool, icon: Icon, title, description }) => (
        <RailRow
          key={tool}
          title={title}
          description={description}
          showHelp={showHelp}
          active={activeTool === tool}
          disabled={disabled}
          onClick={() => onToolChange(activeTool === tool ? null : tool)}
        >
          <Icon size={15} />
        </RailRow>
      ))}

      {/* Erase mode: a modifier on the tools above — gestures delete on commit (R1) */}
      <RailRow
        title={eraseMode ? `${ACTION_TITLES.erase}: ON` : ACTION_TITLES.erase}
        description={ACTION_DESCRIPTIONS.erase}
        showHelp={showHelp}
        active={eraseMode}
        activeClass="bg-red-500/85 text-white"
        disabled={disabled}
        onClick={() => onEraseModeChange(!eraseMode)}
      >
        <Eraser size={15} />
      </RailRow>

      <div className="my-1 h-px w-5 bg-border-mid" />

      <RailRow
        title={ACTION_TITLES.delete}
        description={ACTION_DESCRIPTIONS.delete}
        showHelp={showHelp}
        disabled={disabled || !hasSelection}
        onClick={onDeleteSelection}
      >
        <Trash2 size={15} />
      </RailRow>
      <RailRow
        title={ACTION_TITLES.keep}
        description={ACTION_DESCRIPTIONS.keep}
        showHelp={showHelp}
        disabled={disabled || !hasSelection}
        onClick={onKeepSelection}
      >
        <Crop size={15} />
      </RailRow>
      <RailRow
        title={ACTION_TITLES.invert}
        description={ACTION_DESCRIPTIONS.invert}
        showHelp={showHelp}
        disabled={disabled}
        onClick={onInvertSelection}
      >
        <FlipHorizontal2 size={15} />
      </RailRow>
      <RailRow
        title={ACTION_TITLES.clear}
        description={ACTION_DESCRIPTIONS.clear}
        showHelp={showHelp}
        disabled={disabled || !hasSelection}
        onClick={onClearSelection}
      >
        <XCircle size={15} />
      </RailRow>

      <div className="my-1 h-px w-5 bg-border-mid" />

      <RailRow
        title={ACTION_TITLES.undo}
        description={ACTION_DESCRIPTIONS.undo}
        showHelp={showHelp}
        disabled={disabled}
        onClick={onUndo}
      >
        <Undo2 size={15} />
      </RailRow>
      <RailRow
        title={ACTION_TITLES.redo}
        description={ACTION_DESCRIPTIONS.redo}
        showHelp={showHelp}
        disabled={disabled}
        onClick={onRedo}
      >
        <Redo2 size={15} />
      </RailRow>

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
