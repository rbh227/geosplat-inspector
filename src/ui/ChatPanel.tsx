import { useEffect, useRef, useState } from 'react'
import { X, SendHorizonal } from 'lucide-react'
import type { ChatMessage } from '../types/agent'
import ActionCard from './ActionCard'
import Button from './Button'

interface ChatPanelProps {
  isOpen: boolean
  messages: ChatMessage[]
  isThinking: boolean
  onSend: (text: string) => void
  onClose: () => void
}

export default function ChatPanel({
  isOpen,
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
      className={`
        absolute top-0 right-0 z-20 h-full w-[380px]
        panel flex flex-col
        animate-slide-in-right
      `}
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
