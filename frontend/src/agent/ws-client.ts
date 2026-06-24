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
import type { WSCommand, WSTraceEvent, WSResponse } from '../contracts.ts'
import type { RendererBridge, CameraMovePayload, TraceEntry } from './types.ts'
import { FrontendExecutors, runCameraTool } from './executors.ts'
import type { Overlay } from './overlay.ts'
import type { PanelBus } from './panels.ts'
import type { Transport } from './transport.ts'

const COMMAND_TYPES = new Set([
  'camera_move', 'capture_request', 'drop_marker', 'clear_markers', 'narrate', 'reload_scene',
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
          const orbit = (p as { orbit?: { center: number[]; n: number; radius?: number } }).orbit
          const result = orbit
            ? await this.executors.capture_orbit(orbit)
            : await this.executors.capture_frame()
          this.reply(cmd.id, result as Record<string, unknown>)
          break
        }
        case 'drop_marker': {
          const { position, label } = p as { position: [number, number, number]; label: string }
          this.overlay.dropMarker(position, label ?? '')
          this.reply(cmd.id, { ok: true })
          break
        }
        case 'clear_markers': {
          this.overlay.clearMarkers()
          this.reply(cmd.id, { ok: true })
          break
        }
        case 'narrate': {
          const { text } = p as { text: string }
          this.panels.setNarration(text ?? '')
          this.reply(cmd.id, { ok: true })
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
    if (ev.type === 'complete') this.panels.setRunning(false)
  }
}
