/**
 * Panel data wiring (data only — not final visual polish).
 *
 * A tiny pub/sub the React panels subscribe to: trace stream, narration,
 * latest metrics, and the capability-launcher catalog. No JSX here.
 */
import type { ClusterRow, Metrics } from '../contracts.ts'
import { FRONTEND_TOOLS, BACKEND_TOOLS } from '../contracts.ts'
import type { TraceEntry } from './types.ts'

export interface Capability {
  name: string
  runs_on: 'frontend' | 'backend'
}

/** A parked crop/edit proposal awaiting the operator's decision. The resolver
 *  (installed by ws-client) sends the correlated tool_result and clears the
 *  signal — nothing is sent until the operator approves/rejects/adjusts. */
export interface ProposalState {
  kind: string
  summary: string
  /** For bulk_edit: the exact operation the approval authorizes — rendered on
   *  the card so the operator reviews the real payload, never just the
   *  model-authored summary (Codex adversarial review). */
  operation?: { tool: string; params?: Record<string, unknown> } | null
  /** For delete_clusters (v0.7): the judgment-tour rows the operator reviews —
   *  one line per candidate cluster with its verdict and the model's reason. */
  clusters?: ClusterRow[]
  /** For keep_only_subject (v0.8): slider state — counts per level, current
   *  level, and the local re-tint callback (no round trip while parked). */
  subject?: { counts: number[]; level: number; onLevel: (k: number) => void }
  resolve: (verdict: 'approved' | 'rejected' | 'adjusted', feedback?: string) => void
}

/** Static catalog for the capability launcher, derived from the frozen contract. */
export const CAPABILITY_CATALOG: Capability[] = [
  ...FRONTEND_TOOLS.map((name) => ({ name, runs_on: 'frontend' as const })),
  ...BACKEND_TOOLS.map((name) => ({ name, runs_on: 'backend' as const })),
]

type Listener<T> = (value: T) => void

class Signal<T> {
  private listeners = new Set<Listener<T>>()
  constructor(private value: T) {}
  get(): T { return this.value }
  set(v: T): void { this.value = v; this.listeners.forEach((l) => l(v)) }
  subscribe(l: Listener<T>): () => void {
    this.listeners.add(l)
    l(this.value)
    return () => this.listeners.delete(l)
  }
}

export class PanelBus {
  readonly trace = new Signal<TraceEntry[]>([])
  readonly narration = new Signal<string | null>(null)
  readonly metrics = new Signal<Metrics | null>(null)
  readonly running = new Signal<boolean>(false)
  readonly proposal = new Signal<ProposalState | null>(null)

  pushTrace(entry: TraceEntry): void {
    this.trace.set([...this.trace.get(), entry])
  }

  setNarration(text: string): void {
    this.setNarrationInternal(text)
    this.pushTrace({ kind: 'narrate', text, at: Date.now() })
  }

  private setNarrationInternal(text: string): void {
    this.narration.set(text)
  }

  setMetrics(m: Metrics): void { this.metrics.set(m) }
  setRunning(v: boolean): void { this.running.set(v) }

  // Relies on the blocking-proposal contract: the backend never sends a second
  // proposal while one is parked, so a plain set (no queue) is sufficient.
  setProposal(p: ProposalState): void { this.proposal.set(p) }
  clearProposal(): void { this.proposal.set(null) }

  reset(): void {
    this.trace.set([])
    this.narration.set(null)
    this.proposal.set(null)
  }
}
