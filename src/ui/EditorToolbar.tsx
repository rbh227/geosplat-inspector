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
  Scissors,
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
  cropBoxCount?: number
  onCropToBox?: () => void
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
  { tool: 'cropBox', icon: Scissors, title: 'Crop box', description: 'Place a box, move and resize it, then delete everything outside it.' },
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

/** The six selection/history actions that render below the erase toggle. */
type SelectionActionKey = Exclude<keyof typeof ACTION_DESCRIPTIONS, 'erase'>

/**
 * Data-driven action rows — mirrors `TOOLS`. The component maps over this
 * instead of hand-writing a `<RailRow>` per action, so a row physically
 * cannot exist without its title/description, and can't silently drop one.
 */
// eslint-disable-next-line react-refresh/only-export-components
export const ACTIONS: Array<{
  key: SelectionActionKey
  icon: typeof Trash2
  title: string
  description: string
  /** Which divider-separated group the row renders in. */
  group: 'edit' | 'history'
  /** Whether this row is disabled given selection state (on top of the whole-rail `disabled` prop). */
  disabledWhen: (ctx: { hasSelection: boolean }) => boolean
}> = [
  { key: 'delete', icon: Trash2, title: ACTION_TITLES.delete, description: ACTION_DESCRIPTIONS.delete, group: 'edit', disabledWhen: ({ hasSelection }) => !hasSelection },
  { key: 'keep', icon: Crop, title: ACTION_TITLES.keep, description: ACTION_DESCRIPTIONS.keep, group: 'edit', disabledWhen: ({ hasSelection }) => !hasSelection },
  { key: 'invert', icon: FlipHorizontal2, title: ACTION_TITLES.invert, description: ACTION_DESCRIPTIONS.invert, group: 'edit', disabledWhen: () => false },
  { key: 'clear', icon: XCircle, title: ACTION_TITLES.clear, description: ACTION_DESCRIPTIONS.clear, group: 'edit', disabledWhen: ({ hasSelection }) => !hasSelection },
  { key: 'undo', icon: Undo2, title: ACTION_TITLES.undo, description: ACTION_DESCRIPTIONS.undo, group: 'history', disabledWhen: () => false },
  { key: 'redo', icon: Redo2, title: ACTION_TITLES.redo, description: ACTION_DESCRIPTIONS.redo, group: 'history', disabledWhen: () => false },
]

/** Shared wrapper classes for one rail row — `RailRow` and the standalone help-toggle row both use this. */
const ROW_WRAPPER_CLASS = 'flex items-center gap-2 px-[3px]'

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
    <div className={ROW_WRAPPER_CLASS}>
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
  cropBoxCount,
  onCropToBox,
}: EditorToolbarProps) {
  const hasSelection = selectionCount > 0
  const [showHelp, setShowHelp] = useState(false)

  const actionHandlers: Record<SelectionActionKey, () => void> = {
    delete: onDeleteSelection,
    keep: onKeepSelection,
    invert: onInvertSelection,
    clear: onClearSelection,
    undo: onUndo,
    redo: onRedo,
  }

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

      {activeTool === 'cropBox' && (
        <div className="flex flex-col items-stretch gap-1 px-[3px] py-1">
          <button
            type="button"
            onClick={onCropToBox}
            disabled={disabled || !cropBoxCount}
            className="rounded-[2px] bg-accent-cyan/90 px-1 py-1 text-[9px] font-medium text-white disabled:opacity-35"
          >
            Crop to box
          </button>
          <div className="text-center font-mono text-[9px] text-text-dim">
            ~{(cropBoxCount ?? 0).toLocaleString()} inside
          </div>
        </div>
      )}

      {/* Erase mode: a modifier on the tools above — gestures delete on commit (R1) */}
      <RailRow
        title={eraseMode ? `${ACTION_TITLES.erase}: ON (click to turn off)` : ACTION_TITLES.erase}
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

      {ACTIONS.filter((a) => a.group === 'edit').map(({ key, icon: Icon, title, description, disabledWhen }) => (
        <RailRow
          key={key}
          title={title}
          description={description}
          showHelp={showHelp}
          disabled={disabled || disabledWhen({ hasSelection })}
          onClick={actionHandlers[key]}
        >
          <Icon size={15} />
        </RailRow>
      ))}

      <div className="my-1 h-px w-5 bg-border-mid" />

      {ACTIONS.filter((a) => a.group === 'history').map(({ key, icon: Icon, title, description, disabledWhen }) => (
        <RailRow
          key={key}
          title={title}
          description={description}
          showHelp={showHelp}
          disabled={disabled || disabledWhen({ hasSelection })}
          onClick={actionHandlers[key]}
        >
          <Icon size={15} />
        </RailRow>
      ))}

      <div className={`mt-auto mb-2 ${ROW_WRAPPER_CLASS}`}>
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
