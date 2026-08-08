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
        # The good-cube preview tools echo {ok, min, max} — the loop absorbs the
        # box so a crop_outside_box approval can bind it (Fix 2).
        if ctype == "selection_tool" and cmd.get("tool") in ("show_box_preview", "adjust_box_preview"):
            args = cmd.get("args", {})
            return {"ok": True, "min": args.get("min"), "max": args.get("max")}
        if ctype == "capture_request":
            # v0.6: Understand runs app-dispatch survey_capture before the
            # model's first turn — answer it with a frame like the base mock.
            return {"ok": True, "frame": self.frame}
        return {"ok": True}


class RecordingExecutor(MockBackendExecutor):
    """Records every destructive edit that actually reaches the engine, and adds
    the selection-edit methods the base mock lacks."""

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.edit_calls: list[str] = []
        self.last_crop: dict | None = None
        self.kept_ids: list[int] | None = None

    def crop_bbox(self, min, max):  # noqa: A002
        self.edit_calls.append("crop_bbox")
        self.last_crop = {"min": list(min), "max": list(max)}
        return super().crop_bbox(min, max)

    def crop_sphere(self, center, radius, invert: bool = False):
        self.edit_calls.append("crop_sphere")
        return super().crop_sphere(center, radius, invert)

    def delete_selection(self, ids):
        self.edit_calls.append("delete_selection")
        before = self.state["count"]
        self.state["count"] = max(0, before - len(ids))
        return {"before": before, "after": self.state["count"], "removed": len(ids)}

    def keep_only_ids(self, ids):
        # v0.8 — the subject card's approved edit
        self.edit_calls.append("keep_only_ids")
        self.kept_ids = list(ids)
        before = self.state["count"]
        self.state["count"] = len(ids)
        return {"before": before, "after": len(ids), "removed": before - len(ids)}

    def keep_selection(self, ids):
        self.edit_calls.append("keep_selection")
        before = self.state["count"]
        self.state["count"] = len(ids)
        return {"before": before, "after": len(ids), "removed": before - len(ids)}


def _loop(provider, channel, executor, *, stage="clean", verify=False):
    dispatcher = ToolDispatcher(executor, channel)
    # verify_after_edit off (default) so the gated tools flow through generic
    # dispatch and the test isolates the gate itself (not the verify/undo
    # behaviour). One test flips it on to cover the production destructive path.
    config = AgentConfig(enforce_grounding=False, verify_after_edit=verify)
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
# v0.8.2 — the crop-box flow is retired from the agent surface
# (RETIRED_BOX_TOOLS): its gate/binding tests went with it. The generic
# approval machinery stays covered via delete/keep/bulk kinds below.

def test_adjusted_verdict_banks_no_approval_and_feeds_back_feedback():
    executor = RecordingExecutor()
    channel = ProposalChannel(
        verdicts=[{"verdict": "adjusted", "feedback": "brush the left cluster too"}]
    )
    provider = MockProvider(script=[
        tool_turn(("propose_decision", {"kind": "delete_selection"})),
        tool_turn(("delete_selection", {})),
        tool_turn(("answer", {"text": "done"})),
    ])
    result = asyncio.run(_loop(provider, channel, executor).run("clean"))

    assert result.status == "answered"
    assert executor.edit_calls == []  # adjusted != approved: still locked
    assert _rejections(result, "delete_selection")
    # the operator's feedback made it back into the fed-back tool result
    proposal_results = _tool_results(result, "propose_decision")
    assert any("brush the left cluster" in str(e.get("result")) for e in proposal_results)


def test_rejected_verdict_banks_no_approval():
    executor = RecordingExecutor()
    channel = ProposalChannel(verdicts=[{"verdict": "rejected"}])
    provider = MockProvider(script=[
        tool_turn(("propose_decision", {"kind": "delete_selection"})),
        tool_turn(("delete_selection", {})),
        tool_turn(("answer", {"text": "done"})),
    ])
    result = asyncio.run(_loop(provider, channel, executor).run("clean"))
    assert result.status == "answered"
    assert executor.edit_calls == []
    assert _rejections(result, "delete_selection")


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


def test_keep_selection_requires_its_own_kind():
    """keep_selection deletes everything EXCEPT the selection — materially
    different consent than delete_selection, so a delete approval must NOT
    unlock it (Codex adversarial review)."""
    executor = RecordingExecutor()
    channel = ProposalChannel(verdicts=[{"verdict": "approved"}])
    provider = MockProvider(script=[
        tool_turn(("propose_decision", {"kind": "delete_selection"})),
        tool_turn(("keep_selection", {})),  # wrong consent — must stay locked
        tool_turn(("answer", {"text": "done"})),
    ])
    result = asyncio.run(_loop(provider, channel, executor).run("clean"))
    assert result.status == "answered"
    assert executor.edit_calls == []
    rej = _rejections(result, "keep_selection")
    assert rej and "keep_only_selection" in str(rej[0]["result"]["error"])


def test_keep_only_selection_kind_unlocks_keep_selection():
    executor = RecordingExecutor()
    channel = ProposalChannel(verdicts=[{"verdict": "approved"}])
    provider = MockProvider(script=[
        tool_turn(("propose_decision", {"kind": "keep_only_selection"})),
        tool_turn(("keep_selection", {})),
        tool_turn(("answer", {"text": "done"})),
    ])
    result = asyncio.run(_loop(provider, channel, executor).run("clean"))
    assert result.status == "answered"
    assert executor.edit_calls == ["keep_selection"]
    assert _rejections(result, "keep_selection") == []


def test_keep_only_kind_does_not_unlock_delete_selection():
    executor = RecordingExecutor()
    channel = ProposalChannel(verdicts=[{"verdict": "approved"}])
    provider = MockProvider(script=[
        tool_turn(("propose_decision", {"kind": "keep_only_selection"})),
        tool_turn(("delete_selection", {})),  # inverse substitution — locked
        tool_turn(("answer", {"text": "done"})),
    ])
    result = asyncio.run(_loop(provider, channel, executor).run("clean"))
    assert result.status == "answered"
    assert executor.edit_calls == []
    assert _rejections(result, "delete_selection")


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


# ── Fix 4: the production destructive path (gate → _handle_destructive) ───
# ── bulk_edit: statistical sweeps are gated too (operator decision 2026-07-22) ─
class SweepRecordingExecutor(RecordingExecutor):
    def remove_outliers(self, k, std_ratio):
        self.edit_calls.append("remove_outliers")
        return super().remove_outliers(k, std_ratio)


def test_statistical_sweep_without_approval_is_rejected():
    executor = SweepRecordingExecutor()
    channel = ProposalChannel()
    provider = MockProvider(script=[
        tool_turn(("remove_outliers", {"k": 8, "std_ratio": 2.0})),
        tool_turn(("answer", {"text": "done"})),
    ])
    result = asyncio.run(_loop(provider, channel, executor).run("clean"))

    assert result.status == "answered"
    assert executor.edit_calls == []  # sweep never reached the engine
    assert _rejections(result, "remove_outliers"), "expected the approval-gate rejection"


def test_approved_bulk_edit_unlocks_exactly_one_sweep():
    executor = SweepRecordingExecutor()
    channel = ProposalChannel(verdicts=[{"verdict": "approved"}])
    provider = MockProvider(script=[
        tool_turn(("propose_decision", {
            "kind": "bulk_edit",
            "operation": {"tool": "remove_outliers", "params": {"k": 8, "std_ratio": 2.0}},
        })),
        tool_turn(("remove_outliers", {"k": 8, "std_ratio": 2.0})),
        tool_turn(("remove_outliers", {"k": 8, "std_ratio": 2.0})),  # second: rejected
        tool_turn(("answer", {"text": "done"})),
    ])
    result = asyncio.run(_loop(provider, channel, executor).run("clean"))

    assert result.status == "answered"
    assert executor.edit_calls == ["remove_outliers"]  # exactly one consumed
    assert _rejections(result, "remove_outliers"), "second sweep must be re-gated"


def test_bulk_edit_approval_without_operation_is_not_banked():
    """A bulk approval must name the exact sweep — a bare kind banks nothing."""
    executor = SweepRecordingExecutor()
    channel = ProposalChannel(verdicts=[{"verdict": "approved"}])
    provider = MockProvider(script=[
        tool_turn(("propose_decision", {"kind": "bulk_edit"})),  # no operation!
        tool_turn(("remove_outliers", {"k": 8, "std_ratio": 2.0})),
        tool_turn(("answer", {"text": "done"})),
    ])
    result = asyncio.run(_loop(provider, channel, executor).run("clean"))
    assert result.status == "answered"
    assert executor.edit_calls == []
    assert _rejections(result, "remove_outliers")


def test_bulk_edit_approval_binds_the_named_sweep_and_params():
    """The approval authorizes ONE named sweep; another sweep is rejected and
    the executed call runs with the REVIEWED params, not the model's."""
    executor = SweepRecordingExecutor()
    channel = ProposalChannel(verdicts=[{"verdict": "approved"}])
    provider = MockProvider(script=[
        tool_turn(("propose_decision", {
            "kind": "bulk_edit",
            "operation": {"tool": "remove_outliers", "params": {"k": 8, "std_ratio": 2.0}},
        })),
        tool_turn(("opacity_threshold", {"min_alpha": 0.05})),  # NOT the approved sweep
        tool_turn(("remove_outliers", {"k": 99, "std_ratio": 9.0})),  # wrong params
        tool_turn(("answer", {"text": "done"})),
    ])
    result = asyncio.run(_loop(provider, channel, executor).run("clean"))

    assert result.status == "answered"
    assert executor.edit_calls == ["remove_outliers"]  # opacity_threshold never ran
    # the engine received the approved params (k=8), not the model's k=99
    assert executor.state["outlier"] < 0.12  # sweep genuinely ran
    mismatch_rej = [
        e for e in _tool_results(result, "opacity_threshold")
        if e.get("result", {}).get("ok") is False
        and "remove_outliers" in str(e.get("result", {}).get("error", ""))
    ]
    assert mismatch_rej, "expected a rejection naming the approved sweep"
    # override surfaced honestly
    narrations = [e for e in result.trace if e.get("type") == "narrate"]
    assert any("parameters the operator approved" in str(e) for e in narrations)


# ── delete_selection approvals bind the reviewed IDs ─────────────────────
class GrowingSelectionChannel(ProposalChannel):
    """The selection grows right after the approval banks its ID snapshot (the
    first get_selection pull) — simulating strokes landing between the
    operator's approval and the delete."""

    _grown = False

    async def send_command(self, cmd: dict) -> dict:
        res = await super().send_command(cmd)
        if cmd.get("type") == "get_selection" and not self._grown:
            self._grown = True
            self.selected_ids = [1, 2, 3, 99]  # operator-unseen extra splat
        return res


def test_selection_change_after_approval_voids_it():
    """Brushing MORE splats between approval and delete must void the approval:
    the operator reviewed a different selection than would be deleted."""
    executor = RecordingExecutor()
    channel = GrowingSelectionChannel(verdicts=[{"verdict": "approved"}], selected_ids=[1, 2, 3])
    provider = MockProvider(script=[
        tool_turn(("propose_decision", {"kind": "delete_selection"})),
        tool_turn(("delete_selection", {})),
        tool_turn(("answer", {"text": "done"})),
    ])
    result = asyncio.run(_loop(provider, channel, executor).run("clean"))

    assert result.status == "answered"
    assert executor.edit_calls == []  # the changed selection was never deleted
    void_rej = [
        e for e in _tool_results(result, "delete_selection")
        if e.get("result", {}).get("ok") is False
        and "changed since" in str(e.get("result", {}).get("error", ""))
    ]
    assert void_rej, "expected the selection-changed voiding rejection"


def test_delete_approval_with_empty_selection_is_not_banked():
    executor = RecordingExecutor()
    channel = ProposalChannel(verdicts=[{"verdict": "approved"}], selected_ids=[])
    provider = MockProvider(script=[
        tool_turn(("propose_decision", {"kind": "delete_selection"})),
        tool_turn(("delete_selection", {})),
        tool_turn(("answer", {"text": "done"})),
    ])
    result = asyncio.run(_loop(provider, channel, executor).run("clean"))
    assert result.status == "answered"
    assert executor.edit_calls == []
    assert _rejections(result, "delete_selection")
