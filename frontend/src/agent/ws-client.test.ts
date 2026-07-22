import { describe, it, expect, beforeEach } from 'vitest'
import * as THREE from 'three'
import { AgentWSClient } from './ws-client.ts'
import { FrontendExecutors } from './executors.ts'
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

/**
 * v0.5 proposal / good-cube surface: the three selection_tool cases that seed a
 * crop box from the detected core and preview/adjust it view-relatively. Driven
 * straight through runSelectionTool with a stub bridge (no transport needed).
 */
class ProposalBridge {
  coreBox: { min: number[]; max: number[]; count: number } | null = { min: [0, 0, 0], max: [2, 2, 2], count: 42 }
  proposal: { min: number[]; max: number[] } | null = null
  shown: Array<{ min: number[]; max: number[] }> = []
  getCoreBoundsBox() { return this.coreBox }
  showProposalBox(min: number[], max: number[]): void {
    this.proposal = { min, max }
    this.shown.push({ min, max })
  }
  clearProposalBox(): void { this.proposal = null }
  getProposalBox() { return this.proposal }
  getCamera(): THREE.PerspectiveCamera { return new THREE.PerspectiveCamera() }
}

describe('runSelectionTool v0.5 proposal tools', () => {
  let bridge: ProposalBridge
  let ex: FrontendExecutors

  beforeEach(() => {
    bridge = new ProposalBridge()
    ex = new FrontendExecutors(bridge as unknown as RendererBridge, {} as unknown as Overlay)
  })

  it('get_core_bounds returns the seeded core box', async () => {
    const r = await ex.runSelectionTool('get_core_bounds', {})
    expect(r).toEqual({ ok: true, min: [0, 0, 0], max: [2, 2, 2], count: 42 })
  })

  it('get_core_bounds returns an error when no scene is loaded', async () => {
    bridge.coreBox = null
    const r = await ex.runSelectionTool('get_core_bounds', {})
    expect(r).toEqual({ ok: false, error: 'no scene loaded' })
  })

  it('show_box_preview shows the box and echoes it', async () => {
    const r = await ex.runSelectionTool('show_box_preview', { min: [0, 0, 0], max: [2, 2, 2] })
    expect(r).toEqual({ ok: true, min: [0, 0, 0], max: [2, 2, 2] })
    expect(bridge.proposal).toEqual({ min: [0, 0, 0], max: [2, 2, 2] })
  })

  it('show_box_preview rejects a malformed box', async () => {
    const r = await ex.runSelectionTool('show_box_preview', { min: [0, 0], max: [2, 2, 2] })
    expect(r).toEqual({ ok: false, error: 'min/max must be [x,y,z]' })
    expect(bridge.proposal).toBeNull()
  })

  it('adjust_box_preview with no active box returns an error', async () => {
    const r = await ex.runSelectionTool('adjust_box_preview', { grow: 2 })
    expect(r).toEqual({ ok: false, error: 'no box preview active — call show_box_preview first' })
  })

  it('adjust_box_preview grows the active box about its center and re-shows it', async () => {
    bridge.proposal = { min: [0, 0, 0], max: [2, 2, 2] }
    const r = await ex.runSelectionTool('adjust_box_preview', { grow: 2 }) as { ok: boolean; min: number[]; max: number[] }
    expect(r.ok).toBe(true)
    // uniform grow=2 about center [1,1,1] -> half-extent doubles to 2 each axis
    expect(r.min).toEqual([-1, -1, -1])
    expect(r.max).toEqual([3, 3, 3])
    expect(bridge.proposal).toEqual({ min: [-1, -1, -1], max: [3, 3, 3] })
  })
})
