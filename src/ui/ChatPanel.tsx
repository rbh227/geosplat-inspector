import { useEffect, useRef, useState } from 'react'
import { X, SendHorizonal, Play } from 'lucide-react'
import type { ChatMessage } from '../types/agent'
import type { SkillInfo } from '../backend/client'
import ActionCard from './ActionCard'
import Button from './Button'

interface ChatPanelProps {
  isOpen: boolean
  stage: 'clean' | 'understand'
  /** The shared skills vocabulary (R11) — clickable entries, not chat bubbles. */
  skills: SkillInfo[]
  messages: ChatMessage[]
  isThinking: boolean
  onSend: (text: string) => void
  onClose: () => void
}

const EMPTY_HINTS: Record<'clean' | 'understand', string> = {
  clean: 'Load a .ply, then describe what to clean — e.g. "clean this scene".',
  understand: 'Ask a question about the scene — e.g. "how many damaged buildings?"',
}

export default function ChatPanel({
  isOpen,
  stage,
  skills,
  messages,
  isThinking,
  onSend,
  onClose,
}: ChatPanelProps) {
  const [input, setInput] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Auto-scroll to bottom when messages change or thinking state changes
  useEffect(() => {
    const el = scrollRef.current
    if (el) {
      el.scrollTop = el.scrollHeight
    }
  }, [messages, isThinking])

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

      {/* Skills: compact pills in a dedicated strip — the same routines the
          agent composes; clicking one runs it (AE5). */}
      {skills.length > 0 && (
        <div className="shrink-0 flex flex-wrap gap-1.5 px-4 py-2.5 border-b border-border-subtle">
          {skills.map((s) => (
            <button
              key={s.name}
              type="button"
              title={`${s.description}\n${s.recipe}`}
              disabled={isThinking}
              onClick={() => onSend(s.description)}
              className="inline-flex items-center gap-1 rounded-full border border-border-active bg-bg-elevated px-2.5 py-1 font-mono text-[10.5px] text-text-secondary hover:text-text-primary hover:border-accent-cyan/50 transition-colors disabled:opacity-40 cursor-pointer disabled:cursor-default"
            >
              <Play size={9} />
              {s.name}
            </button>
          ))}
        </div>
      )}

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

            {/* Action cards for assistant messages */}
            {msg.role === 'assistant' && msg.actions && msg.actions.length > 0 && (
              <div className="w-full max-w-[85%] flex flex-col">
                {msg.actions.map((action, idx) => (
                  <ActionCard key={`${msg.id}-action-${idx}`} action={action} />
                ))}
              </div>
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

        {/* Thinking indicator */}
        {isThinking && (
          <div className="animate-fade-in flex items-start">
            <div className="bg-bg-elevated border border-border-subtle rounded-lg rounded-bl-sm px-3 py-2">
              <div className="thinking-dots flex gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-accent-cyan inline-block" />
                <span className="w-1.5 h-1.5 rounded-full bg-accent-cyan inline-block" />
                <span className="w-1.5 h-1.5 rounded-full bg-accent-cyan inline-block" />
              </div>
            </div>
          </div>
        )}
      </div>

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
          <Button
            variant="primary"
            size="md"
            onClick={handleSend}
            disabled={!input.trim()}
            aria-label="Send message"
          >
            <SendHorizonal size={16} />
          </Button>
        </div>
      </div>
    </div>
  )
}
