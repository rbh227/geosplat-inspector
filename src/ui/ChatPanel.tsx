import { useEffect, useRef, useState } from 'react'
import { X, SendHorizonal, ChevronRight, Square } from 'lucide-react'
import type { ChatMessage } from '../types/agent'
import type { ProposalState } from '@agent'
import ActionCard from './ActionCard'
import ProposalCard from './ProposalCard'
import Button from './Button'

interface ChatPanelProps {
  isOpen: boolean
  stage: 'clean' | 'understand'
  messages: ChatMessage[]
  isThinking: boolean
  /** The agent's latest narration/thought — the live "what I'm doing" line. */
  narration: string
  /** A parked crop/edit proposal awaiting the operator's decision, or null. */
  proposal: ProposalState | null
  onProposalDecide: (verdict: 'approved' | 'rejected' | 'adjusted', feedback?: string) => void
  onSend: (text: string) => void
  /** Stop the active run (user_interrupt). Shown while the agent is thinking. */
  onStop: () => void
  onClose: () => void
}

function formatElapsed(ms: number): string {
  const s = Math.floor(ms / 1000)
  if (s < 60) return `${s}s`
  return `${Math.floor(s / 60)}m ${s % 60}s`
}

const EMPTY_HINTS: Record<'clean' | 'understand', string> = {
  clean: 'Load a .ply, then describe what to clean — e.g. "clean this scene".',
  understand: 'Ask a question about the scene — e.g. "how many damaged buildings?"',
}

export default function ChatPanel({
  isOpen,
  stage,
  messages,
  isThinking,
  narration,
  proposal,
  onProposalDecide,
  onSend,
  onStop,
  onClose,
}: ChatPanelProps) {
  const [input, setInput] = useState('')
  const [elapsed, setElapsed] = useState(0)
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Elapsed-run clock: a long run should LOOK long ("thinking · 2m 14s"),
  // not like a frozen indicator. The zero-delay timeout resets the clock
  // asynchronously when a run starts (the indicator is hidden when idle).
  useEffect(() => {
    if (!isThinking) return
    const start = Date.now()
    const update = () => setElapsed(Date.now() - start)
    const t0 = setTimeout(update, 0)
    const t = setInterval(update, 1000)
    return () => {
      clearTimeout(t0)
      clearInterval(t)
    }
  }, [isThinking])

  // Auto-scroll to bottom when messages change or thinking state changes
  useEffect(() => {
    const el = scrollRef.current
    if (el) {
      el.scrollTop = el.scrollHeight
    }
  }, [messages, isThinking, narration])

  // Focus input when panel opens
  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 350)
    }
  }, [isOpen])

  function handleSend() {
    const trimmed = input.trim()
    if (!trimmed) return
    onSend(trimmed)
    setInput('')
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  if (!isOpen) return null

  return (
    <div
      className="h-full w-[380px] flex-none panel flex flex-col animate-slide-in-right"
      style={{ borderRadius: '0' }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border-subtle shrink-0">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-accent-cyan animate-pulse-glow" />
          <h2 className="text-sm font-semibold text-text-primary">Agent</h2>
        </div>
        <Button variant="icon" size="sm" onClick={onClose} aria-label="Close chat panel">
          <X size={16} />
        </Button>
      </div>

      {/* Messages */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto px-4 py-3 flex flex-col gap-3"
      >
        {/* Empty state: one stage-appropriate hint, nothing else (DL6) */}
        {messages.length === 0 && !isThinking && (
          <div className="flex-1 flex items-center justify-center px-6 text-center">
            <span className="text-sm text-text-dim leading-relaxed">{EMPTY_HINTS[stage]}</span>
          </div>
        )}
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`animate-slide-up flex flex-col ${
              msg.role === 'user' ? 'items-end' : 'items-start'
            }`}
          >
            {/* Message bubble */}
            <div
              className={`
                max-w-[85%] px-3 py-2 rounded-lg text-sm leading-relaxed
                ${
                  msg.role === 'user'
                    ? 'bg-accent-cyan-dim text-text-primary border border-accent-cyan/20 rounded-br-sm'
                    : 'bg-bg-elevated text-text-primary border border-border-subtle rounded-bl-sm'
                }
              `}
            >
              {msg.content}
            </div>

            {/* What the agent did, folded away — the reply is the product,
                the steps are the receipt. */}
            {msg.role === 'assistant' && msg.actions && msg.actions.length > 0 && (
              <details className="w-full max-w-[85%] mt-1 group">
                <summary className="flex items-center gap-1 cursor-pointer list-none text-[11px] font-mono text-text-dim hover:text-text-secondary select-none">
                  <ChevronRight size={11} className="transition-transform group-open:rotate-90" />
                  {msg.actions.length} step{msg.actions.length === 1 ? '' : 's'}
                </summary>
                <div className="flex flex-col">
                  {msg.actions.map((action, idx) => (
                    <ActionCard key={`${msg.id}-action-${idx}`} action={action} />
                  ))}
                </div>
              </details>
            )}

            {/* Thumbnail preview */}
            {msg.thumbnail && (
              <img
                src={msg.thumbnail}
                alt="Capture"
                className="mt-2 max-w-[85%] rounded-lg border border-border-subtle"
              />
            )}

            {/* Timestamp */}
            <span className="text-[10px] text-text-dim mt-1 font-mono">
              {new Date(msg.timestamp).toLocaleTimeString([], {
                hour: '2-digit',
                minute: '2-digit',
              })}
            </span>
          </div>
        ))}

        {/* Thinking indicator + the agent's live narration + elapsed clock */}
        {isThinking && (
          <div className="animate-fade-in flex items-start">
            <div className="bg-bg-elevated border border-border-subtle rounded-lg rounded-bl-sm px-3 py-2 max-w-[85%]">
              <div className="flex items-center gap-2">
                <div className="thinking-dots flex gap-1 shrink-0">
                  <span className="w-1.5 h-1.5 rounded-full bg-accent-cyan inline-block" />
                  <span className="w-1.5 h-1.5 rounded-full bg-accent-cyan inline-block" />
                  <span className="w-1.5 h-1.5 rounded-full bg-accent-cyan inline-block" />
                </div>
                {elapsed >= 5000 && (
                  <span className="text-[10px] font-mono text-text-dim shrink-0">
                    {formatElapsed(elapsed)}
                  </span>
                )}
                {narration && (
                  <span className="text-xs text-text-dim italic leading-snug">
                    {narration}
                  </span>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Parked proposal: docked above the chat input until the operator decides */}
      {proposal && (
        <div className="shrink-0">
          <ProposalCard proposal={proposal} onDecide={onProposalDecide} />
        </div>
      )}

      {/* Input bar */}
      <div className="shrink-0 px-4 py-3 border-t border-border-subtle">
        <div className="flex items-center gap-2">
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask the agent..."
            className="
              flex-1 bg-bg-elevated border border-border-subtle rounded-lg
              px-3 py-2 text-sm text-text-primary placeholder:text-text-dim
              outline-none
              focus:border-accent-cyan focus:shadow-[0_0_8px_var(--color-accent-cyan-dim)]
              transition-all duration-200
            "
          />
          {/* While a proposal is parked, typed text is adjustment feedback —
              keep Send. Otherwise a running agent shows Stop. */}
          {isThinking && !proposal ? (
            <Button
              variant="primary"
              size="md"
              onClick={onStop}
              aria-label="Stop the run"
            >
              <Square size={14} fill="currentColor" />
            </Button>
          ) : (
            <Button
              variant="primary"
              size="md"
              onClick={handleSend}
              disabled={!input.trim()}
              aria-label="Send message"
            >
              <SendHorizonal size={16} />
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}
