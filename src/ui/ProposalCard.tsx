import { useState } from 'react'
import { Crop, Eraser, Focus, HelpCircle, SendHorizonal, Sparkles } from 'lucide-react'
import type { ProposalState } from '@agent'
import Button from './Button'
import { proposalTitle } from './proposalTitle'

interface ProposalCardProps {
  proposal: ProposalState
  /** Resolves the parked proposal; the resolver latch makes repeat calls safe. */
  onDecide: (verdict: 'approved' | 'rejected' | 'adjusted', feedback?: string) => void
}

const KIND_ICONS: Record<string, React.ComponentType<{ size?: number; className?: string }>> = {
  crop_outside_box: Crop,
  delete_selection: Eraser,
  keep_only_selection: Focus,
  bulk_edit: Sparkles,
  delete_clusters: Eraser,
}

export default function ProposalCard({ proposal, onDecide }: ProposalCardProps) {
  const [feedback, setFeedback] = useState('')
  const Icon = KIND_ICONS[proposal.kind] ?? HelpCircle

  function handleAdjust() {
    const trimmed = feedback.trim()
    if (!trimmed) return
    onDecide('adjusted', trimmed)
    setFeedback('')
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleAdjust()
    }
  }

  return (
    <div className="panel-dense animate-expand m-3 mb-0 p-3 flex flex-col gap-3 border border-accent-amber/30">
      {/* Header */}
      <div className="flex items-center gap-2">
        <Icon size={14} className="text-accent-amber" />
        <span className="text-sm font-semibold text-text-primary">
          {proposalTitle(proposal.kind)}
        </span>
      </div>

      {/* Agent's summary of what it wants to do */}
      <p className="text-xs text-text-secondary leading-relaxed">
        {proposal.summary}
      </p>

      {/* v0.7 judgment-tour batch: one reviewed row per candidate cluster */}
      {proposal.clusters && proposal.clusters.length > 0 && (
        <div className="text-xs font-mono bg-bg-elevated border border-border-subtle rounded-lg px-2 py-1.5 max-h-40 overflow-y-auto">
          {proposal.clusters.map((row) => (
            <div key={row.label} className="flex items-center gap-2 py-0.5">
              <span className="w-5 text-accent-amber font-semibold">{row.label}</span>
              <span className="w-16 text-right text-text-secondary">{row.count.toLocaleString()}</span>
              <span className={
                row.verdict === 'junk' ? 'w-14 text-red-400' :
                row.verdict === 'structure' ? 'w-14 text-green-400' : 'w-14 text-text-dim'
              }>
                {row.verdict === 'junk' ? 'delete' : row.verdict === 'structure' ? 'keep' : 'unsure'}
              </span>
              <span className="flex-1 truncate text-text-secondary">{row.reason ?? ''}</span>
            </div>
          ))}
        </div>
      )}

      {/* The canonical operation the approval authorizes — shown verbatim so
          the operator reviews the real payload, never just the summary. */}
      {proposal.operation && (
        <p className="text-xs font-mono text-text-primary bg-bg-elevated border border-border-subtle rounded-lg px-2 py-1.5">
          Will run exactly:{' '}
          <span className="text-accent-amber">{proposal.operation.tool}</span>
          {proposal.operation.params && Object.keys(proposal.operation.params).length > 0
            ? ` ${JSON.stringify(proposal.operation.params)}`
            : ''}
        </p>
      )}

      {/* Approve / Reject */}
      <div className="flex items-center gap-2">
        <Button
          variant="primary"
          size="md"
          onClick={() => onDecide('approved')}
          className="flex-1"
        >
          Approve
        </Button>
        <Button
          variant="danger"
          size="md"
          onClick={() => onDecide('rejected')}
          className="flex-1"
        >
          Reject
        </Button>
      </div>

      {/* Free-text adjustment — Enter or Send resolves as 'adjusted' */}
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={proposal.clusters?.length
            ? "Adjust it — e.g. keep B, it's a shed"
            : 'Adjust it — e.g. make the box a bit bigger'}
          className="
            flex-1 bg-bg-elevated border border-border-subtle rounded-lg
            px-3 py-2 text-sm text-text-primary placeholder:text-text-dim
            outline-none
            focus:border-accent-amber focus:shadow-[0_0_8px_var(--color-accent-amber-dim)]
            transition-all duration-200
          "
        />
        <Button
          variant="secondary"
          size="md"
          onClick={handleAdjust}
          disabled={!feedback.trim()}
          aria-label="Send adjustment"
        >
          <SendHorizonal size={16} />
        </Button>
      </div>
    </div>
  )
}
