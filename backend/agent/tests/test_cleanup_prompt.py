"""Prompt-CI for the Clean stage's model-facing surface.

v0.8.2: the crop-box flow is RETIRED from the agent surface (operator
decision, live 2026-08-07 — the freeform model followed the old good-cube
script and narrate-spiraled). These guards now enforce its ABSENCE: no box
tools offered, no box routine taught, cleanup routed to the app-run
controller. Live-model behavior is evaluated manually."""

from __future__ import annotations

from backend.agent.system_prompt import (
    build_tool_specs,
    skills_for,
    system_prompt_for,
)

_RETIRED_BOX_TOOLS = (
    "get_core_bounds", "show_box_preview", "adjust_box_preview",
    "crop_bbox", "crop_sphere",
)


def test_box_tools_offered_in_no_stage():
    for stage in ("clean", "understand"):
        names = {s.name for s in build_tool_specs(stage)}
        for tool in _RETIRED_BOX_TOOLS:
            assert tool not in names, f"{tool} must not be offered in {stage}"


def test_proposal_tool_still_offered_in_clean_only():
    assert "propose_decision" in {s.name for s in build_tool_specs("clean")}
    assert "propose_decision" not in {s.name for s in build_tool_specs("understand")}


def test_clean_prompt_teaches_the_proposal_flow_without_boxes():
    prompt = system_prompt_for("clean")
    assert "PROPOSE BEFORE DELETING" in prompt
    assert "BRUSH ROUNDS" in prompt
    assert "delete_selection" in prompt
    assert "bulk_edit" in prompt
    # scene-wide cleanup routes to the app-run controller, never tool-by-tool
    assert "SCENE-WIDE CLEANUP IS APP-RUN" in prompt
    # the retired box flow is GONE from the teaching text
    assert "GOOD-CUBE" not in prompt
    assert "crop_outside_box" not in prompt
    for tool in _RETIRED_BOX_TOOLS:
        assert tool not in prompt, f"{tool} must not be taught in Clean"


def test_understand_prompt_never_mentions_propose_decision():
    prompt = system_prompt_for("understand")
    assert "propose_decision" not in prompt
    for tool in _RETIRED_BOX_TOOLS:
        assert tool not in prompt


def test_cleanup_scene_skill_is_clean_only():
    clean_names = {s["name"] for s in skills_for("clean")}
    understand_names = {s["name"] for s in skills_for("understand")}
    assert "cleanup_scene" in clean_names
    assert "cleanup_scene" not in understand_names
    # the good-cube skill is gone entirely
    assert "trim_background" not in clean_names


def test_clean_recipes_route_through_propose_decision():
    clean = {s["name"]: s for s in skills_for("clean")}
    assert "propose_decision(kind='delete_selection')" in clean["clean_floaters"]["recipe"]


def test_cleanup_scene_recipe_is_app_run():
    """cleanup_scene is a controller routine, not a tool-by-tool recipe the
    model executes — and it no longer mentions a crop."""
    clean = {s["name"]: s for s in skills_for("clean")}
    recipe = clean["cleanup_scene"]["recipe"]
    assert "APP-RUN ROUTINE" in recipe
    assert "get_core_bounds" not in recipe
    assert "propose_decision" not in recipe
    assert "crop" not in recipe.lower()
    assert "select_by_brush" not in recipe
