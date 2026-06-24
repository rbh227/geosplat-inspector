/**
 * In-process MOCK backend — drives the frontend exactly like the real agent
 * loop will (§6.8), but with no server. Use it to verify pacing, capture,
 * markers/trail, narration and trace ordering before Agent 4 is ready.
 *
 * It speaks the backend → frontend half of the protocol over a LoopbackTransport
 * and awaits the correlated `frame` reply for each command (mirroring
 * FrontendChannel.send_command).
 */
import type { WSCommand, WSTraceEvent, WSResponse } from '../contracts.ts'
import { LoopbackTransport } from './transport.ts'

export class MockBackend {
  private seq = 0
  private pending = new Map<string, (payload: Record<string, unknown>) => void>()

  constructor(private transport: LoopbackTransport) {
    transport.backendHandler = (msg: WSResponse) => {
      if (msg.type === 'frame') {
        this.pending.get(msg.id)?.(msg.payload ?? {})
        this.pending.delete(msg.id)
      }
      // user_interrupt would abort the script in a fuller mock
    }
  }

  /** Send a command and await the frontend's correlated reply. */
  private command(type: WSCommand['type'], payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    const id = `cmd-${++this.seq}`
    return new Promise((resolve) => {
      this.pending.set(id, resolve)
      const cmd: WSCommand = { type, id, payload }
      this.transport.emitToClient(cmd)
    })
  }

  private trace(type: WSTraceEvent['type'], payload: Record<string, unknown>): void {
    const ev: WSTraceEvent = { type, payload }
    this.transport.emitToClient(ev)
  }

  /** A scripted "robot inspector" pass that exercises every frontend tool. */
  async runDemoInspection(opts: { reloadUrl?: string } = {}): Promise<string[]> {
    const frames: string[] = []

    this.trace('thought', { text: 'Beginning scene inspection.' })
    await this.command('narrate', { text: 'Framing the whole scene…' })

    this.trace('tool_call', { name: 'reset_view' })
    await this.command('camera_move', { tool: 'reset_view', args: {} })
    this.trace('tool_result', { text: 'reset_view ok' })

    this.trace('tool_call', { name: 'orbit' })
    await this.command('camera_move', {
      tool: 'orbit',
      args: { center: [0, 0, 0], deg: 60, axis: 'y', duration_ms: 1200 },
    })

    await this.command('narrate', { text: 'Scanning the upper region for floaters.' })
    await this.command('camera_move', { tool: 'scan_pause', args: { ms: 600 } })

    await this.command('drop_marker', { position: [0.8, 0.8, 0.0], label: 'floaters?' })
    await this.command('drop_marker', { position: [-0.6, 0.2, 0.5], label: 'outlier' })

    this.trace('tool_call', { name: 'capture_frame' })
    const cap = await this.command('capture_request', {})
    // Same wire shape as the real backend: bare base64 under png_base64.
    if (typeof cap.png_base64 === 'string') frames.push(`data:image/png;base64,${cap.png_base64}`)
    this.trace('tool_result', { text: 'captured frame' })

    await this.command('camera_move', {
      tool: 'frame_object',
      args: { bbox: { min: [-0.4, -0.4, -0.4], max: [0.4, 0.4, 0.4] }, duration_ms: 1000 },
    })

    const orbitCap = await this.command('capture_request', {
      orbit: { center: [0, 0, 0], n: 4, radius: 3 },
    })
    if (Array.isArray(orbitCap.frames_base64)) {
      frames.push(...(orbitCap.frames_base64 as string[]).map((b) => `data:image/png;base64,${b}`))
    }

    if (opts.reloadUrl) {
      await this.command('narrate', { text: 'Loading cleaned scene…' })
      await this.command('reload_scene', { url: opts.reloadUrl })
    }

    await this.command('clear_markers', {})
    this.trace('complete', { text: 'Inspection complete.' })
    return frames
  }
}

/** Convenience: build a loopback transport already wired to a MockBackend. */
export function createMockTransport(): { transport: LoopbackTransport; backend: MockBackend } {
  const transport = new LoopbackTransport()
  const backend = new MockBackend(transport)
  return { transport, backend }
}
