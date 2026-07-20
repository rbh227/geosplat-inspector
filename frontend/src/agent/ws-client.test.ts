import { describe, it, expect, beforeEach } from 'vitest'
import { AgentWSClient } from './ws-client.ts'
import type { RendererBridge } from './types.ts'
import type { Overlay } from './overlay.ts'
import type { PanelBus } from './panels.ts'
import type { Transport } from './transport.ts'

/**
 * Routing regression: the dispatcher packages every frontend command as
 * {tool, args} and WSChannel forwards that as the payload, so movement_input /
 * rotation_input MUST read direction/duration from p.args. Reading p directly
 * (the old bug) passed `undefined` to move_camera, which silently no-op'd — the
 * agent could never actually move. These tests drive the real executors through
 * a fake bridge and assert the input toggles reach it.
 */
class FakeTransport {
  handler: ((d: unknown) => void) | undefined
  sent: unknown[] = []
  onMessage(cb: (d: unknown) => void): void { this.handler = cb }
  send(m: unknown): void { this.sent.push(m) }
  close(): void {}
}

class FakeBridge {
  moves: Array<[string, boolean]> = []
  rots: Array<[string, boolean]> = []
  setMovementInput(d: string, a: boolean): void { this.moves.push([d, a]) }
  setRotationInput(d: string, a: boolean): void { this.rots.push([d, a]) }
}

function movementCmd(type: string, direction: string) {
  return { type, id: 'c1', payload: { tool: type === 'rotation_input' ? 'turn' : 'move_camera', args: { direction, duration_ms: 1 } } }
}

describe('ws-client movement/rotation routing (reads p.args)', () => {
  let transport: FakeTransport
  let bridge: FakeBridge

  beforeEach(() => {
    transport = new FakeTransport()
    bridge = new FakeBridge()
    // Constructing the client registers the transport handler (the side effect
    // under test); we drive it via transport.handler, so the instance is unused.
    void new AgentWSClient(
      transport as unknown as Transport,
      bridge as unknown as RendererBridge,
      {} as unknown as Overlay,
      {} as unknown as PanelBus,
    )
  })

  it('routes movement_input direction from p.args to setMovementInput (the bug regression)', async () => {
    await transport.handler!(movementCmd('movement_input', 'forward'))
    expect(bridge.moves).toContainEqual(['forward', true])
    expect(bridge.moves).toContainEqual(['forward', false])
  })

  it('routes rotation_input (turn) from p.args, mapping left -> yaw-left', async () => {
    await transport.handler!(movementCmd('rotation_input', 'left'))
    expect(bridge.rots).toContainEqual(['yaw-left', true])
    expect(bridge.rots).toContainEqual(['yaw-left', false])
  })

  it('maps every turn direction to the rotate-pad vocabulary', async () => {
    const cases: Array<[string, string]> = [
      ['right', 'yaw-right'], ['up', 'pitch-up'], ['down', 'pitch-down'],
    ]
    for (const [input, expected] of cases) {
      bridge.rots = []
      await transport.handler!(movementCmd('rotation_input', input))
      expect(bridge.rots).toContainEqual([expected, true])
    }
  })
})
