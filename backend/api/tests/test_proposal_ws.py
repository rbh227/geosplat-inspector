"""v0.5 proposal WS plumbing: the `proposal` command awaits its reply with NO
timeout (the operator may deliberate indefinitely), every other command keeps
the 30s DEFAULT_COMMAND_TIMEOUT, and the four new v0.5 tools dispatch to the
right WS command types.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.agent.dispatch import ToolDispatcher
from backend.agent.mocks import MockBackendExecutor, MockFrontendChannel
from backend.api.ws import DEFAULT_COMMAND_TIMEOUT, WSChannel
from backend.contracts import ToolCall


@pytest.fixture
def anyio_backend():
    return "asyncio"


class RecordingManager:
    """Records the (ctype, timeout, client) of every send_command; acks trivially."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def send_command(
        self, scene_id, ctype, payload=None, timeout=DEFAULT_COMMAND_TIMEOUT, client_id=None,
    ):
        self.calls.append({
            "ctype": ctype, "timeout": timeout, "payload": payload, "client_id": client_id,
        })
        return {"ok": True}


@pytest.mark.anyio
async def test_proposal_command_awaits_with_no_timeout():
    mgr = RecordingManager()
    channel = WSChannel("s1", mgr)  # type: ignore[arg-type]
    await channel.send_command({"type": "proposal", "payload": {"summary": "crop?"}})
    assert mgr.calls[-1]["ctype"] == "proposal"
    assert mgr.calls[-1]["timeout"] is None  # operator deliberates indefinitely


@pytest.mark.anyio
async def test_non_proposal_command_keeps_default_timeout():
    mgr = RecordingManager()
    channel = WSChannel("s2", mgr)  # type: ignore[arg-type]
    await channel.send_command({"type": "selection_tool", "payload": {}})
    assert mgr.calls[-1]["ctype"] == "selection_tool"
    assert mgr.calls[-1]["timeout"] == DEFAULT_COMMAND_TIMEOUT


@pytest.mark.anyio
@pytest.mark.parametrize(
    "tool_name,expected_type",
    [
        ("get_core_bounds", "selection_tool"),
        ("show_box_preview", "selection_tool"),
        ("adjust_box_preview", "selection_tool"),
        ("propose_decision", "proposal"),
    ],
)
async def test_v05_tools_route_to_expected_command_type(tool_name, expected_type):
    channel = MockFrontendChannel()
    dispatcher = ToolDispatcher(MockBackendExecutor(), channel)
    res = await dispatcher.dispatch(ToolCall(name=tool_name, args={}))
    assert res["ok"], res
    assert channel.commands[-1]["type"] == expected_type
    assert channel.commands[-1]["tool"] == tool_name
