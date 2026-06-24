import { useEffect, useRef, useState } from 'react'
import { ChevronRight } from 'lucide-react'
import type { ChatMessage, AgentAction } from '../types/agent'

interface InspectorPanelProps {
  messages: ChatMessage[]
  isThinking: boolean
  onSend: (text: string) => void
  onClose: () => void
}

type Tab = 'metrics' | 'trace'

/* ── Metrics Tab ─────────────────────────────────── */

function MetricsTab({ messages }: { messages: ChatMessage[] }) {
  // Extract latest stats from agent actions if available
  const lastAssistant = [...messages].reverse().find(m => m.role === 'assistant')
  const stats = lastAssistant?.actions?.find(a => a.type === 'capture' || a.detail?.includes('Gaussians'))

  return (
    <div className="p-3.5">
      <div className="font-mono text-[10px] font-semibold tracking-[0.14em] text-text-dim mb-1">SCENE</div>
      <MetricRow label="Gaussians" value="—" />
      <MetricRow label="Visible" value="—" />

      <div className="font-mono text-[10px] font-semibold tracking-[0.14em] text-text-dim mt-4 mb-1">QUALITY</div>
      <MetricRow label="Floaters" value="—" accent />
      <MetricRow label="Outliers" value="—" suffix="%" />
      <MetricRow label="Mean opacity" value="—" />

      {stats && (
        <div className="mt-4 text-[11px] text-text-dim font-mono">
          {stats.detail}
        </div>
      )}

      <div className="font-mono text-[10px] font-semibold tracking-[0.14em] text-text-dim mt-4 mb-2">
        OPACITY DISTRIBUTION
      </div>
      <div className="h-[66px] flex items-end gap-[3px]">
        {Array.from({ length: 12 }, (_, i) => {
          const h = [14, 9, 22, 38, 55, 72, 88, 100, 96, 78, 60, 40][i]
          return (
            <div
              key={i}
              className="flex-1 rounded-sm"
              style={{
                height: `${h}%`,
                background: i < 2 ? 'rgba(210,153,34,0.5)' : `hsl(212, 18%, ${15 + i * 3}%)`,
              }}
            />
          )
        })}
      </div>
      <div className="flex justify-between mt-1.5">
        <span className="font-mono text-[9.5px] text-text-dim">0.0</span>
        <span className="font-mono text-[9.5px] text-text-dim">opacity</span>
        <span className="font-mono text-[9.5px] text-text-dim">1.0</span>
      </div>
    </div>
  )
}

function MetricRow({ label, value, suffix, accent }: { label: string; value: string; suffix?: string; accent?: boolean }) {
  return (
    <div className="flex justify-between items-baseline py-2.5 border-b border-border-subtle/50">
      <span className="text-[12.5px] text-text-secondary">{label}</span>
      <span className={`font-mono text-[15px] ${accent ? 'text-accent-amber-bright' : 'text-text-primary'}`}>
        {value}
        {suffix && <span className="text-text-dim text-[11px] ml-0.5">{suffix}</span>}
      </span>
    </div>
  )
}

/* ── Trace Tab ───────────────────────────────────── */

function TraceTab({ messages, isThinking }: { messages: ChatMessage[]; isThinking: boolean }) {
  const steps: { type: 'thinking' | 'tool' | 'result'; label: string; detail: string; active?: boolean }[] = []

  // Build trace from messages and their actions
  for (const msg of messages) {
    if (msg.role === 'user') {
      steps.push({ type: 'thinking', label: 'PROMPT', detail: msg.content })
    }
    if (msg.role === 'assistant') {
      if (msg.actions) {
        for (const action of msg.actions) {
          steps.push({ type: 'tool', label: 'TOOL', detail: actionToTrace(action) })
          if (action.detail) {
            steps.push({ type: 'result', label: 'RESULT', detail: action.detail })
          }
        }
      }
      if (msg.content) {
        steps.push({ type: 'result', label: 'ANSWER', detail: msg.content })
      }
    }
  }

  if (isThinking) {
    steps.push({ type: 'thinking', label: 'THINKING', detail: 'Processing...', active: true })
  }

  if (steps.length === 0) {
    return (
      <div className="p-4 text-center text-text-dim text-xs">
        No trace yet. Send a prompt to start.
      </div>
    )
  }

  return (
    <div className="p-3.5 relative">
      {/* Connector line */}
      <div className="absolute left-[22px] top-4 bottom-5 w-px bg-border-mid" />

      {steps.map((step, i) => (
        <div
          key={i}
          className={`relative flex gap-3 py-[7px] ${
            step.active
              ? 'ml-[-9px] pl-[9px] border-l-2 border-accent-cyan bg-gradient-to-r from-accent-cyan/8 to-transparent rounded-r-[5px]'
              : ''
          }`}
        >
          {/* Node */}
          <span className={`relative z-[1] flex-none w-[17px] h-[17px] mt-0.5 flex items-center justify-center ${
            step.active
              ? 'rounded-full bg-accent-cyan shadow-[0_0_8px_rgba(88,166,255,0.6)] animate-agent-blink'
              : step.type === 'tool'
              ? 'rounded bg-bg-elevated border-[1.5px] border-text-muted'
              : step.type === 'result'
              ? 'rounded-full bg-bg-elevated border-[1.5px] border-accent-green-bg'
              : 'rounded-full bg-bg-surface border-[1.5px] border-text-muted'
          }`}>
            {step.type === 'tool' && !step.active && (
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#7D8590" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M5 17l5-5-5-5"/><path d="M13 19h6"/>
              </svg>
            )}
            {step.type === 'result' && !step.active && (
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#3fb950" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round">
                <path d="M20 6L9 17l-5-5"/>
              </svg>
            )}
          </span>

          {/* Content */}
          <div className="min-w-0">
            <div className={`font-mono text-[9.5px] tracking-[0.12em] mb-0.5 ${
              step.active ? 'text-accent-cyan' : 'text-text-dim'
            }`}>{step.label}</div>
            <div className={`text-[12px] leading-relaxed break-words ${
              step.type === 'tool' ? 'font-mono text-text-secondary' :
              step.active ? 'text-text-primary' : 'text-text-secondary'
            }`}>{step.detail}</div>
          </div>
        </div>
      ))}
    </div>
  )
}

function actionToTrace(action: AgentAction): string {
  const parts = [action.label]
  if (action.removedCount !== undefined) parts.push(`→ removed ${action.removedCount.toLocaleString()}`)
  return parts.join(' ')
}

/* ── Main Panel ──────────────────────────────────── */

export default function InspectorPanel({ messages, isThinking, onSend, onClose }: InspectorPanelProps) {
  const [input, setInput] = useState('')
  const [activeTab, setActiveTab] = useState<Tab>('metrics')
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, isThinking])

  function handleSend() {
    const trimmed = input.trim()
    if (!trimmed) return
    onSend(trimmed)
    setInput('')
  }

  return (
    <div className="w-[340px] flex-none bg-bg-surface border-l border-border-subtle flex flex-col">
      {/* Prompt area */}
      <div className="flex-none p-3.5 border-b border-border-subtle/60">
        <div className="flex items-center justify-between mb-2">
          <span className="font-mono text-[10.5px] font-semibold tracking-[0.14em] text-text-secondary uppercase">Prompt</span>
          <button onClick={onClose} className="w-[22px] h-[22px] flex items-center justify-center border-none bg-transparent text-text-dim cursor-pointer rounded hover:text-text-primary hover:bg-bg-elevated">
            <ChevronRight size={15} />
          </button>
        </div>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
          spellCheck={false}
          placeholder="Describe what to inspect or clean..."
          className="w-full h-[72px] resize-none bg-bg-deep border border-border-active rounded-md p-2.5 text-text-primary text-[13px] leading-relaxed outline-none focus:border-accent-cyan/60 transition-colors font-[inherit]"
        />
        <div className="flex items-center justify-between mt-2.5">
          <span className="inline-flex items-center gap-1.5 text-[11px] text-text-dim border border-border-active/60 rounded px-2 py-0.5 font-mono">
            agent · auto-plan
          </span>
          <button
            onClick={handleSend}
            disabled={!input.trim()}
            className="inline-flex items-center gap-2 h-[31px] px-3.5 rounded-md border border-accent-cyan/55 bg-accent-cyan/12 text-accent-cyan-soft text-[12.5px] font-semibold cursor-pointer hover:bg-accent-cyan/20 hover:border-accent-cyan/80 disabled:opacity-30 disabled:cursor-default transition-colors"
          >
            Run
            <span className="font-mono text-[10px] text-accent-cyan-muted border-l border-accent-cyan/30 pl-[7px]">&#8984;&#9166;</span>
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex-none flex border-b border-border-subtle px-3.5">
        {(['metrics', 'trace'] as Tab[]).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`relative py-3 mr-5 border-none bg-transparent text-[12.5px] font-semibold cursor-pointer transition-colors capitalize ${
              activeTab === tab ? 'text-text-primary' : 'text-text-secondary hover:text-text-primary'
            }`}
          >
            {tab}
            {activeTab === tab && (
              <span className="absolute left-0 right-0 -bottom-px h-[2px] bg-accent-cyan" />
            )}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div ref={scrollRef} className="flex-1 overflow-auto">
        {activeTab === 'metrics' ? (
          <MetricsTab messages={messages} />
        ) : (
          <TraceTab messages={messages} isThinking={isThinking} />
        )}
      </div>
    </div>
  )
}
