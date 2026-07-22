/**
 * /frontend/src/agent — the agent's hands and eyes wired onto the existing
 * renderer. Boundary: this folder only. Imports the FROZEN contract and a
 * narrow RendererBridge slice of the existing ViewerHandle (injected).
 *
 * Quick start (real backend):
 *   const t = new WebSocketTransport(wsUrl); await t.whenOpen();
 *   const agent = createAgent({ bridge: viewerHandle, transport: t });
 *
 * Quick start (mock, no server):
 *   const { transport, backend } = createMockTransport();
 *   const agent = createAgent({ bridge: viewerHandle, transport });
 *   await backend.runDemoInspection({ reloadUrl: '/examples/clean.ply' });
 */
import type { RendererBridge } from './types.ts'
import type { Transport } from './transport.ts'
import { Overlay } from './overlay.ts'
import { PanelBus } from './panels.ts'
import { AgentWSClient } from './ws-client.ts'

export interface Agent {
  client: AgentWSClient
  overlay: Overlay
  panels: PanelBus
  dispose(): void
}

export function createAgent(opts: {
  bridge: RendererBridge
  transport: Transport
  panels?: PanelBus
}): Agent {
  const panels = opts.panels ?? new PanelBus()
  const overlay = new Overlay(opts.bridge)
  const client = new AgentWSClient(opts.transport, opts.bridge, overlay, panels)

  return {
    client,
    overlay,
    panels,
    dispose() {
      overlay.dispose()
      opts.transport.close()
    },
  }
}

export { Overlay } from './overlay.ts'
export { PanelBus, CAPABILITY_CATALOG } from './panels.ts'
export type { Capability, ProposalState } from './panels.ts'
export { AgentWSClient } from './ws-client.ts'
export { WebSocketTransport, LoopbackTransport } from './transport.ts'
export type { Transport } from './transport.ts'
export { MockBackend, createMockTransport } from './mock-backend.ts'
export { capturePNG } from './capture.ts'
export type { RendererBridge, ToolResult, TraceEntry, CameraMovePayload } from './types.ts'
