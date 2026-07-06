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
 * a bare completion with neither falls back to "Done."
 */
export function completeContent(detail: Record<string, unknown> | undefined): string {
  const error = detail?.error ? String(detail.error) : null
  if (error) return `Error: ${error}`
  const answer = detail?.answer ? String(detail.answer) : null
  return answer ?? 'Done.'
}
