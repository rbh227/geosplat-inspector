"""U8 parity canary: agent-issued select → state → delete → undo drives the
same edit path a human uses (KTD2). If this fails, the tool layer is not
agent-ready — fix before any Phase B work.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from backend.agent.dispatch import ToolDispatcher
from backend.api.real_engine import RealBackendExecutor, RealScene
from backend.contracts import ToolCall
from backend.splat.model import GaussianSplatModel

EXAMPLES = Path(__file__).resolve().parents[3] / "examples"


class SelectionChannel:
    """Fake FrontendChannel simulating the viewer's selection layer: holds a
    current selection, answers get_selection pulls, records every command."""

    def __init__(self, selected_ids: list[int] | None = None):
        self.selected_ids = selected_ids or []
        self.commands: list[dict] = []
        self.events: list[dict] = []

    async def send_command(self, cmd: dict) -> dict:
        self.commands.append(cmd)
        ctype = cmd.get("type")
        if ctype == "get_selection":
            return {"ok": True, "ids": list(self.selected_ids)}
        if ctype == "selection_tool":
            # the real frontend resolves containment; the fake selects 0..9
            self.selected_ids = list(range(10))
            return {"ok": True, "count": len(self.selected_ids)}
        if ctype == "movement_input":
            return {"ok": True}
        return {"ok": True}

    async def emit_event(self, event: dict) -> None:
        self.events.append(event)

    def command_types(self) -> list[str]:
        return [c.get("type") for c in self.commands]


@pytest.fixture
def scene() -> RealScene:
    return RealScene(GaussianSplatModel.load(str(EXAMPLES / "clean.ply")))


def _dispatch(dispatcher: ToolDispatcher, name: str, args: dict | None = None) -> dict:
    return asyncio.run(dispatcher.dispatch(ToolCall(name=name, args=args or {})))


def test_agent_select_state_delete_undo_flow(scene):
    channel = SelectionChannel()
    dispatcher = ToolDispatcher(RealBackendExecutor(scene), channel)
    before = scene.count()

    # 1. agent selects through the shared layer (frontend command)
    res = _dispatch(dispatcher, "select_by_sphere", {"center": [0, 0, 0], "radius": 1.0})
    assert res["ok"]
    assert channel.command_types() == ["selection_tool"]

    # 2. delete_selection pulls the IDs and applies through the shared engine
    res = _dispatch(dispatcher, "delete_selection")
    assert res["ok"], res
    assert channel.command_types() == ["selection_tool", "get_selection"]
    assert res["result"]["removed"] == 10
    assert scene.count() == before - 10
    assert res["snapshotted"] is True  # destructive → verify loop engages

    # 3. undo restores through the same shared history a human's undo uses
    res = _dispatch(dispatcher, "undo")
    assert res["ok"]
    assert scene.count() == before


def test_delete_selection_with_empty_selection_steers_the_model(scene):
    channel = SelectionChannel(selected_ids=[])
    dispatcher = ToolDispatcher(RealBackendExecutor(scene), channel)
    res = _dispatch(dispatcher, "delete_selection")
    assert res["ok"] is False
    assert "select_by_" in res["error"]
    assert scene.count() > 0  # nothing was deleted


def test_keep_selection_inverts(scene):
    channel = SelectionChannel(selected_ids=[0, 1, 2])
    dispatcher = ToolDispatcher(RealBackendExecutor(scene), channel)
    res = _dispatch(dispatcher, "keep_selection")
    assert res["ok"]
    assert scene.count() == 3


def test_selection_tools_route_to_frontend(scene):
    channel = SelectionChannel()
    dispatcher = ToolDispatcher(RealBackendExecutor(scene), channel)
    for name, args in [
        ("select_by_brush", {"center_xy": [0.5, 0.5], "radius": 0.1}),
        ("get_selection_state", {}),
        ("clear_selection", {}),
    ]:
        res = _dispatch(dispatcher, name, args)
        assert res["ok"], name
    assert channel.command_types() == ["selection_tool"] * 3


def test_move_camera_routes_as_movement_input(scene):
    channel = SelectionChannel()
    dispatcher = ToolDispatcher(RealBackendExecutor(scene), channel)
    res = _dispatch(dispatcher, "move_camera", {"direction": "forward", "duration_ms": 200})
    assert res["ok"]
    assert channel.command_types() == ["movement_input"]
    assert channel.commands[0]["tool"] == "move_camera"
