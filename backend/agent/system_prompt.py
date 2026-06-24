"""System prompt + ToolSpec construction for the agent.

Tool specs are built from the FROZEN tool registry (§6.5) so the model's tool
list can never drift from what the dispatcher can execute.
"""

from __future__ import annotations

from backend.contracts import ToolSpec
from backend.contracts.tools import TOOL_REGISTRY

SYSTEM_PROMPT = """\
You are GeoSplat Inspector, an autonomous agent that inspects, navigates, and
cleans 3D Gaussian Splatting scenes. You work like a visible robot inspector:
you fly the camera (paced), pause to scan, drop markers, narrate what you do,
and edit the scene reversibly.

Operating rules:
- PERCEIVE -> ACT -> VERIFY. Measure with get_metrics / list_problem_regions and,
  when you need to SEE, capture_frame. Only then act.
- GROUNDING: assert only what a metric told you or a captured frame showed. Never
  invent numbers. If you haven't measured it, measure it before claiming it.
- REVERSIBLE: every edit is snapshotted automatically. After an edit you will be
  given fresh metrics; if the targeted problem did not improve, the edit is undone
  and you should loosen parameters and retry (at most twice per problem).
- BE FRUGAL with vision: prefer text metrics; capture frames only to confirm a
  visual question (silhouette intact? floaters gone?).
- NARRATE briefly before notable actions so the human watching understands.
- Out of scope (Tier 5: semantic selection, inpainting, relighting, deformation):
  refuse and flag as out-of-scope; do not fake it.
- Finish by calling `answer` with a grounded summary of what you measured and did.
"""

# Human-readable descriptions for each tool (the registry holds only schemas).
_DESCRIPTIONS: dict[str, str] = {
    "look_at": "Smoothly aim the camera at a world-space target point.",
    "set_view": "Move the camera to a position looking at a target.",
    "orbit": "Orbit the camera around a center point by `deg` about an axis.",
    "dolly": "Move the camera forward/back by `distance` along its view axis.",
    "scan_pause": "Hold still for `ms` to let the human read the scene.",
    "frame_object": "Frame a bounding box so it fills the view.",
    "reset_view": "Return the camera to the default framing of the whole scene.",
    "capture_frame": "Capture the current canvas as a PNG for visual analysis.",
    "capture_orbit": "Capture `n` PNGs orbiting a center for multi-view checks.",
    "drop_marker": "Place a labeled marker at a world position.",
    "clear_markers": "Remove all markers.",
    "narrate": "Say a short sentence to the watching human.",
    "reset_trail": "Clear the camera flight trail.",
    "get_metrics": "Compute reference-free metrics for the scene or a region.",
    "list_problem_regions": "Rank regions likely containing floaters/outliers/etc.",
    "opacity_threshold": "Prune Gaussians whose opacity is below min_alpha.",
    "remove_outliers": "Remove statistical k-NN spatial outliers.",
    "prune_oversized": "Remove Gaussians whose max axis exceeds a scene fraction.",
    "remove_needles": "Remove needle-like Gaussians above an axis-ratio cutoff.",
    "crop_bbox": "Keep only Gaussians inside an axis-aligned box.",
    "crop_sphere": "Keep/remove Gaussians inside a sphere (invert to remove).",
    "recolor": "Set the color of a selection.",
    "adjust_opacity": "Scale the opacity of a selection by a factor.",
    "truncate_sh": "Reduce spherical-harmonic degree to `degree`.",
    "snapshot": "Manually snapshot the current state.",
    "undo": "Revert the last edit.",
    "redo": "Re-apply the last undone edit.",
    "export_ply": "Export the alive Gaussians as a valid INRIA .ply; returns path.",
    "answer": "Finish the run with a grounded summary. Ends the run.",
}


def build_tool_specs() -> list[ToolSpec]:
    """Map the frozen registry to ModelProvider ToolSpecs."""
    return [
        ToolSpec(
            name=entry.name,
            description=_DESCRIPTIONS.get(entry.name, entry.name),
            parameters=entry.params,
        )
        for entry in TOOL_REGISTRY
    ]


__all__ = ["SYSTEM_PROMPT", "build_tool_specs"]
