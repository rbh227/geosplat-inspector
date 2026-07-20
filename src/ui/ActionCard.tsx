import { Move3d, Eraser, Camera, CheckCircle2 } from 'lucide-react'
import type { AgentAction } from '../types/agent'

interface ActionCardProps {
  action: AgentAction
}

const ACTION_ICONS: Record<AgentAction['type'], React.ComponentType<{ size?: number; className?: string }>> = {
  camera_move: Move3d,
  cleanup: Eraser,
  capture: Camera,
  answer: CheckCircle2,
}

const ACTION_COLORS: Record<AgentAction['type'], string> = {
  camera_move: 'text-accent-cyan',
  cleanup: 'text-accent-amber',
  capture: 'text-accent-cyan',
  answer: 'text-accent-green',
}

export default function ActionCard({ action }: ActionCardProps) {
  const Icon = ACTION_ICONS[action.type]
  const color = ACTION_COLORS[action.type]

  return (
    <div className="panel-dense animate-expand mt-2 p-2.5 flex flex-col gap-2">
      {/* Header row */}
      <div className="flex items-center gap-2">
        <Icon size={14} className={color} />
        <span className="text-xs font-medium text-text-primary">
          {action.label}
        </span>
        {action.removedCount !== undefined && (
          <span className="ml-auto text-xs font-mono text-accent-amber">
            -{action.removedCount.toLocaleString('en-US')}
          </span>
        )}
      </div>

      {/* Detail text */}
      {action.detail && (
        <p className="text-xs text-text-secondary leading-relaxed">
          {action.detail}
        </p>
      )}

      {/* Before / After thumbnails */}
      {action.before && action.after && (
        <div className="flex gap-2 mt-1">
          <div className="flex-1 flex flex-col gap-1">
            <span className="text-[10px] uppercase text-text-dim">Before</span>
            <img
              src={action.before}
              alt="Before"
              className="w-full rounded border border-border-subtle object-cover aspect-video"
            />
          </div>
          <div className="flex-1 flex flex-col gap-1">
            <span className="text-[10px] uppercase text-text-dim">After</span>
            <img
              src={action.after}
              alt="After"
              className="w-full rounded border border-border-subtle object-cover aspect-video"
            />
          </div>
        </div>
      )}
    </div>
  )
}
