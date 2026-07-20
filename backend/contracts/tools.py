"""Tool contract registry (ARCHITECTURE.md §6.5).

v0.2 — editor phase. The contract freezes per phase: v0.1 froze the Phase-0
build; v0.2 adds spatial selection, movement, and selection-edit tools for the
editor-first rework (docs/plans/2026-07-05-001). Additions only — nothing is
removed or renamed.
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

# Quick lookups
TOOL_BY_NAME: dict[str, ToolEntry] = {t.name: t for t in TOOL_REGISTRY}
FRONTEND_TOOLS: set[str] = {t.name for t in TOOL_REGISTRY if t.runs_on == "frontend"}
BACKEND_TOOLS: set[str] = {t.name for t in TOOL_REGISTRY if t.runs_on == "backend"}
