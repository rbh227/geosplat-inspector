export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: number
  actions?: AgentAction[]
  thumbnail?: string
}

export interface AgentAction {
  type: 'camera_move' | 'cleanup' | 'capture' | 'answer'
  label: string
  detail?: string
  before?: string
  after?: string
  removedCount?: number
}

export type ToolName =
  | 'look_at'
  | 'set_view'
  | 'orbit'
  | 'dolly'
  | 'capture_frame'
  | 'clean_opacity'
  | 'remove_outliers'
  | 'crop_bbox'
  | 'get_scene_stats'
  | 'filter_by_scale'
  | 'filter_by_color'
  | 'filter_by_density'
  | 'filter_by_height'
  | 'auto_clean'
  | 'undo'
  | 'answer'

export interface ToolCall {
  name: ToolName
  input: Record<string, unknown>
}

export interface ToolResult {
  name: ToolName
  result: string
  image?: string
}

export interface AgentConfig {
  apiKey: string
  model: string
  maxSteps: number
}
