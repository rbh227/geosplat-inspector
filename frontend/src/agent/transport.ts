/**
 * Transport abstraction so the WS client can run against a real WebSocket OR
 * an in-process mock backend (no server) during development.
 */
import type { WSResponse } from '../contracts.ts'

export interface Transport {
  /** Frontend → backend (frame / user_interrupt). */
  send(msg: WSResponse): void
  /** Register the handler for backend → frontend messages (commands + trace). */
  onMessage(handler: (data: unknown) => void): void
  close(): void
}

/** Real WebSocket transport. */
export class WebSocketTransport implements Transport {
  private ws: WebSocket
  private handler: ((data: unknown) => void) | null = null

  constructor(url: string) {
    this.ws = new WebSocket(url)
    this.ws.binaryType = 'arraybuffer'
    this.ws.addEventListener('message', (ev) => {
      let data: unknown
      try {
        data = typeof ev.data === 'string' ? JSON.parse(ev.data) : ev.data
      } catch {
        data = ev.data
      }
      this.handler?.(data)
    })
  }

  send(msg: WSResponse): void {
    if (this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg))
  }

  onMessage(handler: (data: unknown) => void): void {
    this.handler = handler
  }

  whenOpen(): Promise<void> {
    if (this.ws.readyState === WebSocket.OPEN) return Promise.resolve()
    return new Promise((resolve, reject) => {
      this.ws.addEventListener('open', () => resolve(), { once: true })
      this.ws.addEventListener('error', () => reject(new Error('WS error')), { once: true })
    })
  }

  close(): void { this.ws.close() }
}

/** In-process loopback: pairs the client with a mock backend, no network. */
export class LoopbackTransport implements Transport {
  private clientHandler: ((data: unknown) => void) | null = null
  /** Set by the mock backend to receive frontend → backend messages. */
  backendHandler: ((msg: WSResponse) => void) | null = null

  send(msg: WSResponse): void {
    this.backendHandler?.(msg)
  }

  onMessage(handler: (data: unknown) => void): void {
    this.clientHandler = handler
  }

  /** Mock backend → frontend (command / trace event). */
  emitToClient(data: unknown): void {
    this.clientHandler?.(data)
  }

  close(): void {
    this.clientHandler = null
    this.backendHandler = null
  }
}
