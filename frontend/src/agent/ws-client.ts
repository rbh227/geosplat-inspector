/**
 * WebSocket client implementing the §6.8 protocol against the frozen contract.
 *
 * Receives backend → frontend commands (camera_move, capture_request,
 * drop_marker, clear_markers, narrate, reload_scene) and trace events
 * (thought, tool_call, tool_result, complete). Executes commands via the
 * frontend executors / overlay and replies with a correlated message.
 *
 * NOTE (contract interpretation): §6.8 lists only `frame` / `user_interrupt`
 * as frontend → backend message types, but FrontendChannel.send_command
 * awaits a result for every command. We therefore reply to every awaited
 * command with a `type:"frame"` envelope correlated by `id`, whose payload
 * carries the tool result ({ok:true} for non-capture commands, {png}/{pngs}
 * for captures). This stays within the frozen type union. Flagged to Agents
 * 3/4 as a coordination detail — not a contract change.
 */
import type { ClusterRow, WSCommand, WSTraceEvent, WSResponse } from '../contracts.ts'
import type { RendererBridge, CameraMovePayload, TraceEntry } from './types.ts'
import { FrontendExecutors, runCameraTool } from './executors.ts'
import type { Overlay } from './overlay.ts'
import type { PanelBus } from './panels.ts'
import type { Transport } from './transport.ts'

const COMMAND_TYPES = new Set([
  'camera_move', 'capture_request', 'drop_marker', 'clear_markers', 'narrate', 'reload_scene',
  // v0.2 — selection pull + agent-driven editor tools
  'get_selection', 'selection_tool', 'movement_input', 'rotation_input',
  // v0.5 — blocking proposal: reply is parked until the operator decides
  'proposal',
])

function isCommand(m: { type?: string }): m is WSCommand {
  return typeof m?.type === 'string' && COMMAND_TYPES.has(m.type)
}

export class AgentWSClient {
  private executors: FrontendExecutors

  constructor(
    private transport: Transport,
    private bridge: RendererBridge,
    private overlay: Overlay,
    private panels: PanelBus,
  ) {
    this.executors = new FrontendExecutors(bridge, overlay)
    this.transport.onMessage((data) => this.handle(data))
  }

  private reply(id: string, payload: Record<string, unknown>): void {
    const msg: WSResponse = { type: 'frame', id, payload }
    this.transport.send(msg)
  }

  sendUserInterrupt(): void {
    this.transport.send({ type: 'user_interrupt', id: `int-${Date.now()}`, payload: {} })
  }

  private async handle(data: unknown): Promise<void> {
    const m = data as { type?: string }
    if (!m || typeof m.type !== 'string') return

    if (isCommand(m)) {
      await this.handleCommand(m)
    } else {
      this.handleTrace(m as WSTraceEvent)
    }
  }

  private async handleCommand(cmd: WSCommand): Promise<void> {
    const p = cmd.payload ?? {}
    try {
      switch (cmd.type) {
        case 'camera_move': {
          const { tool, args } = p as unknown as CameraMovePayload
          const result = await runCameraTool(this.executors, tool, args ?? {})
          this.reply(cmd.id, result as Record<string, unknown>)
          break
        }
        case 'capture_request': {
          // Dispatcher envelope: {tool: 'capture_frame'|'capture_orbit'|'survey_capture', args}.
          const { tool, args } = p as unknown as {
            tool?: string
            args?: { center: number[]; n: number; radius?: number; if_revision_not?: number }
          }
          const result = tool === 'survey_capture'
            ? await this.executors.survey_capture(args ?? {})
            : tool === 'capture_orbit' && args
              ? await this.executors.capture_orbit(args as { center: number[]; n: number; radius?: number })
              : await this.executors.capture_frame()
          this.reply(cmd.id, result as Record<string, unknown>)
          break
        }
        case 'drop_marker': {
          const { args } = p as unknown as { args?: { position?: unknown; label?: unknown } }
          const position = args?.position
          if (!Array.isArray(position) || position.length !== 3 || position.some((v) => typeof v !== 'number')) {
            this.reply(cmd.id, { ok: false, error: 'drop_marker: args.position must be [x,y,z]' })
            break
          }
          this.overlay.dropMarker(
            position as [number, number, number],
            typeof args?.label === 'string' ? args.label : '',
          )
          this.reply(cmd.id, { ok: true })
          break
        }
        case 'clear_markers': {
          this.overlay.clearMarkers()
          this.reply(cmd.id, { ok: true })
          break
        }
        case 'narrate': {
          // Two legitimate shapes: the dispatcher command {tool, args:{text}}
          // and the loop's ev_narrate EVENT {text} (no args, no correlation id).
          const maybe = p as { args?: { text?: unknown }; text?: unknown }
          const text = typeof maybe.args?.text === 'string'
            ? maybe.args.text
            : typeof maybe.text === 'string' ? maybe.text : ''
          if (!text) {
            if (cmd.id) this.reply(cmd.id, { ok: false, error: 'narrate: args.text missing' })
            break
          }
          this.panels.setNarration(text)
          if (cmd.id) this.reply(cmd.id, { ok: true })
          break
        }
        case 'reload_scene': {
          // also resets the trail — new scene, fresh path
          this.overlay.resetTrail()
          const { url } = p as { url: string }
          // loadSplat is on the bridge via executors' bridge; reload via overlay-free path
          await this.reloadScene(url)
          this.reply(cmd.id, { ok: true })
          break
        }
        // v0.2 — wired by the editor-tool executors (U8); explicit replies so
        // the backend's correlation future never hangs to timeout meanwhile.
        case 'get_selection': {
          const result = await this.executors.get_selection()
          this.transport.send({ type: 'selection', id: cmd.id, payload: result } as WSResponse)
          break
        }
        case 'selection_tool': {
          const { tool, args } = p as unknown as { tool: string; args: Record<string, unknown> }
          const result = await this.executors.runSelectionTool(tool, args ?? {})
          this.transport.send({ type: 'tool_result', id: cmd.id, payload: result } as WSResponse)
          break
        }
        case 'movement_input': {
          // The dispatcher packages every frontend command as {tool, args};
          // WSChannel forwards that as the payload, so the real fields live in
          // p.args (reading p directly gave undefined -> move_camera no-op'd).
          const { args } = p as unknown as { args: { direction: string; duration_ms: number } }
          const result = await this.executors.move_camera(args ?? { direction: '', duration_ms: 0 })
          this.transport.send({ type: 'tool_result', id: cmd.id, payload: result } as WSResponse)
          break
        }
        case 'rotation_input': {
          const { args } = p as unknown as { args: { direction: string; duration_ms: number } }
          const result = await this.executors.turn(args ?? { direction: '', duration_ms: 0 })
          this.transport.send({ type: 'tool_result', id: cmd.id, payload: result } as WSResponse)
          break
        }
        case 'proposal': {
          const { args } = p as unknown as {
            args: {
              kind: string
              summary: string
              operation?: { tool?: unknown; params?: unknown }
              clusters?: unknown
            }
          }
          const id = cmd.id
          // Carry the canonical operation to the card (Codex adversarial
          // review): the operator must review the real payload the backend
          // binds the approval to, not only the model-authored summary.
          const rawOp = args?.operation
          const operation = rawOp && typeof rawOp.tool === 'string'
            ? {
                tool: rawOp.tool,
                params: rawOp.params && typeof rawOp.params === 'object'
                  ? rawOp.params as Record<string, unknown>
                  : undefined,
              }
            : null
          // Never replace a parked proposal (Codex adversarial review): the
          // first resolver would be orphaned and its no-timeout future would
          // hang forever. Single-run enforcement makes this unreachable in
          // protocol; reply-reject defensively rather than clobber.
          if (this.panels.proposal.get()) {
            this.transport.send({
              type: 'tool_result', id,
              payload: { ok: false, verdict: 'rejected', feedback: 'another proposal is already awaiting review' },
            } as WSResponse)
            break
          }
          // Latch the resolver: a rapid double-click on the ProposalCard must
          // never send two tool_results for the same id. The exactly-one-reply
          // invariant is guaranteed here, not delegated to the caller.
          // v0.7 — judgment-tour batch rows: sanitize before they reach React.
          const rawRows = args?.clusters
          const clusters = Array.isArray(rawRows)
            ? rawRows.filter((r): r is ClusterRow =>
                !!r && typeof (r as ClusterRow).label === 'string'
                && typeof (r as ClusterRow).count === 'number')
            : undefined
          let done = false
          this.panels.setProposal({
            kind: args?.kind ?? '',
            summary: args?.summary ?? '',
            operation,
            clusters,
            resolve: (verdict, feedback) => {
              if (done) return
              done = true
              // v0.6: on approval, return the box as it stands NOW — the
              // operator's editable crop-box gizmo (cyan channel), falling
              // back to the agent's originally-previewed box (amber channel)
              // if the operator never engaged the gizmo. Never the reverse:
              // getProposalBox() stays the agent's own record.
              const box = verdict === 'approved'
                ? (this.bridge.getCropBox() ?? this.bridge.getProposalBox())
                : null
              this.transport.send({
                type: 'tool_result', id,
                payload: { ok: true, verdict, ...(feedback ? { feedback } : {}), ...(box ? { box } : {}) },
              } as WSResponse)
              this.panels.clearProposal()
            },
          })
          break  // reply parked — resolved by the operator via the ProposalCard
        }
      }
    } catch (err) {
      this.panels.pushTrace({
        kind: 'tool_result',
        text: `error in ${cmd.type}: ${String(err)}`,
        at: Date.now(),
      })
      this.reply(cmd.id, { ok: false, error: String(err) })
    }
  }

  private reloadScene(url: string): Promise<void> {
    return this.bridge.loadSplat(url)
  }

  private handleTrace(ev: WSTraceEvent): void {
    const payload = (ev.payload ?? {}) as Record<string, unknown>
    const text = String(payload.text ?? payload.name ?? '')
    const entry: TraceEntry = { kind: ev.type, text, detail: payload, at: Date.now() }
    this.panels.pushTrace(entry)
    if (ev.type === 'complete') {
      this.panels.setRunning(false)
      // The run is over: drop any still-parked proposal WITHOUT replying (the
      // backend correlator is gone) and clear its viewport artifacts.
      if (this.panels.proposal.get()) this.panels.clearProposal()
      try { this.bridge.clearProposalBox() } catch { /* bridge may lack a scene */ }
      try { this.bridge.clearSelection() } catch { /* bridge may lack a scene */ }
    }
  }
}
