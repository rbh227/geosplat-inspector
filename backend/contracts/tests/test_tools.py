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


def test_no_duplicate_names():
    names = [t.name for t in TOOL_REGISTRY]
    assert len(names) == len(set(names))


def test_v02_counts():
    assert len(FRONTEND_TOOLS) == 22
    assert len(BACKEND_TOOLS) == 18
    assert len(TOOL_REGISTRY) == 40


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
