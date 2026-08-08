import { describe, it, expect, beforeEach } from 'vitest'
import { AgentWSClient } from './ws-client.ts'
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
 * v0.5 parked-proposal handling: the `proposal` command must NOT auto-reply.
 * It parks a resolver on the PanelBus (populated by the ProposalCard, built in
 * the next task) that, on operator decision, sends exactly one correlated
 * tool_result and clears the signal. A `complete` trace that arrives with a
 * still-pending proposal clears the signal WITHOUT sending (the run is over).
 */
class ProposalCleanupBridge {
  clearedProposalBox = 0
  clearedSelection = 0
  // v0.6: the operator's editable crop box (cyan gizmo channel) and the
  // agent's originally-previewed box (amber channel) are separate — the
  // resolver must read the former, falling back to the latter.
  cropBox: { min: number[]; max: number[] } | null = null
  proposalBox: { min: number[]; max: number[] } | null = null
  clearProposalBox(): void { this.clearedProposalBox++ }
  clearSelection(): number { this.clearedSelection++; return 0 }
  getCropBox() { return this.cropBox }
  getProposalBox() { return this.proposalBox }
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

  it('complete trace with a pending proposal clears the signal without sending', async () => {
    await transport.handler!(proposalCmd('p3', 'crop', 'crop it'))
    expect(panels.proposal.get()).not.toBeNull()
    transport.sent = []
    await transport.handler!({ type: 'complete', payload: {} })
    expect(panels.proposal.get()).toBeNull()
    expect(transport.sent).toEqual([])
    expect(bridge.clearedSelection).toBe(1)
  })
})

class FakeOverlay {
  markers: Array<{ position: [number, number, number]; label: string }> = []
  trailResets = 0
  dropMarker(position: [number, number, number], label: string): void { this.markers.push({ position, label }) }
  resetTrail(): void { this.trailResets += 1 }
}

class FakePanels {
  narrations: string[] = []
  setNarration(text: string): void { this.narrations.push(text) }
  pushTrace(): void {}
}

describe('ws-client command envelopes (dispatcher wraps everything as {tool, args})', () => {
  let transport: FakeTransport
  let overlay: FakeOverlay
  let panels: FakePanels

  beforeEach(() => {
    transport = new FakeTransport()
    overlay = new FakeOverlay()
    panels = new FakePanels()
    void new AgentWSClient(
      transport as unknown as Transport,
      {} as unknown as RendererBridge,
      overlay as unknown as Overlay,
      panels as unknown as PanelBus,
    )
  })

  function lastReplyPayload(): Record<string, unknown> {
    const msg = transport.sent[transport.sent.length - 1] as { payload?: Record<string, unknown> }
    return msg?.payload ?? {}
  }

  it('drop_marker reads position/label from p.args (the dispatcher envelope)', async () => {
    await transport.handler!({ type: 'drop_marker', id: 'c1', payload: { tool: 'drop_marker', args: { position: [1, 2, 3], label: 'floaters' } } })
    expect(overlay.markers).toEqual([{ position: [1, 2, 3], label: 'floaters' }])
    expect(lastReplyPayload().ok).toBe(true)
  })

  it('drop_marker rejects a malformed payload instead of throwing into a generic error', async () => {
    await transport.handler!({ type: 'drop_marker', id: 'c2', payload: { position: [1, 2, 3] } })
    expect(overlay.markers).toEqual([])
    expect(lastReplyPayload().ok).toBe(false)
  })

  it('narrate reads text from p.args and reports failure when both shapes are absent', async () => {
    await transport.handler!({ type: 'narrate', id: 'c3', payload: { tool: 'narrate', args: { text: 'scanning the ridge' } } })
    expect(panels.narrations).toEqual(['scanning the ridge'])
    expect(lastReplyPayload().ok).toBe(true)

    await transport.handler!({ type: 'narrate', id: 'c4', payload: { tool: 'narrate', args: {} } })
    expect(panels.narrations).toEqual(['scanning the ridge']) // no blank narration
    expect(lastReplyPayload().ok).toBe(false)
  })

  it('narrate still accepts the loop-event root shape {text} (ev_narrate has no args)', async () => {
    await transport.handler!({ type: 'narrate', payload: { text: 'Paused — the operator has control.' } })
    expect(panels.narrations).toEqual(['Paused — the operator has control.'])
  })

  it('reset_trail routed as camera_move actually resets the trail', async () => {
    await transport.handler!({ type: 'camera_move', id: 'c5', payload: { tool: 'reset_trail', args: {} } })
    expect(overlay.trailResets).toBe(1)
    expect(lastReplyPayload().ok).toBe(true)
  })

  it('an unknown camera tool is rejected, not silently succeeded', async () => {
    await transport.handler!({ type: 'camera_move', id: 'c6', payload: { tool: 'warp_drive', args: {} } })
    expect(lastReplyPayload().ok).toBe(false)
  })
})

/**
 * v0.8 subject lock-on: a keep_only_subject proposal parked after a
 * show_subject_preview must (a) surface the slider state on ProposalState,
 * (b) carry the CURRENT slider level back in the approved tool_result (the
 * backend keeps level_ids server-side and executes keep_only_ids from it),
 * and (c) tear the tint + module state down with the card — same rule as the
 * crop box: a DECIDED preview never outlives its card.
 */
class SubjectBridge {
  selection = new Set<number>()
  cleared = 0
  updateSelection(ids: Iterable<number>, mode: 'add' | 'remove' = 'add'): number {
    for (const id of ids) {
      if (mode === 'add') this.selection.add(id)
      else this.selection.delete(id)
    }
    return this.selection.size
  }
  clearSelection(): number { this.cleared++; this.selection.clear(); return 0 }
  selected(): number[] { return Array.from(this.selection).sort((a, b) => a - b) }
  getSelectionSummary() { return { count: 0, bbox: null } }
  getCropBox() { return null }
  getProposalBox() { return null }
  clearProposalBox(): void {}
}

describe('ws-client keep_only_subject proposal (slider level plumbing)', () => {
  let transport: FakeTransport
  let bridge: SubjectBridge
  let panels: PanelBus

  beforeEach(async () => {
    transport = new FakeTransport()
    bridge = new SubjectBridge()
    panels = new PanelBus()
    void new AgentWSClient(
      transport as unknown as Transport,
      bridge as unknown as RendererBridge,
      {} as unknown as Overlay,
      panels,
    )
    // Controller ships the complement + deltas, tinting level 1's DELETE-set.
    // Levels: K0=[1,2], K1=[1,2,3], K2=[1,2,3,4,5]; outside [6] (junk always).
    // Excluded per level: L0=[3,4,5,6], L1=[4,5,6], L2=[6].
    await transport.handler!({
      type: 'selection_tool', id: 's1',
      payload: {
        tool: 'show_subject_preview',
        args: { outside_ids: [6], deltas: [[3], [4, 5]], counts: [2, 3, 5], level: 1 },
      },
    })
  })

  it('show_subject_preview tints the requested level DELETE-set and replies with its count', () => {
    expect(transport.sent.at(-1)).toMatchObject({
      type: 'tool_result', id: 's1', payload: { ok: true, count: 3 },
    })
    expect(bridge.selected()).toEqual([4, 5, 6])
  })

  it('parks the card with slider state, and approve carries the current level then clears', async () => {
    await transport.handler!({
      type: 'proposal', id: 'p1',
      payload: { tool: 'propose_decision', args: { kind: 'keep_only_subject', summary: 'keep the subject' } },
    })
    const state = panels.proposal.get()
    expect(state!.subject).toMatchObject({ counts: [2, 3, 5], level: 1 })

    // Operator slides looser (keep more): the delete tint shrinks, locally.
    state!.subject!.onLevel(2)
    expect(bridge.selected()).toEqual([6])

    state!.resolve('approved')
    const reply = transport.sent.at(-1) as { id: string; payload: Record<string, unknown> }
    expect(reply.id).toBe('p1')
    expect(reply.payload).toMatchObject({ ok: true, verdict: 'approved', level: 2 })
    // decided preview comes down with the card
    expect(bridge.selected()).toEqual([])
  })

  it('reject clears the subject preview too and carries no level', async () => {
    await transport.handler!({
      type: 'proposal', id: 'p2',
      payload: { tool: 'propose_decision', args: { kind: 'keep_only_subject', summary: 's' } },
    })
    panels.proposal.get()!.resolve('rejected')
    const reply = transport.sent.at(-1) as { payload: Record<string, unknown> }
    expect(reply.payload.verdict).toBe('rejected')
    expect(reply.payload.level).toBeUndefined()
    expect(bridge.selected()).toEqual([])
  })
})

/**
 * Codex adversarial review: a mid-run reload MUST adopt the backend's alive
 * IDs. loadSplat alone leaves the viewer's ID map describing the pre-edit
 * scene, so the very next select_by_ids tint would highlight the wrong splats
 * — worse than not reloading at all.
 */
class ReloadBridge {
  loaded: string[] = []
  adopted: string[] = []
  adoptFails = false
  loadSplat(url: string): Promise<void> { this.loaded.push(url); return Promise.resolve() }
  async adoptAliveIds(sceneId: string): Promise<void> {
    if (this.adoptFails) throw new Error('ids fetch failed')
    this.adopted.push(sceneId)
  }
}

describe('ws-client reload_scene adopts the authoritative ID map', () => {
  let transport: FakeTransport
  let bridge: ReloadBridge

  beforeEach(() => {
    transport = new FakeTransport()
    bridge = new ReloadBridge()
    void new AgentWSClient(
      transport as unknown as Transport,
      bridge as unknown as RendererBridge,
      { resetTrail() {} } as unknown as Overlay,
      new PanelBus(),
    )
  })

  it('loads the scene and then adopts its ids', async () => {
    await transport.handler!({ type: 'reload_scene', id: 'r1', payload: { url: '/scene/s1.ply', scene_id: 's1' } })
    expect(bridge.loaded).toEqual(['/scene/s1.ply'])
    expect(bridge.adopted).toEqual(['s1'])
    expect(transport.sent.at(-1)).toMatchObject({ id: 'r1', payload: { ok: true } })
  })

  it('still replies when the id adoption fails (never hangs the run)', async () => {
    bridge.adoptFails = true
    await transport.handler!({ type: 'reload_scene', id: 'r2', payload: { url: '/scene/s1.ply', scene_id: 's1' } })
    expect(transport.sent.at(-1)).toMatchObject({ id: 'r2' })
  })

  it('skips adoption when no scene_id came with the command', async () => {
    await transport.handler!({ type: 'reload_scene', id: 'r3', payload: { url: '/scene/s1.ply' } })
    expect(bridge.loaded).toEqual(['/scene/s1.ply'])
    expect(bridge.adopted).toEqual([])
  })
})
