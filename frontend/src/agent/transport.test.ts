import { describe, it, expect, beforeEach, vi } from 'vitest'
import { WebSocketTransport } from './transport.ts'

class FakeWS {
  static last: FakeWS | null = null
  readyState = 0 // CONNECTING
  binaryType = ''
  private listeners = new Map<string, Array<(ev?: unknown) => void>>()
  constructor(public url: string) { FakeWS.last = this }
  addEventListener(type: string, cb: (ev?: unknown) => void): void {
    const arr = this.listeners.get(type) ?? []
    arr.push(cb)
    this.listeners.set(type, arr)
  }
  fire(type: string, ev: unknown = {}): void {
    ;(this.listeners.get(type) ?? []).forEach((cb) => cb(ev))
  }
  send(_m: string): void { void _m }
  close(): void { this.readyState = 3 }
}

describe('WebSocketTransport lifecycle', () => {
  beforeEach(() => {
    vi.stubGlobal('WebSocket', Object.assign(FakeWS, { OPEN: 1, CONNECTING: 0, CLOSED: 3 }))
  })

  it('fires onClose exactly once when the socket dies unexpectedly (close then error)', () => {
    const t = new WebSocketTransport('ws://x')
    let fired = 0
    t.onClose(() => { fired += 1 })
    FakeWS.last!.fire('close')
    FakeWS.last!.fire('error')
    expect(fired).toBe(1)
  })

  it('a deliberate close() does not fire onClose (scene switch is not a failure)', () => {
    const t = new WebSocketTransport('ws://x')
    let fired = 0
    t.onClose(() => { fired += 1 })
    t.close()
    FakeWS.last!.fire('close')
    expect(fired).toBe(0)
  })

  it('a handler registered after death fires immediately', () => {
    const t = new WebSocketTransport('ws://x')
    FakeWS.last!.fire('close')
    let fired = 0
    t.onClose(() => { fired += 1 })
    expect(fired).toBe(1)
  })

  it('send() on a non-open socket drops without throwing', () => {
    const t = new WebSocketTransport('ws://x')
    expect(() => t.send({ type: 'user_interrupt', id: 'i', payload: {} })).not.toThrow()
  })
})
