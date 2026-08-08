"""U9 stage gating (R12/R15, AE2): the Understand stage offers zero mutating
tools, rejects hallucinated edit calls at dispatch, and the skills vocabulary
serves the same names the prompt renders (R11)."""

from __future__ import annotations

import asyncio

from backend.agent.config import AgentConfig
from backend.agent.loop import AgentLoop
from backend.agent.mocks import MockBackendExecutor, MockFrontendChannel, MockProvider, tool_turn
from backend.agent.dispatch import ToolDispatcher
from backend.agent.system_prompt import (
    SKILLS,
    TELEPORT_TOOLS,
    UNDERSTAND_TOOLS,
    build_tool_specs,
    skills_for,
    stage_tools,
    system_prompt_for,
)
from backend.agent.types import DESTRUCTIVE_TOOLS
from backend.contracts.tools import TOOL_REGISTRY

MUTATING = DESTRUCTIVE_TOOLS | {
    "snapshot", "undo", "redo", "export_ply",
    "select_by_brush", "select_by_lasso", "select_by_polygon",
    "select_by_sphere", "select_by_box", "invert_selection", "clear_selection",
}


def test_understand_specs_contain_zero_mutating_tools():
    names = {spec.name for spec in build_tool_specs("understand")}
    assert names & MUTATING == set()
    # look-only surface: navigation + capture + display + movement + answer
    assert names == UNDERSTAND_TOOLS


def test_clean_specs_contain_the_full_registry_minus_teleports():
    # Button-only nav (docs/plans/2026-07-20-001): the teleport/absolute camera
    # tools are removed from BOTH stages' offered sets. v0.6/v0.7: the
    # app-dispatched tools (survey_capture, select_by_ids) are removed too —
    # the loop/CleanupController drives those, never the model.
    from backend.agent.system_prompt import CONTROLLER_ONLY_TOOLS, RETIRED_BOX_TOOLS

    names = {spec.name for spec in build_tool_specs("clean")}
    assert names == (
        {t.name for t in TOOL_REGISTRY}
        - TELEPORT_TOOLS - CONTROLLER_ONLY_TOOLS - RETIRED_BOX_TOOLS
    )
    assert names.isdisjoint(TELEPORT_TOOLS)
    assert names.isdisjoint(CONTROLLER_ONLY_TOOLS)
    assert names.isdisjoint(RETIRED_BOX_TOOLS)   # v0.8.2 — no crop-box flow
    assert {"move_camera", "turn", "dolly"} <= names


def test_understand_loop_rejects_edit_calls_without_dispatching():
    """AE2 backstop: a hallucinated delete never reaches the dispatcher."""
    executor = MockBackendExecutor()
    channel = MockFrontendChannel()
    provider = MockProvider(script=[
        tool_turn(("delete_selection", {})),
        tool_turn(("answer", {"text": "done"})),
    ])
    dispatcher = ToolDispatcher(executor, channel)
    config = AgentConfig(enforce_grounding=False)
    loop = AgentLoop(provider, dispatcher, channel, config=config, stage="understand")
    result = asyncio.run(loop.run("clean this up"))

    assert result.status == "answered"
    # the edit was rejected at the loop boundary: no get_selection pull, no edit
    assert all(c.get("type") != "get_selection" for c in channel.commands)
    rejections = [
        e for e in result.trace
        if e.get("type") == "tool_result"
        and "not available in the understand stage" in str(e.get("result", {}))
    ]
    assert rejections, "expected a stage rejection in the trace"


def test_clean_loop_rejects_teleport_calls_without_dispatching():
    """Button-only nav: a hallucinated reset_view/orbit bounces at the loop
    boundary even in Clean — the agent cannot fling away from the operator's view."""
    executor = MockBackendExecutor()
    channel = MockFrontendChannel()
    provider = MockProvider(script=[
        tool_turn(("reset_view", {})),
        tool_turn(("answer", {"text": "done"})),
    ])
    loop = AgentLoop(provider, ToolDispatcher(executor, channel), channel,
                     config=AgentConfig(enforce_grounding=False), stage="clean")
    result = asyncio.run(loop.run("look around"))

    assert result.status == "answered"
    # reset_view never reached the frontend as a camera_move command
    assert all(c.get("type") != "camera_move" for c in channel.commands)
    rejections = [
        e for e in result.trace
        if e.get("type") == "tool_result" and "not available in the clean stage" in str(e.get("result", {}))
    ]
    assert rejections, "expected a teleport rejection in the trace"


def test_skills_split_by_stage_but_stay_out_of_the_prompts():
    clean_names = {s["name"] for s in skills_for("clean")}
    understand_names = {s["name"] for s in skills_for("understand")}
    assert "clean_floaters" in clean_names and "clean_floaters" not in understand_names
    assert "count_objects" in understand_names and "count_objects" not in clean_names
    # The registry no longer renders into the prompts: listed routines read as
    # MORE tools (models called `survey_scene` as one). It survives only for
    # the loop's recipe feedback when a model still calls a routine name.
    for stage_name, names in (("clean", clean_names), ("understand", understand_names)):
        prompt = system_prompt_for(stage_name)  # type: ignore[arg-type]
        for name in names:
            assert name not in prompt


def test_every_skill_recipe_names_only_stage_legal_tools():
    """A skill must not teach tools its stage cannot use."""
    all_tools = {t.name for t in TOOL_REGISTRY}
    for skill in SKILLS:
        stages = ["clean", "understand"] if skill["stage"] == "both" else [skill["stage"]]
        text = skill["recipe"] + " " + skill["description"]
        mentioned = {t for t in all_tools if t in text}
        for stage_name in stages:
            illegal = mentioned - stage_tools(stage_name)  # type: ignore[arg-type]
            assert not illegal, f"{skill['name']} teaches {illegal} in {stage_name}"
