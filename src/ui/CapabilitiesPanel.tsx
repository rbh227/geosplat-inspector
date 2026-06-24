import { useState } from 'react'
import { Navigation, Search, Globe, Eraser, ChevronLeft, Undo2, Crop } from 'lucide-react'

interface CapabilitiesPanelProps {
  onSendPrompt: (text: string) => void
  onCleanOpacity: (threshold: number) => void
  onRemoveOutliers: (k: number) => void
  onCrop: () => void
  onUndo: () => void
  canUndo: boolean
  undoCount: number
  onClose: () => void
}

interface Section {
  id: string
  label: string
  icon: React.ReactNode
  prompts: string[]
}

const SECTIONS: Section[] = [
  {
    id: 'navigate',
    label: 'Navigate',
    icon: <Navigation size={15} />,
    prompts: [
      'Orbit around the scene slowly',
      'Fly to the center and frame the object',
      'Look at the scene from the top down',
    ],
  },
  {
    id: 'inspect',
    label: 'Inspect',
    icon: <Search size={15} />,
    prompts: [
      'Scan for isolated Gaussians',
      'Measure opacity across the scene',
      'Find and mark problem regions',
    ],
  },
  {
    id: 'multiangle',
    label: 'Multi-angle analysis',
    icon: <Globe size={15} />,
    prompts: [
      'Compare front and rear density',
      'Capture 6 viewpoints around the scene',
    ],
  },
]

export default function CapabilitiesPanel({
  onSendPrompt, onCleanOpacity, onRemoveOutliers, onCrop, onUndo,
  canUndo, undoCount, onClose,
}: CapabilitiesPanelProps) {
  const [opacityThreshold, setOpacityThreshold] = useState(0.10)
  const [kValue, setKValue] = useState(3)

  return (
    <div className="w-[270px] flex-none bg-bg-surface border-r border-border-subtle flex flex-col">
      {/* Header */}
      <div className="h-10 flex-none flex items-center justify-between px-3.5 border-b border-border-subtle/60">
        <span className="font-mono text-[10.5px] font-semibold tracking-[0.14em] text-text-secondary uppercase">
          Capabilities
        </span>
        <button onClick={onClose} className="w-[22px] h-[22px] flex items-center justify-center border-none bg-transparent text-text-dim cursor-pointer rounded hover:text-text-primary hover:bg-bg-elevated">
          <ChevronLeft size={15} />
        </button>
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-auto p-1.5">
        {SECTIONS.map((section, si) => (
          <div key={section.id} className={si > 0 ? 'border-t border-border-subtle/40 pt-0.5' : ''}>
            <div className="flex items-center gap-2.5 px-2 py-2.5 text-text-dim">
              {section.icon}
              <span className="text-[12.5px] font-semibold text-text-primary">{section.label}</span>
            </div>
            {section.prompts.map((prompt) => (
              <button
                key={prompt}
                onClick={() => onSendPrompt(prompt)}
                className="w-full flex items-center gap-2 px-2 py-[7px] pl-8 border-none bg-transparent rounded-[5px] cursor-pointer text-left text-text-secondary text-xs hover:bg-bg-elevated hover:text-text-primary transition-colors"
              >
                <span className="text-text-muted text-[10px]">&#9656;</span>
                {prompt}
              </button>
            ))}
          </div>
        ))}

        {/* Clean up section with actual controls */}
        <div className="border-t border-border-subtle/40 pt-0.5">
          <div className="flex items-center gap-2.5 px-2 py-2.5 text-text-dim">
            <Eraser size={15} />
            <span className="text-[12.5px] font-semibold text-text-primary">Clean up</span>
          </div>

          {/* Agent prompts */}
          <button
            onClick={() => onSendPrompt(`Remove floaters below ${opacityThreshold.toFixed(2)} opacity`)}
            className="w-full flex items-center gap-2 px-2 py-[7px] pl-8 border-none bg-transparent rounded-[5px] cursor-pointer text-left text-text-secondary text-xs hover:bg-bg-elevated hover:text-text-primary transition-colors"
          >
            <span className="text-text-muted text-[10px]">&#9656;</span>
            Remove floaters below {opacityThreshold.toFixed(2)} opacity
          </button>
          <button
            onClick={() => onSendPrompt('Strip outliers, then crop to bounds')}
            className="w-full flex items-center gap-2 px-2 py-[7px] pl-8 border-none bg-transparent rounded-[5px] cursor-pointer text-left text-text-secondary text-xs hover:bg-bg-elevated hover:text-text-primary transition-colors"
          >
            <span className="text-text-muted text-[10px]">&#9656;</span>
            Strip outliers, then crop to bounds
          </button>

          {/* Manual controls */}
          <div className="px-3 pt-3 pb-1 flex flex-col gap-2.5">
            {/* Opacity slider */}
            <div className="flex flex-col gap-1">
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-text-secondary">Opacity threshold</span>
                <span className="font-mono text-[11px] text-text-primary">{opacityThreshold.toFixed(2)}</span>
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="range" min="0" max="1" step="0.01"
                  value={opacityThreshold}
                  onChange={(e) => setOpacityThreshold(parseFloat(e.target.value))}
                  className="flex-1 h-1 accent-accent-cyan cursor-pointer"
                />
                <button
                  onClick={() => onCleanOpacity(opacityThreshold)}
                  className="px-2 py-1 text-[11px] font-medium text-accent-cyan border border-accent-cyan/30 rounded bg-accent-cyan/10 cursor-pointer hover:bg-accent-cyan/20 transition-colors"
                >Clean</button>
              </div>
            </div>

            {/* Outlier slider */}
            <div className="flex flex-col gap-1">
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-text-secondary">Outlier k-neighbors</span>
                <span className="font-mono text-[11px] text-text-primary">{kValue}</span>
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="range" min="1" max="16" step="1"
                  value={kValue}
                  onChange={(e) => setKValue(parseInt(e.target.value))}
                  className="flex-1 h-1 accent-accent-cyan cursor-pointer"
                />
                <button
                  onClick={() => onRemoveOutliers(kValue)}
                  className="px-2 py-1 text-[11px] font-medium text-accent-cyan border border-accent-cyan/30 rounded bg-accent-cyan/10 cursor-pointer hover:bg-accent-cyan/20 transition-colors"
                >Remove</button>
              </div>
            </div>

            {/* Crop */}
            <button
              onClick={onCrop}
              className="w-full flex items-center justify-center gap-1.5 py-1.5 text-[11px] font-medium text-text-secondary border border-border-active rounded bg-bg-elevated cursor-pointer hover:bg-bg-hover hover:text-text-primary transition-colors"
            >
              <Crop size={12} />Crop to bounds
            </button>

            {/* Undo */}
            <button
              onClick={onUndo}
              disabled={!canUndo}
              className="w-full flex items-center justify-center gap-1.5 py-1.5 text-[11px] text-text-dim border border-border-subtle rounded bg-transparent cursor-pointer hover:bg-bg-elevated hover:text-text-secondary disabled:opacity-30 disabled:cursor-default transition-colors"
            >
              <Undo2 size={12} />Undo
              {undoCount > 0 && <span className="font-mono text-accent-cyan text-[10px]">({undoCount})</span>}
            </button>
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="flex-none px-3.5 py-2.5 border-t border-border-subtle/60">
        <span className="font-mono text-[10px] text-text-faint tracking-wide">
          Click a prompt to dispatch the agent
        </span>
      </div>
    </div>
  )
}
