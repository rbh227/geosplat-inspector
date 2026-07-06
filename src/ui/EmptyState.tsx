import { useCallback, useState } from 'react'

interface EmptyStateProps {
  onImport: () => void
  onDropFile: (file: File) => void
}

/**
 * Minimal viewport empty state — plain text and one flat button, in the
 * old-tool spirit. Sample scenes live behind the Samples button in the top
 * bar, not here.
 */
export default function EmptyState({ onImport, onDropFile }: EmptyStateProps) {
  const [dragging, setDragging] = useState(false)

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files?.[0]
    if (file) onDropFile(file)
  }, [onDropFile])

  return (
    <div
      className={`absolute inset-0 flex items-center justify-center transition-colors ${
        dragging ? 'bg-bg-hover/40' : ''
      }`}
      onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
    >
      <div className="flex flex-col items-center gap-3 text-center">
        <span className="text-[13px] text-text-secondary">No scene loaded</span>
        <button
          onClick={onImport}
          className="btn-phosphor px-4 py-1.5 text-[12px] cursor-pointer"
        >
          Import…
        </button>
        <span className="text-[11px] text-text-dim">
          drag &amp; drop a <code className="font-mono">.ply / .splat / .spz / .ksplat</code>,
          or pick one from Samples in the toolbar
        </span>
      </div>
    </div>
  )
}
