"""Tool contract registry (ARCHITECTURE.md §6.5).

v0.2 — editor phase. The contract freezes per phase: v0.1 froze the Phase-0
build; v0.2 adds spatial selection, movement, and selection-edit tools for the
editor-first rework (docs/plans/2026-07-05-001). v0.3 adds the `turn` look tool
(rotate pad) for button-only relative navigation (docs/plans/2026-07-20-001).
v0.4 adds `reframe` — an app-owned "return to the operator's start view" recovery
op (docs/plans/2026-07-20-002). v0.5 adds the proposal / good-cube tools
(get_core_bounds, show_box_preview, adjust_box_preview, propose_decision) for the
propose-and-review cleanup flow (docs/superpowers/specs/2026-07-22-agent-cleanup-
proposals-design.md). v0.6 adds `survey_capture` — the app-owned analyst
survey (docs/superpowers/specs/2026-08-03-app-owned-survey-analyst-design.md).
v0.7 adds select_by_ids (controller tint), the delete_clusters proposal kind +
clusters payload rows, and CONTROLLER_CHOICE_SPECS — forced-choice schemas for
the judgment-tour cleanup controller, never dispatched (docs/superpowers/specs/
2026-08-04-judgment-tour-cleanup-design.md).
Additions only — nothing is removed or renamed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class ToolEntry:
    name: str
    runs_on: Literal["backend", "frontend"]
    params: dict  # JSON Schema
    returns: str  # short description of return shape


def _vec3(desc: str = "3-element array [x,y,z]") -> dict:
    return {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3, "description": desc}


def _dur() -> dict:
    return {"type": "number", "description": "Animation duration in ms"}


TOOL_REGISTRY: list[ToolEntry] = [
    # ── frontend (camera) ──
    ToolEntry("look_at", "frontend", {
        "type": "object",
        "properties": {"target": _vec3(), "duration_ms": _dur()},
        "required": ["target"],
    }, "ok"),
    ToolEntry("set_view", "frontend", {
        "type": "object",
        "properties": {"position": _vec3(), "target": _vec3(), "duration_ms": _dur()},
        "required": ["position", "target"],
    }, "ok"),
    ToolEntry("orbit", "frontend", {
        "type": "object",
        "properties": {
            "center": _vec3(),
            "deg": {"type": "number"},
            "axis": {"type": "string", "enum": ["x", "y", "z"]},
            "duration_ms": _dur(),
        },
        "required": ["center", "deg", "axis"],
    }, "ok"),
    ToolEntry("dolly", "frontend", {
        "type": "object",
        "properties": {"distance": {"type": "number"}, "duration_ms": _dur()},
        "required": ["distance"],
    }, "ok"),
    ToolEntry("scan_pause", "frontend", {
        "type": "object",
        "properties": {"ms": {"type": "number"}},
        "required": ["ms"],
    }, "ok"),
    ToolEntry("frame_object", "frontend", {
        "type": "object",
        "properties": {
            "bbox": {
                "type": "object",
                "properties": {"min": _vec3(), "max": _vec3()},
                "required": ["min", "max"],
            },
            "duration_ms": _dur(),
        },
        "required": ["bbox"],
    }, "ok"),
    ToolEntry("reset_view", "frontend", {
        "type": "object", "properties": {},
    }, "ok"),
    # v0.4 — app-owned recovery: return to the operator's start-of-run view.
    ToolEntry("reframe", "frontend", {
        "type": "object", "properties": {},
    }, "ok"),

    # ── frontend (capture) ──
    ToolEntry("capture_frame", "frontend", {
        "type": "object", "properties": {},
    }, "image bytes (PNG)"),
    ToolEntry("capture_orbit", "frontend", {
        "type": "object",
        "properties": {
            "center": _vec3(),
            "n": {"type": "integer", "description": "Number of frames"},
            "radius": {"type": "number"},
        },
        "required": ["center", "n"],
    }, "image bytes[]"),
    # v0.6 — app-owned survey (the app dispatches it; never offered to the
    # model): operator's view + framed top-down/oblique views in one round trip.
    ToolEntry("survey_capture", "frontend", {
        "type": "object",
        "properties": {
            "if_revision_not": {
                "type": "integer",
                "description": "Skip the flight and return {unchanged} if the "
                               "scene revision still equals this value",
            },
        },
    }, "image bytes[] + labels + revision"),

    # ── frontend (display) ──
    ToolEntry("drop_marker", "frontend", {
        "type": "object",
        "properties": {"position": _vec3(), "label": {"type": "string"}},
        "required": ["position", "label"],
    }, "ok"),
    ToolEntry("clear_markers", "frontend", {
        "type": "object", "properties": {},
    }, "ok"),
    ToolEntry("narrate", "frontend", {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }, "ok"),
    ToolEntry("reset_trail", "frontend", {
        "type": "object", "properties": {},
    }, "ok"),

    # ── frontend (selection) — v0.2 ──
    # Screen-space tools take viewport-normalized coordinates (0..1, origin
    # top-left). Volume tools take backend-space world coordinates (Y-down);
    # the frontend applies the render-space flip. All selection tools mutate
    # the viewer's current selection and return its summary — never raw IDs
    # (IDs cross to the backend via the get_selection WS pull, not the model).
    ToolEntry("select_by_brush", "frontend", {
        "type": "object",
        "properties": {
            "center_xy": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2,
                          "description": "Viewport-normalized [u,v], 0..1, origin top-left"},
            "radius": {"type": "number", "description": "Brush radius as a fraction of viewport height (0..1)"},
            "mode": {"type": "string", "enum": ["add", "remove"], "description": "Add to or remove from selection (default add)"},
        },
        "required": ["center_xy", "radius"],
    }, "{count, bbox}"),
    ToolEntry("select_by_lasso", "frontend", {
        "type": "object",
        "properties": {
            "points_xy": {"type": "array", "minItems": 3,
                          "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                          "description": "Freehand outline, viewport-normalized [u,v] points"},
            "mode": {"type": "string", "enum": ["add", "remove"]},
        },
        "required": ["points_xy"],
    }, "{count, bbox}"),
    ToolEntry("select_by_polygon", "frontend", {
        "type": "object",
        "properties": {
            "points_xy": {"type": "array", "minItems": 3,
                          "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                          "description": "Polygon vertices, viewport-normalized [u,v]; closed automatically"},
            "mode": {"type": "string", "enum": ["add", "remove"]},
        },
        "required": ["points_xy"],
    }, "{count, bbox}"),
    ToolEntry("select_by_sphere", "frontend", {
        "type": "object",
        "properties": {
            "center": _vec3("Sphere center in backend/world coords"),
            "radius": {"type": "number"},
            "mode": {"type": "string", "enum": ["add", "remove"]},
        },
        "required": ["center", "radius"],
    }, "{count, bbox}"),
    ToolEntry("select_by_box", "frontend", {
        "type": "object",
        "properties": {
            "min": _vec3("Box min corner, backend/world coords"),
            "max": _vec3("Box max corner, backend/world coords"),
            "mode": {"type": "string", "enum": ["add", "remove"]},
        },
        "required": ["min", "max"],
    }, "{count, bbox}"),
    ToolEntry("invert_selection", "frontend", {
        "type": "object", "properties": {},
    }, "{count, bbox}"),
    ToolEntry("clear_selection", "frontend", {
        "type": "object", "properties": {},
    }, "{count: 0}"),
    ToolEntry("get_selection_state", "frontend", {
        "type": "object", "properties": {},
    }, "{count, bbox}"),
    # v0.7 — controller tint: select EXACT stable ids (judgment-tour cleanup).
    # Dispatched by the CleanupController only; never offered to the model.
    ToolEntry("select_by_ids", "frontend", {
        "type": "object",
        "properties": {
            "ids": {"type": "array", "items": {"type": "integer"},
                    "description": "Stable splat ids to select"},
            "mode": {"type": "string", "enum": ["add", "remove", "replace"]},
        },
        "required": ["ids"],
    }, "{count, bbox}"),
    # v0.8 — subject-first cleanup: ship nested keep-levels to the viewer and
    # tint one. COMPLEMENT form: the keep-set is ~N ids (17MB of JSON on a
    # 2M-splat scene — live-found), the excluded set is the small one, so
    # that's what travels; the viewer derives each keep-tint locally as
    # invert-all-then-remove-excluded. Controller-dispatched only; never
    # offered to the model.
    ToolEntry("show_subject_preview", "frontend", {
        "type": "object",
        "properties": {
            "outside_ids": {"type": "array", "items": {"type": "integer"},
                            "description": "Stable ids EXCLUDED even at the "
                                           "loosest level (the junk)"},
            "deltas": {"type": "array",
                       "items": {"type": "array", "items": {"type": "integer"}},
                       "description": "Ids ADDED by each successive level"},
            "counts": {"type": "array", "items": {"type": "integer"}},
            "level": {"type": "integer",
                      "description": "Level to tint now (0 = tightest)"},
        },
        "required": ["level"],
    }, "{ok, count}"),

    # ── frontend (movement) — v0.2 ──
    ToolEntry("move_camera", "frontend", {
        "type": "object",
        "properties": {
            "direction": {"type": "string", "enum": ["forward", "back", "left", "right", "up", "down"],
                          "description": "Fly-mode movement direction (W/S/A/D/up/down)"},
            "duration_ms": {"type": "number", "description": "How long to hold the input"},
        },
        "required": ["direction", "duration_ms"],
    }, "ok"),
    # ── frontend (look/turn) — v0.3 (rotate pad; button-only relative nav) ──
    ToolEntry("turn", "frontend", {
        "type": "object",
        "properties": {
            "direction": {"type": "string", "enum": ["left", "right", "up", "down"],
                          "description": "Look direction (yaw left/right, pitch up/down) — the rotate pad"},
            "duration_ms": {"type": "number", "description": "How long to hold the input"},
        },
        "required": ["direction", "duration_ms"],
    }, "ok"),

    # ── frontend (proposal / good-cube) — v0.5 ──
    # The proposal surface (docs/superpowers/specs/2026-07-22-agent-cleanup-
    # proposals-design.md): preview a region, then BLOCK on the operator's
    # verdict. Clean-stage only; coordinates are backend space.
    ToolEntry("get_core_bounds", "frontend", {
        "type": "object", "properties": {},
    }, "{min, max, count} — robust (5th-95th pct) core box"),
    ToolEntry("show_box_preview", "frontend", {
        "type": "object",
        "properties": {
            "min": _vec3("Box min corner, backend coords"),
            "max": _vec3("Box max corner, backend coords"),
        },
        "required": ["min", "max"],
    }, "{ok, min, max}"),
    ToolEntry("adjust_box_preview", "frontend", {
        "type": "object",
        "properties": {
            "grow": {"type": "number",
                     "description": "Uniform scale about the box center (1.2 = 20% bigger)"},
            "grow_axes": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3,
                          "description": "Per-view-axis scale [right, up, forward]"},
            "shift": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3,
                      "description": "Move by [right, up, forward] in units of the box's own size, "
                                     "relative to the OPERATOR'S current view"},
        },
    }, "{ok, min, max}"),
    ToolEntry("propose_decision", "frontend", {
        "type": "object",
        "properties": {
            "kind": {"type": "string",
                     "enum": ["crop_outside_box", "delete_selection", "keep_only_selection", "bulk_edit",
                              "delete_clusters", "keep_only_subject"],
                     "description": "delete_selection deletes the selected splats; "
                                    "keep_only_selection deletes everything EXCEPT them — "
                                    "materially different consent, so distinct kinds. "
                                    "delete_clusters (v0.7) is the judgment-tour batch card. "
                                    "keep_only_subject (v0.8) is the subject lock-on card — "
                                    "its reply may carry the slider's level"},
            "summary": {"type": "string",
                        "description": "One or two sentences the operator reads before deciding"},
            "operation": {
                "type": "object",
                "description": "REQUIRED for kind 'bulk_edit': the exact sweep the "
                               "approval authorizes — nothing else will run",
                "properties": {
                    "tool": {"type": "string",
                             "enum": ["opacity_threshold", "remove_outliers",
                                      "prune_oversized", "remove_needles"]},
                    "params": {"type": "object"},
                },
                "required": ["tool"],
            },
            # v0.7 — delete_clusters only: the reviewed rows the operator sees
            "clusters": {
                "type": "array",
                "description": "delete_clusters only: the reviewed rows",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "count": {"type": "integer"},
                        "verdict": {"type": "string",
                                    "enum": ["junk", "structure", "unsure"]},
                        "reason": {"type": "string"},
                        "provenance": {"type": "string",
                                       "enum": ["stats", "model", "both"]},
                    },
                    "required": ["label", "count", "verdict"],
                },
            },
        },
        "required": ["kind", "summary"],
    }, "{verdict: approved|rejected|adjusted, feedback?}"),

    # ── backend (analysis) ──
    ToolEntry("get_metrics", "backend", {
        "type": "object",
        "properties": {
            "region": {
                "type": "object",
                "properties": {"min": _vec3(), "max": _vec3()},
                "required": ["min", "max"],
            },
        },
    }, "Metrics"),
    ToolEntry("list_problem_regions", "backend", {
        "type": "object", "properties": {},
    }, "ranked regions w/ bboxes"),

    # ── backend (editing) ──
    ToolEntry("opacity_threshold", "backend", {
        "type": "object",
        "properties": {"min_alpha": {"type": "number"}},
        "required": ["min_alpha"],
    }, "before/after counts"),
    ToolEntry("remove_outliers", "backend", {
        "type": "object",
        "properties": {
            "k": {"type": "integer"},
            "std_ratio": {"type": "number"},
        },
        "required": ["k", "std_ratio"],
    }, "before/after counts"),
    ToolEntry("prune_oversized", "backend", {
        "type": "object",
        "properties": {"max_axis_scene_frac": {"type": "number"}},
        "required": ["max_axis_scene_frac"],
    }, "before/after counts"),
    ToolEntry("remove_needles", "backend", {
        "type": "object",
        "properties": {"max_axis_ratio": {"type": "number"}},
        "required": ["max_axis_ratio"],
    }, "before/after counts"),
    ToolEntry("crop_bbox", "backend", {
        "type": "object",
        "properties": {"min": _vec3(), "max": _vec3()},
        "required": ["min", "max"],
    }, "before/after counts"),
    ToolEntry("crop_sphere", "backend", {
        "type": "object",
        "properties": {
            "center": _vec3(),
            "radius": {"type": "number"},
            "invert": {"type": "boolean"},
        },
        "required": ["center", "radius"],
    }, "before/after counts"),
    ToolEntry("recolor", "backend", {
        "type": "object",
        "properties": {
            "selection": {"type": "object"},
            "rgb": _vec3("RGB [0-1]"),
        },
        "required": ["selection", "rgb"],
    }, "ok"),
    ToolEntry("adjust_opacity", "backend", {
        "type": "object",
        "properties": {
            "selection": {"type": "object"},
            "factor": {"type": "number"},
        },
        "required": ["selection", "factor"],
    }, "ok"),
    ToolEntry("truncate_sh", "backend", {
        "type": "object",
        "properties": {"degree": {"type": "integer", "minimum": 0, "maximum": 3}},
        "required": ["degree"],
    }, "ok"),

    # ── backend (selection editing) — v0.2 ──
    # These act on the viewer's current selection: dispatch pulls the stable
    # splat IDs from the frontend (get_selection WS command), then the editing
    # engine masks by ID and snapshots the shared history.
    ToolEntry("delete_selection", "backend", {
        "type": "object", "properties": {},
    }, "before/after counts"),
    ToolEntry("keep_selection", "backend", {
        "type": "object", "properties": {},
    }, "before/after counts"),

    # ── backend (history) ──
    ToolEntry("snapshot", "backend", {
        "type": "object", "properties": {},
    }, "ok"),
    ToolEntry("undo", "backend", {
        "type": "object", "properties": {},
    }, "ok"),
    ToolEntry("redo", "backend", {
        "type": "object", "properties": {},
    }, "ok"),
    ToolEntry("export_ply", "backend", {
        "type": "object", "properties": {},
    }, "path"),
    ToolEntry("answer", "backend", {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }, "ends run"),
]

# v0.6 — fields a proposal reply may carry. `box` is the operator's edited crop
# box in backend coordinates; on an `approved` verdict the backend rebinds the
# approval to it (mirror: frontend/src/contracts.ts PROPOSAL_DECISION_FIELDS).
# v0.8 — `level` is the subject card's slider position (keep_only_subject only).
PROPOSAL_DECISION_FIELDS: tuple[str, ...] = ("verdict", "feedback", "box", "level")

# v0.7 — forced-choice schemas for the CleanupController. These are provider
# ToolSpec dicts (name/description/parameters), NOT registry entries: the
# controller offers exactly one of them per model call and dispatches nothing.
CONTROLLER_CHOICE_SPECS: dict[str, dict] = {
    "mark_noise": {
        "name": "mark_noise",
        "description": "Mark grid cells that contain floating junk, debris "
                       "mist, or disconnected fragments. Empty list if none.",
        "parameters": {
            "type": "object",
            "properties": {
                "cells": {"type": "array", "items": {"type": "string"},
                          "description": "Cell labels like B3 (columns A-D, rows 1-4)"},
                "note": {"type": "string"},
            },
            "required": ["cells"],
        },
    },
    "judge_candidate": {
        "name": "judge_candidate",
        "description": "Judge the highlighted cluster.",
        "parameters": {
            "type": "object",
            "properties": {
                "verdict": {"type": "string",
                            "enum": ["junk", "structure", "look_closer"]},
                "reason": {"type": "string", "description": "One short sentence"},
            },
            "required": ["verdict", "reason"],
        },
    },
    # v0.8.1 — scene-hull lock-on: the model OUTLINES the actual scene per
    # survey view (figure/ground — the easy question); code carves the 3D
    # keep-set from the outlines by reprojection. Reasoning leads, the
    # density/scale statistics are the safety floor.
    "outline_scene": {
        "name": "outline_scene",
        "description": "Outline the tightest box containing the ACTUAL scene "
                       "— the coherent reconstructed structure. Exclude "
                       "floating junk, debris mist, streaks, and disconnected "
                       "fragments. Full box if the scene fills the view.",
        "parameters": {
            "type": "object",
            # 0-1000 integer space — Qwen-VL's native grounding convention
            # (it answers in it regardless of what the schema requests; the
            # controller normalizes 0..1 replies too).
            "properties": {
                "x0": {"type": "number", "description": "left edge, 0-1000"},
                "y0": {"type": "number", "description": "top edge, 0-1000"},
                "x1": {"type": "number", "description": "right edge, 0-1000"},
                "y1": {"type": "number", "description": "bottom edge, 0-1000"},
            },
            "required": ["x0", "y0", "x1", "y1"],
        },
    },
    # v0.8 — subject-first cleanup: per-view vote on the tinted keep-region.
    "judge_subject": {
        "name": "judge_subject",
        "description": "Judge whether the bright-tinted keep-region matches "
                       "the real structure.",
        "parameters": {
            "type": "object",
            "properties": {
                "verdict": {"type": "string",
                            "enum": ["good", "clipping_structure", "including_junk"]},
                "reason": {"type": "string", "description": "One short sentence"},
            },
            "required": ["verdict", "reason"],
        },
    },
}

# Quick lookups
TOOL_BY_NAME: dict[str, ToolEntry] = {t.name: t for t in TOOL_REGISTRY}
FRONTEND_TOOLS: set[str] = {t.name for t in TOOL_REGISTRY if t.runs_on == "frontend"}
BACKEND_TOOLS: set[str] = {t.name for t in TOOL_REGISTRY if t.runs_on == "backend"}

__all__ = [
    "ToolEntry",
    "TOOL_REGISTRY",
    "TOOL_BY_NAME",
    "FRONTEND_TOOLS",
    "BACKEND_TOOLS",
    "PROPOSAL_DECISION_FIELDS",
    "CONTROLLER_CHOICE_SPECS",
]
