/**
 * Shared contracts for GeoSplat Inspector (ARCHITECTURE.md §6.5, §6.7, §6.8).
 * v0.2 — editor phase. The contract freezes per phase; v0.2 adds spatial
 * selection, movement, and selection-edit tools plus the agent pause/resume
 * and selection-pull WS types (docs/plans/2026-07-05-001). Must stay in sync
 * with backend/contracts/tools.py.
 */

// ─── §6.2 Constants (mirrored from Python) ───

export const SH_C0 = 0.28209479177387814;
export const FLOATER_ALPHA = 0.05;
export const VISIBILITY_ALPHA = 0.10;
export const OUTLIER_K = 16;
export const OUTLIER_STD_RATIO = 2.0;
export const NEEDLE_RATIO = 10.0;
export const OVERSIZED_SCENE_FRAC = 0.05;
export const HIST_BINS = 50;
export const UNDO_STACK_MAX = 50;

// ─── §6.4 Metrics ───

export interface OpacityMetrics {
  histogram: number[];
  nearTransparentFraction: number;
  mean: number;
  median: number;
}

export interface AxisRatioMetrics {
  histogram: number[];
  needleFraction: number;
}

export interface ScaleMetrics {
  histogram: number[];
  oversizedFraction: number;
  axisRatio: AxisRatioMetrics;
}

export interface NNDistanceMetrics {
  mean: number;
  std: number;
  histogram: number[];
}

export interface SpatialMetrics {
  nnDistance: NNDistanceMetrics;
  outlierFraction: number;
  density: number;
}

export interface BoundsMetrics {
  min: [number, number, number];
  max: [number, number, number];
  volume: number;
}

export interface ColorMetrics {
  dcMean: [number, number, number];
  dcStd: [number, number, number];
}

export interface Metrics {
  gaussianCount: number;
  opacity: OpacityMetrics;
  scale: ScaleMetrics;
  spatial: SpatialMetrics;
  bounds: BoundsMetrics;
  color: ColorMetrics;
  computedAt: string;
  region: Record<string, unknown> | null;
}

// ─── §6.5 Tool contract ───

export type RunsOn = "backend" | "frontend";

export interface ToolEntry {
  name: string;
  runs_on: RunsOn;
  params: Record<string, unknown>;
  returns: string;
}

export const FRONTEND_TOOLS = [
  "look_at", "set_view", "orbit", "dolly", "scan_pause",
  "frame_object", "reset_view", "capture_frame", "capture_orbit",
  // v0.6 — app-owned analyst survey (app dispatches; never offered to the model)
  "survey_capture",
  "drop_marker", "clear_markers", "narrate", "reset_trail",
  // v0.2 — selection
  "select_by_brush", "select_by_lasso", "select_by_polygon",
  "select_by_sphere", "select_by_box",
  "invert_selection", "clear_selection", "get_selection_state",
  // v0.2 — movement
  "move_camera",
  // v0.3 — look/turn (rotate pad; button-only relative nav)
  "turn",
  // v0.4 — app-owned recovery: return to the operator's start view
  "reframe",
  // v0.5 — proposal (the crop-box surface was DELETED in v0.8.2)
  "propose_decision",
  // v0.7 — controller tint: exact stable ids (judgment-tour cleanup; the
  // CleanupController dispatches it, never the model)
  "select_by_ids",
  // v0.8 — subject-first cleanup: nested keep-levels shipped once, tint one
  // (CleanupController dispatches it, never the model)
  "show_subject_preview",
] as const;

export const BACKEND_TOOLS = [
  "get_metrics", "list_problem_regions",
  "opacity_threshold", "remove_outliers", "prune_oversized",
  "remove_needles",
  "recolor", "adjust_opacity", "truncate_sh",
  "snapshot", "undo", "redo", "export_ply", "answer",
  // v0.2 — selection editing (IDs pulled from the frontend at dispatch time)
  "delete_selection", "keep_selection",
] as const;

export type FrontendToolName = typeof FRONTEND_TOOLS[number];
export type BackendToolName = typeof BACKEND_TOOLS[number];
export type ToolName = FrontendToolName | BackendToolName;

// ─── §6.7 REST API endpoints ───

export const API = {
  /** POST — upload .ply, returns { id, count } */
  UPLOAD_SCENE: "/scene",
  /** GET — chunked .ply download */
  GET_SCENE: (id: string) => `/scene/${id}.ply` as const,
  /** GET — compute metrics, optional ?region=JSON */
  GET_METRICS: "/metrics",
  /** POST — { op, params, selection? } → { before, after, metrics } */
  EDIT: "/edit",
  /** POST — undo last edit */
  UNDO: "/undo",
  /** POST — redo last undone edit */
  REDO: "/redo",
  /** POST — { prompt } → streams over WS */
  AGENT_RUN: "/agent/run",
} as const;

// ─── §6.8 WebSocket message types ───

/** Backend → frontend commands */
export type WSCommandType =
  | "camera_move"
  | "capture_request"
  | "drop_marker"
  | "clear_markers"
  | "narrate"
  | "reload_scene"
  // v0.2: pull the current selection's stable splat IDs from the viewer
  | "get_selection"
  // v0.2: agent-driven selection/movement tools, executed on the shared
  // visible action layer (same code paths as manual tools)
  | "selection_tool"
  | "movement_input"
  // v0.2: rotate-pad input (was missing from this union — drift fix)
  | "rotation_input"
  // v0.5: blocking proposal — reply is parked until the operator decides
  | "proposal";

/**
 * Fields a proposal reply may carry.
 * v0.8 — `level` is the subject card's slider position (keep_only_subject
 * only). v0.8.2 — `box` was deleted with the crop-box flow.
 */
export const PROPOSAL_DECISION_FIELDS = ['verdict', 'feedback', 'level'] as const

/** Proposal kinds (mirror: tools.py propose_decision kind enum).
 *  v0.7 adds delete_clusters — the judgment-tour batch card.
 *  v0.8 adds keep_only_subject — the subject lock-on card.
 *  v0.8.2 deletes crop_outside_box with the crop-box flow. */
export const PROPOSAL_KINDS = [
  'delete_selection', 'keep_only_selection', 'bulk_edit',
  'delete_clusters', 'keep_only_subject',
] as const
export type ProposalKind = typeof PROPOSAL_KINDS[number]

/** v0.7 — judgment-tour batch proposal rows (mirror: tools.py clusters items). */
export const CLUSTER_ROW_FIELDS = ['label', 'count', 'verdict', 'reason', 'provenance'] as const
export interface ClusterRow {
  label: string
  count: number
  verdict: 'junk' | 'structure' | 'unsure'
  reason?: string
  provenance?: 'stats' | 'model' | 'both'
}

export interface WSCommand {
  type: WSCommandType;
  id: string;          // correlation ID for request/response
  payload: Record<string, unknown>;
}

/** Frontend → backend responses */
export type WSResponseType =
  | "frame"
  | "user_interrupt"
  // v0.2: correlated reply carrying the current selection's stable IDs
  | "selection"
  // v0.2: correlated reply for selection_tool / movement_input commands
  | "tool_result"
  // v0.2: stateful pause/resume signals — distinct from user_interrupt,
  // which aborts the run; pause holds it at the next tool-call boundary
  | "agent_pause"
  | "agent_resume";

export interface WSResponse {
  type: WSResponseType;
  id: string;          // matches the command's correlation ID
  payload: Record<string, unknown>;
}

/** Backend → frontend trace events (fire-and-forget) */
export type WSTraceType = "thought" | "tool_call" | "tool_result" | "complete";

export interface WSTraceEvent {
  type: WSTraceType;
  payload: Record<string, unknown>;
}

/** Union of all WS messages the frontend can receive */
export type WSIncoming = WSCommand | WSTraceEvent;
