import { describe, it, expect, beforeEach } from 'vitest'
import * as THREE from 'three'
import { AgentWSClient } from './ws-client.ts'
import { FrontendExecutors } from './executors.ts'
import { PanelBus } from './panels.ts'
import type { RendererBridge } from './types.ts'
import type { Overlay } from './overlay.ts'
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

/**
 * v0.5 parked-proposal handling: the `proposal` command must NOT auto-reply.
 * It parks a resolver on the PanelBus (populated by the ProposalCard, built in
 * the next task) that, on operator decision, sends exactly one correlated
 * tool_result and clears the signal. A `complete` trace that arrives with a
 * still-pending proposal clears the signal WITHOUT sending (the run is over).
 */
class ProposalCleanupBridge {
  clearedProposalBox = 0
  clearedSelection = 0
  clearProposalBox(): void { this.clearedProposalBox++ }
  clearSelection(): number { this.clearedSelection++; return 0 }
}

describe('ws-client proposal command (parked reply)', () => {
  let transport: FakeTransport
  let panels: PanelBus
  let bridge: ProposalCleanupBridge

  beforeEach(() => {
    transport = new FakeTransport()
    panels = new PanelBus()
    bridge = new ProposalCleanupBridge()
    void new AgentWSClient(
      transport as unknown as Transport,
      bridge as unknown as RendererBridge,
      {} as unknown as Overlay,
      panels,
    )
  })

  function proposalCmd(id: string, kind: string, summary: string) {
    return { type: 'proposal', id, payload: { tool: 'proposal', args: { kind, summary } } }
  }

  it('parks the proposal — no reply sent, signal populated with kind/summary', async () => {
    await transport.handler!(proposalCmd('p1', 'crop', 'crop outside the good cube'))
    expect(transport.sent).toEqual([])
    const state = panels.proposal.get()
    expect(state).not.toBeNull()
    expect(state!.kind).toBe('crop')
    expect(state!.summary).toBe('crop outside the good cube')
  })

  it('resolve(adjusted, bigger) sends exactly one correlated tool_result then clears the signal', async () => {
    await transport.handler!(proposalCmd('p2', 'crop', 'crop it'))
    panels.proposal.get()!.resolve('adjusted', 'bigger')
    expect(transport.sent).toEqual([
      { type: 'tool_result', id: 'p2', payload: { ok: true, verdict: 'adjusted', feedback: 'bigger' } },
    ])
    expect(panels.proposal.get()).toBeNull()
  })

  it('resolver is idempotent — a double-click sends exactly one tool_result', async () => {
    await transport.handler!(proposalCmd('p4', 'crop', 'crop it'))
    const state = panels.proposal.get()!
    state.resolve('approved')
    state.resolve('approved')
    expect(transport.sent).toEqual([
      { type: 'tool_result', id: 'p4', payload: { ok: true, verdict: 'approved' } },
    ])
    expect(panels.proposal.get()).toBeNull()
  })

  it('carries the canonical operation through to the ProposalState (summary can lie; operation cannot)', async () => {
    await transport.handler!({
      type: 'proposal', id: 'p7',
      payload: {
        tool: 'proposal',
        args: {
          kind: 'bulk_edit',
          summary: 'gentle cleanup',  // model-authored — may disagree with the payload
          operation: { tool: 'remove_outliers', params: { k: 8, std_ratio: 2 } },
        },
      },
    })
    const state = panels.proposal.get()
    expect(state!.operation).toEqual({ tool: 'remove_outliers', params: { k: 8, std_ratio: 2 } })
  })

  it('a malformed operation (no tool string) surfaces as null, never a broken object', async () => {
    await transport.handler!({
      type: 'proposal', id: 'p8',
      payload: { tool: 'proposal', args: { kind: 'bulk_edit', summary: 's', operation: { params: { k: 1 } } } },
    })
    expect(panels.proposal.get()!.operation).toBeNull()
  })

  it('a second proposal never clobbers a parked one — it is reply-rejected immediately', async () => {
    await transport.handler!(proposalCmd('p5', 'crop', 'first — awaiting review'))
    await transport.handler!(proposalCmd('p6', 'crop', 'second — must not park'))
    // the second command got an immediate rejected reply on ITS id
    expect(transport.sent).toEqual([
      {
        type: 'tool_result', id: 'p6',
        payload: { ok: false, verdict: 'rejected', feedback: 'another proposal is already awaiting review' },
      },
    ])
    // the FIRST proposal is still parked and still resolvable
    const state = panels.proposal.get()
    expect(state!.summary).toBe('first — awaiting review')
    state!.resolve('approved')
    expect(transport.sent[1]).toEqual({
      type: 'tool_result', id: 'p5', payload: { ok: true, verdict: 'approved' },
    })
  })

  it('complete trace with a pending proposal clears the signal without sending and calls clearProposalBox', async () => {
    await transport.handler!(proposalCmd('p3', 'crop', 'crop it'))
    expect(panels.proposal.get()).not.toBeNull()
    transport.sent = []
    await transport.handler!({ type: 'complete', payload: {} })
    expect(panels.proposal.get()).toBeNull()
    expect(transport.sent).toEqual([])
    expect(bridge.clearedProposalBox).toBe(1)
    expect(bridge.clearedSelection).toBe(1)
  })
})
