"""Task 12 prompt-CI: the clean-stage prompt/skills/descriptions teach the v0.5
proposal flow, and the four proposal tools are offered in Clean but never in
Understand. Structural guards for the model-facing surface (modeled on
test_analyst_prompt.py); live-model behavior is evaluated manually."""

from __future__ import annotations

from backend.agent.system_prompt import (
    build_tool_specs,
    skills_for,
    system_prompt_for,
)

_V05_TOOLS = ("get_core_bounds", "show_box_preview", "adjust_box_preview", "propose_decision")


def test_v05_tools_absent_from_understand_specs():
    names = {s.name for s in build_tool_specs("understand")}
    for tool in _V05_TOOLS:
        assert tool not in names, f"{tool} must not be offered in Understand"


def test_v05_tools_present_in_clean_specs():
    names = {s.name for s in build_tool_specs("clean")}
    for tool in _V05_TOOLS:
        assert tool in names, f"{tool} must be offered in Clean"


def test_v05_tools_have_descriptions_not_bare_names():
    specs = {s.name: s for s in build_tool_specs("clean")}
    for tool in _V05_TOOLS:
        # description must be a real sentence, not the fallback (== the tool name)
        assert specs[tool].description != tool
        assert len(specs[tool].description) > len(tool)


def test_clean_prompt_teaches_the_proposal_flow():
    prompt = system_prompt_for("clean")
    assert "propose_decision" in prompt
    assert "get_core_bounds" in prompt
    # the flow rules: locked-until-approved, good-cube routine, brush rounds
    assert "PROPOSE BEFORE DELETING" in prompt
    assert "GOOD-CUBE ROUTINE" in prompt
    assert "BRUSH ROUNDS" in prompt
    assert "crop_outside_box" in prompt
    assert "delete_selection" in prompt
    # statistical sweeps are gated too (operator decision, 2026-07-22)
    assert "bulk_edit" in prompt


def test_understand_prompt_never_mentions_propose_decision():
    prompt = system_prompt_for("understand")
    assert "propose_decision" not in prompt
    for tool in _V05_TOOLS:
        assert tool not in prompt


def test_cleanup_scene_skill_is_clean_only():
    clean_names = {s["name"] for s in skills_for("clean")}
    understand_names = {s["name"] for s in skills_for("understand")}
    assert "cleanup_scene" in clean_names
    assert "cleanup_scene" not in understand_names


def test_clean_recipes_route_through_propose_decision():
    clean = {s["name"]: s for s in skills_for("clean")}
    assert "propose_decision(kind='delete_selection')" in clean["clean_floaters"]["recipe"]
    assert "propose_decision" in clean["trim_background"]["recipe"]
    assert "get_core_bounds" in clean["cleanup_scene"]["recipe"]
    assert "propose_decision(kind='crop_outside_box')" in clean["cleanup_scene"]["recipe"]


# ── v0.6: box sizing belongs to the operator ─────────────────────────────
def test_cleanup_recipe_hands_the_box_to_the_operator():
    """The model seeds the box and stops; the operator sizes it (v0.6)."""
    prompt = system_prompt_for("clean")
    lowered = prompt.lower()

    assert "the operator" in lowered
    # It must not promise to size the box itself.
    assert "adjust_box_preview only if the subject is clipped" not in lowered


def test_cleanup_recipe_no_longer_prescribes_brush_rounds():
    clean = {s["name"]: s for s in skills_for("clean")}
    assert "select_by_brush" not in clean["cleanup_scene"]["recipe"]
