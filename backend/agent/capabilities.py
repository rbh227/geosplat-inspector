"""Machine-readable capability launcher list (Tier 1-4, §7).

The frontend renders these as one-click launchers; each maps to an example
prompt the agent can run. Kept as data so the UI and the agent share one
source of truth.
"""

from __future__ import annotations

from typing import TypedDict


class Capability(TypedDict):
    id: str
    title: str
    tier: int
    description: str
    example_prompts: list[str]


CAPABILITIES: list[Capability] = [
    {
        "id": "navigate",
        "title": "Navigate",
        "tier": 1,
        "description": "Fly through the scene with paced camera moves, markers, and narration.",
        "example_prompts": [
            "Give me a guided fly-through of this scene.",
            "Orbit the main object slowly and point out anything unusual.",
        ],
    },
    {
        "id": "inspect",
        "title": "Inspect",
        "tier": 2,
        "description": "Measure reference-free quality metrics and rank problem regions.",
        "example_prompts": [
            "How clean is this scene? Give me the metrics.",
            "Where are the worst problem regions?",
        ],
    },
    {
        "id": "multi_angle",
        "title": "Multi-angle",
        "tier": 2,
        "description": "Capture an orbit of frames and reason about multi-view consistency.",
        "example_prompts": [
            "Look at the object from several angles and tell me if the surface is consistent.",
            "Are there floaters that only appear from certain views?",
        ],
    },
    {
        "id": "cleanup",
        "title": "Clean up",
        "tier": 3,
        "description": "Remove floaters/outliers/oversized/needles, crop, and export — reversibly.",
        "example_prompts": [
            "Clean up the floaters in this scene.",
            "Remove the spray of outliers around the object and export the result.",
        ],
    },
    {
        "id": "auto_clean",
        "title": "Auto-clean (closed loop)",
        "tier": 4,
        "description": "Detect -> fix -> verify -> keep/undo automatically, then report.",
        "example_prompts": [
            "Inspect and fix whatever is wrong, but verify each fix and undo anything that makes it worse.",
        ],
    },
]


def capability_index() -> dict[str, Capability]:
    return {c["id"]: c for c in CAPABILITIES}


__all__ = ["CAPABILITIES", "Capability", "capability_index"]
