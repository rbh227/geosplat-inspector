"""Tool contract registry (ARCHITECTURE.md §6.5). Frozen."""

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
