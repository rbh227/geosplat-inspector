import { useState } from 'react'
import { ChevronUp, Undo2, Eraser, Crop } from 'lucide-react'
import Button from './Button'

interface CleanupDrawerProps {
  onCleanOpacity: (threshold: number) => void
  onRemoveOutliers: (k: number) => void
  onCrop: () => void
  onUndo: () => void
  canUndo: boolean
  undoCount: number
  isOpen: boolean
  onToggle: () => void
}

export default function CleanupDrawer({
  onCleanOpacity,
  onRemoveOutliers,
  onCrop,
  onUndo,
  canUndo,
  undoCount,
  isOpen,
  onToggle,
}: CleanupDrawerProps) {
  const [opacityThreshold, setOpacityThreshold] = useState(0.1)
  const [kValue, setKValue] = useState(3)

  return (
    <div className="absolute bottom-4 left-4 z-10 w-[280px]">
      <div className="panel overflow-hidden">
        {/* Header / Toggle */}
        <button
          onClick={onToggle}
          className="
            w-full flex items-center justify-between px-4 py-2.5
            btn-ghost text-left focus-ring
          "
          aria-expanded={isOpen}
        >
          <div className="flex items-center gap-2">
            <Eraser size={14} className="text-accent-amber" />
            <span className="text-sm font-semibold text-text-primary">Cleanup</span>
          </div>
          <ChevronUp
            size={14}
            className={`text-text-dim transition-transform duration-200 ${isOpen ? '' : 'rotate-180'}`}
          />
        </button>

        {/* Collapsible body */}
        {isOpen && (
          <div className="animate-expand px-4 pb-4 flex flex-col gap-3 border-t border-border-subtle pt-3">
            {/* Opacity threshold */}
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <label className="text-xs text-text-secondary">
                  Opacity threshold
                </label>
                <span className="text-xs font-mono text-text-primary">
                  {opacityThreshold.toFixed(2)}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.01"
                  value={opacityThreshold}
                  onChange={(e) => setOpacityThreshold(parseFloat(e.target.value))}
                  className="flex-1 h-1 accent-accent-amber cursor-pointer"
                />
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => onCleanOpacity(opacityThreshold)}
                  className="text-accent-amber border-accent-amber/30 hover:bg-accent-amber-dim"
                >
                  Clean
                </Button>
              </div>
            </div>

            {/* Outlier removal */}
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <label className="text-xs text-text-secondary">
                  Outlier k-neighbors
                </label>
                <span className="text-xs font-mono text-text-primary">
                  {kValue}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="range"
                  min="1"
                  max="10"
                  step="1"
                  value={kValue}
                  onChange={(e) => setKValue(parseInt(e.target.value))}
                  className="flex-1 h-1 accent-accent-amber cursor-pointer"
                />
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => onRemoveOutliers(kValue)}
                  className="text-accent-amber border-accent-amber/30 hover:bg-accent-amber-dim"
                >
                  Remove
                </Button>
              </div>
            </div>

            {/* Crop button */}
            <Button
              variant="secondary"
              size="md"
              onClick={onCrop}
              className="w-full text-accent-amber border-accent-amber/30 hover:bg-accent-amber-dim"
            >
              <Crop size={14} />
              Crop to bounds
            </Button>

            {/* Divider */}
            <div className="border-t border-border-subtle" />

            {/* Undo */}
            <Button
              variant="secondary"
              size="md"
              onClick={onUndo}
              disabled={!canUndo}
              className="w-full"
            >
              <Undo2 size={14} />
              Undo
              {undoCount > 0 && (
                <span className="font-mono text-accent-cyan text-[10px] ml-1">
                  ({undoCount})
                </span>
              )}
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
