"""v0.2 registry integrity: counts, uniqueness, schema shape, WS type sets."""

from backend.api.ws import COMMAND_TYPES, REPLY_TYPES
from backend.contracts.tools import BACKEND_TOOLS, FRONTEND_TOOLS, TOOL_BY_NAME, TOOL_REGISTRY

V02_FRONTEND = {
    "select_by_brush", "select_by_lasso", "select_by_polygon",
    "select_by_sphere", "select_by_box",
    "invert_selection", "clear_selection", "get_selection_state",
    "move_camera",
}
V02_BACKEND = {"delete_selection", "keep_selection"}

V05_FRONTEND = {
    "get_core_bounds", "show_box_preview", "adjust_box_preview", "propose_decision",
}


def test_no_duplicate_names():
    names = [t.name for t in TOOL_REGISTRY]
    assert len(names) == len(set(names))


def test_v02_counts():
    # v0.3 added `turn`, v0.4 added `reframe` (both frontend): 22 -> 24 frontend.
    # v0.5 adds the four proposal / good-cube frontend tools: 24 -> 28 frontend,
    # 42 -> 46 total. v0.6 adds survey_capture: 28 -> 29 frontend, 46 -> 47 total.
    # v0.7 adds select_by_ids: 29 -> 30 frontend, 47 -> 48 total.
    assert len(FRONTEND_TOOLS) == 30
    assert len(BACKEND_TOOLS) == 18
    assert len(TOOL_REGISTRY) == 48


def test_v03_turn_tool_present_and_routed():
    assert "turn" in FRONTEND_TOOLS
    assert "turn" in TOOL_BY_NAME
    assert TOOL_BY_NAME["turn"].runs_on == "frontend"
    assert "rotation_input" in COMMAND_TYPES


def test_v04_reframe_tool_present_and_routed():
    assert "reframe" in FRONTEND_TOOLS
    assert "reframe" in TOOL_BY_NAME
    assert TOOL_BY_NAME["reframe"].runs_on == "frontend"


def test_v05_proposal_tools_present_and_routed():
    assert V05_FRONTEND <= FRONTEND_TOOLS
    for name in V05_FRONTEND:
        assert name in TOOL_BY_NAME
        assert TOOL_BY_NAME[name].runs_on == "frontend"


def test_v02_tools_present_and_routed():
    assert V02_FRONTEND <= FRONTEND_TOOLS
    assert V02_BACKEND <= BACKEND_TOOLS
    for name in V02_FRONTEND | V02_BACKEND:
        assert name in TOOL_BY_NAME


def test_param_schemas_are_objects():
    for entry in TOOL_REGISTRY:
        assert entry.params.get("type") == "object", entry.name
        assert isinstance(entry.params.get("properties", {}), dict), entry.name


def test_ws_type_sets_carry_v02():
    assert {"get_selection", "selection_tool", "movement_input"} <= COMMAND_TYPES
    assert {"agent_pause", "agent_resume", "selection", "tool_result"} <= REPLY_TYPES


def test_proposal_decision_fields_v06():
    """The operator's edited box rides back with an approved verdict (v0.6)."""
    from backend.contracts.tools import PROPOSAL_DECISION_FIELDS

    assert "verdict" in PROPOSAL_DECISION_FIELDS
    assert "feedback" in PROPOSAL_DECISION_FIELDS
    assert "box" in PROPOSAL_DECISION_FIELDS


def test_v06_survey_capture_present_and_routed():
    assert "survey_capture" in FRONTEND_TOOLS
    assert TOOL_BY_NAME["survey_capture"].runs_on == "frontend"


def test_v07_select_by_ids_registered():
    entry = TOOL_BY_NAME["select_by_ids"]
    assert entry.runs_on == "frontend"
    props = entry.params["properties"]
    assert props["ids"]["type"] == "array"
    assert set(entry.params["required"]) == {"ids"}


def test_v07_delete_clusters_kind():
    kinds = TOOL_BY_NAME["propose_decision"].params["properties"]["kind"]["enum"]
    assert "delete_clusters" in kinds
    props = TOOL_BY_NAME["propose_decision"].params["properties"]
    assert "clusters" in props
    row = props["clusters"]["items"]["properties"]
    assert set(row) == {"label", "count", "verdict", "reason", "provenance"}


def test_v07_controller_choice_specs():
    from backend.contracts.tools import CONTROLLER_CHOICE_SPECS

    mark = CONTROLLER_CHOICE_SPECS["mark_noise"]
    judge = CONTROLLER_CHOICE_SPECS["judge_candidate"]
    assert mark["parameters"]["properties"]["cells"]["items"]["type"] == "string"
    verdicts = judge["parameters"]["properties"]["verdict"]["enum"]
    assert verdicts == ["junk", "structure", "look_closer"]
    # choice specs are NOT dispatchable registry tools
    assert "mark_noise" not in TOOL_BY_NAME
    assert "judge_candidate" not in TOOL_BY_NAME
