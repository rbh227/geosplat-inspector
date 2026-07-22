import { useState } from 'react'
import { Crop, Eraser, HelpCircle, SendHorizonal } from 'lucide-react'
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
          placeholder="Adjust it — e.g. make the box a bit bigger"
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
