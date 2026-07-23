/**
 * Pure helpers for turning agent WS trace events into chat UI data.
 * Extracted from App so the bug-prone mapping is unit-testable.
 */
import type { AgentAction } from '../types/agent'

const CAMERA_TOOLS = new Set([
  'look_at', 'set_view', 'orbit', 'dolly', 'scan_pause', 'frame_object', 'reset_view',
])
const CAPTURE_TOOLS = new Set(['capture_frame', 'capture_orbit'])

/** Map a backend tool name to the chat action category. */
export function classifyAction(name: string): AgentAction['type'] {
  if (CAMERA_TOOLS.has(name)) return 'camera_move'
  if (CAPTURE_TOOLS.has(name)) return 'capture'
  if (name === 'answer') return 'answer'
  return 'cleanup'
}

/**
 * Chat content for a `complete` trace event's payload. Error wins over answer;
 * non-answer endings (step limit, operator stop) must say what happened — a
 * bare "Done." on an exhausted run reads as success and hides that the agent
 * simply ran out of turns.
 */
export function completeContent(detail: Record<string, unknown> | undefined): string {
  const error = detail?.error ? String(detail.error) : null
  if (error) return `Error: ${error}`
  const answer = detail?.answer ? String(detail.answer) : null
  if (answer) return answer
  const status = detail?.status ? String(detail.status) : null
  if (status === 'max_steps') return 'Run ended: step limit reached before finishing.'
  if (status === 'interrupted') return 'Stopped by the operator.'
  return 'Done.'
}

/** True when a `complete` payload records a real backend edit this run.
 *  Gates the authoritative reload: reloading reframes the scene, and a
 *  read-only survey must not yank the operator's camera the moment it ends. */
export function sceneChanged(detail: Record<string, unknown> | undefined): boolean {
  return detail?.scene_changed === true
}
