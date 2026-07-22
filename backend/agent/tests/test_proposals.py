"""v0.5 approval gate (docs task 3): in the CLEAN stage the destructive spatial
ops (crop_bbox / crop_sphere / delete_selection / keep_selection) are locked
until an operator-approved `propose_decision` of the matching kind is banked.
One approval unlocks exactly one edit; adjusted/rejected verdicts bank nothing.

Scaffolding mirrors test_pause_resume.py: a scripted MockProvider drives the
tool calls, a stub channel returns canned proposal verdicts, and a recording
executor reveals whether the edit actually reached the engine.
"""

from __future__ import annotations

import asyncio

from backend.agent.config import AgentConfig
from backend.agent.dispatch import ToolDispatcher
from backend.agent.loop import AgentLoop
from backend.agent.mocks import (
    MockBackendExecutor,
    MockFrontendChannel,
    MockProvider,
    tool_turn,
)


class ProposalChannel(MockFrontendChannel):
    """Stub channel: returns scripted `propose_decision` verdicts (in order,
    defaulting to 'approved' once the script runs out) and answers the
    get_selection pull for selection edits."""

    def __init__(self, verdicts: list[dict] | None = None, selected_ids: list[int] | None = None):
        super().__init__()
        self._verdicts = list(verdicts or [])
        self.selected_ids = list(selected_ids if selected_ids is not None else range(10))
        self.proposals_seen = 0

    async def send_command(self, cmd: dict) -> dict:
        self.commands.append(cmd)
        ctype = cmd.get("type")
        if ctype == "proposal":
            self.proposals_seen += 1
            if self._verdicts:
                return self._verdicts.pop(0)
            return {"verdict": "approved"}
        if ctype == "get_selection":
            return {"ok": True, "ids": list(self.selected_ids)}
        return {"ok": True}


class RecordingExecutor(MockBackendExecutor):
    """Records every destructive edit that actually reaches the engine, and adds
    the selection-edit methods the base mock lacks."""

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.edit_calls: list[str] = []

    def crop_bbox(self, min, max):  # noqa: A002
        self.edit_calls.append("crop_bbox")
        return super().crop_bbox(min, max)

    def crop_sphere(self, center, radius, invert: bool = False):
        self.edit_calls.append("crop_sphere")
        return super().crop_sphere(center, radius, invert)

    def delete_selection(self, ids):
        self.edit_calls.append("delete_selection")
        before = self.state["count"]
        self.state["count"] = max(0, before - len(ids))
        return {"before": before, "after": self.state["count"], "removed": len(ids)}

    def keep_selection(self, ids):
        self.edit_calls.append("keep_selection")
        before = self.state["count"]
        self.state["count"] = len(ids)
        return {"before": before, "after": len(ids), "removed": before - len(ids)}


def _loop(provider, channel, executor, *, stage="clean"):
    dispatcher = ToolDispatcher(executor, channel)
    # verify_after_edit off so the gated tools flow through generic dispatch and
    # the test isolates the gate itself (not the verify/undo behaviour).
    config = AgentConfig(enforce_grounding=False, verify_after_edit=False)
    return AgentLoop(provider, dispatcher, channel, config=config, stage=stage)


def _tool_results(result, name):
    return [
        e for e in result.trace
        if e.get("type") == "tool_result" and e.get("name") == name
    ]


def _rejections(result, name):
    out = []
    for e in _tool_results(result, name):
        res = e.get("result")
        if isinstance(res, dict) and res.get("ok") is False and "propose_decision" in str(res.get("error", "")):
            out.append(e)
    return out


# ── gate blocks without approval ─────────────────────────────────────────
def test_crop_bbox_without_approval_is_rejected():
    executor = RecordingExecutor()
    channel = ProposalChannel()
    provider = MockProvider(script=[
        tool_turn(("crop_bbox", {"min": [0, 0, 0], "max": [1, 1, 1]})),
        tool_turn(("answer", {"text": "done"})),
    ])
    result = asyncio.run(_loop(provider, channel, executor).run("clean"))

    assert result.status == "answered"
    assert executor.edit_calls == []  # executor never touched
    rej = _rejections(result, "crop_bbox")
    assert rej, "expected a gate rejection mentioning propose_decision"
    assert "crop_outside_box" in str(rej[0]["result"]["error"])


# ── one approval unlocks exactly one edit ────────────────────────────────
def test_approved_proposal_unlocks_one_crop_then_relocks():
    executor = RecordingExecutor()
    channel = ProposalChannel(verdicts=[{"verdict": "approved"}])
    provider = MockProvider(script=[
        tool_turn(("propose_decision", {"kind": "crop_outside_box"})),
        tool_turn(("crop_bbox", {"min": [0, 0, 0], "max": [1, 1, 1]})),
        tool_turn(("crop_bbox", {"min": [0, 0, 0], "max": [1, 1, 1]})),
        tool_turn(("answer", {"text": "done"})),
    ])
    result = asyncio.run(_loop(provider, channel, executor).run("clean"))

    assert result.status == "answered"
    # exactly ONE crop dispatched; the second was re-locked (consumed approval)
    assert executor.edit_calls == ["crop_bbox"]
    assert len(_rejections(result, "crop_bbox")) == 1


def test_crop_sphere_shares_the_crop_outside_box_kind():
    executor = RecordingExecutor()
    channel = ProposalChannel(verdicts=[{"verdict": "approved"}])
    provider = MockProvider(script=[
        tool_turn(("propose_decision", {"kind": "crop_outside_box"})),
        tool_turn(("crop_sphere", {"center": [0, 0, 0], "radius": 0.5})),
        tool_turn(("answer", {"text": "done"})),
    ])
    result = asyncio.run(_loop(provider, channel, executor).run("clean"))
    assert result.status == "answered"
    assert executor.edit_calls == ["crop_sphere"]
    assert _rejections(result, "crop_sphere") == []


# ── adjusted / rejected bank nothing ─────────────────────────────────────
def test_adjusted_verdict_banks_no_approval_and_feeds_back_feedback():
    executor = RecordingExecutor()
    channel = ProposalChannel(
        verdicts=[{"verdict": "adjusted", "feedback": "make the box tighter on the left"}]
    )
    provider = MockProvider(script=[
        tool_turn(("propose_decision", {"kind": "crop_outside_box"})),
        tool_turn(("crop_bbox", {"min": [0, 0, 0], "max": [1, 1, 1]})),
        tool_turn(("answer", {"text": "done"})),
    ])
    result = asyncio.run(_loop(provider, channel, executor).run("clean"))

    assert result.status == "answered"
    assert executor.edit_calls == []  # adjusted != approved: still locked
    assert _rejections(result, "crop_bbox")
    # the operator's feedback made it back into the fed-back tool result
    proposal_results = _tool_results(result, "propose_decision")
    assert any("make the box tighter" in str(e.get("result")) for e in proposal_results)


def test_rejected_verdict_banks_no_approval():
    executor = RecordingExecutor()
    channel = ProposalChannel(verdicts=[{"verdict": "rejected"}])
    provider = MockProvider(script=[
        tool_turn(("propose_decision", {"kind": "crop_outside_box"})),
        tool_turn(("crop_bbox", {"min": [0, 0, 0], "max": [1, 1, 1]})),
        tool_turn(("answer", {"text": "done"})),
    ])
    result = asyncio.run(_loop(provider, channel, executor).run("clean"))
    assert result.status == "answered"
    assert executor.edit_calls == []
    assert _rejections(result, "crop_bbox")


# ── delete_selection / keep_selection gated on the delete_selection kind ──
def test_delete_selection_gated_on_delete_selection_kind():
    executor = RecordingExecutor()
    channel = ProposalChannel(verdicts=[{"verdict": "approved"}])
    provider = MockProvider(script=[
        tool_turn(("propose_decision", {"kind": "delete_selection"})),
        tool_turn(("delete_selection", {})),
        tool_turn(("delete_selection", {})),
        tool_turn(("answer", {"text": "done"})),
    ])
    result = asyncio.run(_loop(provider, channel, executor).run("clean"))

    assert result.status == "answered"
    assert executor.edit_calls == ["delete_selection"]
    assert len(_rejections(result, "delete_selection")) == 1


def test_keep_selection_shares_the_delete_selection_kind():
    executor = RecordingExecutor()
    channel = ProposalChannel(verdicts=[{"verdict": "approved"}])
    provider = MockProvider(script=[
        tool_turn(("propose_decision", {"kind": "delete_selection"})),
        tool_turn(("keep_selection", {})),
        tool_turn(("answer", {"text": "done"})),
    ])
    result = asyncio.run(_loop(provider, channel, executor).run("clean"))
    assert result.status == "answered"
    assert executor.edit_calls == ["keep_selection"]
    assert _rejections(result, "keep_selection") == []


def test_delete_kind_does_not_unlock_a_crop():
    """Kinds are namespaced: a delete_selection approval must not unlock crops."""
    executor = RecordingExecutor()
    channel = ProposalChannel(verdicts=[{"verdict": "approved"}])
    provider = MockProvider(script=[
        tool_turn(("propose_decision", {"kind": "delete_selection"})),
        tool_turn(("crop_bbox", {"min": [0, 0, 0], "max": [1, 1, 1]})),
        tool_turn(("answer", {"text": "done"})),
    ])
    result = asyncio.run(_loop(provider, channel, executor).run("clean"))
    assert result.status == "answered"
    assert executor.edit_calls == []
    assert _rejections(result, "crop_bbox")


# ── understand stage: the gate never engages; the stage backstop bites first ─
def test_understand_stage_rejects_gated_tools_at_the_backstop():
    executor = RecordingExecutor()
    channel = ProposalChannel()
    provider = MockProvider(script=[
        tool_turn(("crop_bbox", {"min": [0, 0, 0], "max": [1, 1, 1]})),
        tool_turn(("answer", {"text": "done"})),
    ])
    result = asyncio.run(_loop(provider, channel, executor, stage="understand").run("look"))

    assert result.status == "answered"
    assert executor.edit_calls == []
    stage_rej = [
        e for e in _tool_results(result, "crop_bbox")
        if "not available in the understand stage" in str(e.get("result", {}))
    ]
    assert stage_rej, "expected the stage backstop, not the approval gate"
    # the approval-gate message must NOT appear (backstop returns first)
    assert _rejections(result, "crop_bbox") == []
