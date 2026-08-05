"""CleanupController phases 1-3: crop proposal, gridded survey + marks,
lock-in. Scaffolding mirrors test_proposals.py: scripted provider + channel,
recording executor. No model freedom anywhere: we assert the exact command
stream."""
from __future__ import annotations

import asyncio

import numpy as np

from backend.agent.cleanup_controller import CleanupConfig, CleanupController
from backend.agent.dispatch import ToolDispatcher
from backend.agent.tests.test_proposals import ProposalChannel, RecordingExecutor
from backend.contracts import ModelResponse, ToolCall


def _run(coro):
    return asyncio.run(coro)


def _scene_arrays():
    rng = np.random.default_rng(0)
    building = rng.uniform(-0.5, 0.5, size=(2000, 3))
    blob = np.array([10.0, 0.0, 0.0]) + rng.normal(0, 0.05, size=(80, 3))
    means = np.vstack([building, blob])
    return {
        "means": means,
        "opacity": np.full(len(means), 0.8),
        "ids": np.arange(len(means), dtype=np.int64),
    }


class ChoiceProvider:
    """Scripted forced-choice responses, in call order."""

    def __init__(self, script):
        self.script = list(script)
        self.calls: list[dict] = []

    def generate(self, messages, tools, images=None):
        self.calls.append({"messages": messages, "tools": [t.name for t in tools]})
        if not self.script:
            return ModelResponse(text=None, tool_calls=[])
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class TourChannel(ProposalChannel):
    """ProposalChannel + a survey_capture reply carrying frames AND poses.

    Mirrors ws.py's decode behaviour: the reply exposes raw `frames` bytes
    (the dispatcher's _extract_frames reads those, never base64 strings).
    """

    def __init__(self, n_frames=3, **kw):
        super().__init__(**kw)
        self.n_frames = n_frames
        self.interrupt_after: int | None = None
        self._sends = 0

    @property
    def interrupted(self) -> bool:
        return self.interrupt_after is not None and self._sends > self.interrupt_after

    async def send_command(self, cmd):
        self._sends += 1
        if cmd.get("type") == "capture_request" and cmd.get("tool") == "survey_capture":
            self.commands.append(cmd)
            return {
                "frames": [self.frame] * self.n_frames,
                "labels": ["operator's view"]
                + [f"pose{i}" for i in range(1, self.n_frames)],
                "poses": [
                    {"position": [10, 0, 8], "target": [10, 0, 0], "fov": 60.0, "aspect": 1.0}
                ] * self.n_frames,
                "revision": 1,
            }
        return await super().send_command(cmd)


def _mark(cells):
    return ModelResponse(text=None, tool_calls=[ToolCall("mark_noise", {"cells": cells})])


def _controller(provider, channel, executor, arrays=None, **cfg):
    dispatcher = ToolDispatcher(executor, channel)
    config = CleanupConfig(call_timeout_s=5.0, **cfg)
    return CleanupController(
        provider, dispatcher, channel, executor, arrays or _scene_arrays, config
    )


def test_phase1_crop_proposed_and_executed_on_approval():
    channel = TourChannel(verdicts=[{"verdict": "approved"}])
    executor = RecordingExecutor()
    provider = ChoiceProvider([_mark([]), _mark([]), _mark([])])
    c = _controller(provider, channel, executor)
    result = _run(c.run("cleanup_scene"))
    assert "crop_bbox" in executor.edit_calls
    # crop bounds are the app's core box, not anything model-authored
    assert executor.last_crop is not None
    crop_proposals = [
        cmd for cmd in channel.commands
        if cmd.get("type") == "proposal" and cmd["args"]["kind"] == "crop_outside_box"
    ]
    assert len(crop_proposals) == 1
    assert result.status == "answered"


def test_phase1_operator_box_overrides_app_box():
    box = {"min": [-2.0, -2.0, -2.0], "max": [2.0, 2.0, 2.0]}
    channel = TourChannel(verdicts=[{"verdict": "approved", "box": box}])
    executor = RecordingExecutor()
    provider = ChoiceProvider([_mark([]), _mark([]), _mark([])])
    c = _controller(provider, channel, executor)
    _run(c.run("cleanup_scene"))
    assert executor.last_crop == {"min": box["min"], "max": box["max"]}


def test_phase1_crop_rejected_skips_crop_but_run_continues():
    channel = TourChannel(verdicts=[{"verdict": "rejected"}])
    executor = RecordingExecutor()
    provider = ChoiceProvider([_mark([]), _mark([]), _mark([])])
    c = _controller(provider, channel, executor)
    _run(c.run("cleanup_scene"))
    assert "crop_bbox" not in executor.edit_calls
    # survey still ran
    assert any(cmd.get("tool") == "survey_capture" for cmd in channel.commands)


def test_phase2_one_mark_call_per_frame_with_gridded_survey():
    channel = TourChannel(n_frames=3, verdicts=[{"verdict": "approved"}])
    executor = RecordingExecutor()
    provider = ChoiceProvider([_mark(["B3"]), _mark([]), _mark([])])
    c = _controller(provider, channel, executor)
    _run(c.run("cleanup_scene"))
    mark_calls = [k for k in provider.calls if k["tools"] == ["mark_noise"]]
    assert len(mark_calls) == 3
    survey_cmd = next(cmd for cmd in channel.commands if cmd.get("tool") == "survey_capture")
    assert survey_cmd["args"].get("grid") is True


def test_phase2_respects_max_survey_frames():
    channel = TourChannel(n_frames=9, verdicts=[{"verdict": "approved"}])
    executor = RecordingExecutor()
    provider = ChoiceProvider([_mark([])] * 9)
    c = _controller(provider, channel, executor)
    _run(c.run("cleanup_scene"))
    mark_calls = [k for k in provider.calls if k["tools"] == ["mark_noise"]]
    assert len(mark_calls) == 6  # capped


def test_phase3_stats_cluster_survives_model_silence():
    # all mark calls fail -> candidates come from statistics alone (spec §8)
    channel = TourChannel(verdicts=[{"verdict": "approved"}])
    executor = RecordingExecutor()
    provider = ChoiceProvider([RuntimeError("down")] * 8)
    c = _controller(provider, channel, executor)
    result = _run(c.run("cleanup_scene"))
    assert len(c.candidates) == 1          # the far blob
    assert c.candidates[0].provenance == "stats"
    assert result.status == "answered"     # the run still completes


def test_interrupt_aborts_run_with_interrupted_status():
    channel = TourChannel(verdicts=[{"verdict": "approved"}])
    channel.interrupt_after = 1
    executor = RecordingExecutor()
    provider = ChoiceProvider([_mark([])] * 3)
    c = _controller(provider, channel, executor)
    result = _run(c.run("cleanup_scene"))
    assert result.status == "interrupted"
    events = [e.get("type") for e in channel.events]
    assert "complete" in events


# ---------------------------------------------------------------------------
# Task 7: judgment tour, batch proposal, execution, summary
# ---------------------------------------------------------------------------
def _judge(verdict, reason="because"):
    return ModelResponse(text=None, tool_calls=[
        ToolCall("judge_candidate", {"verdict": verdict, "reason": reason})])


def _two_blob_arrays():
    rng = np.random.default_rng(0)
    building = rng.uniform(-0.5, 0.5, size=(2000, 3))
    blob_a = np.array([10.0, 0.0, 0.0]) + rng.normal(0, 0.05, size=(80, 3))
    blob_b = np.array([0.0, 12.0, 0.0]) + rng.normal(0, 0.05, size=(50, 3))
    means = np.vstack([building, blob_a, blob_b])
    arrays = {
        "means": means,
        "opacity": np.full(len(means), 0.8),
        "ids": np.arange(len(means), dtype=np.int64),
    }
    return lambda: arrays


class DeletingExecutor(RecordingExecutor):
    """Records delete_selection id payloads for binding assertions."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.deleted_batches: list[list[int]] = []

    def delete_selection(self, ids):
        self.deleted_batches.append(list(ids))
        return super().delete_selection(ids)


def _tour_controller(provider, channel, executor, arrays=None):
    return _controller(provider, channel, executor, arrays=arrays or _two_blob_arrays())


def test_tour_judges_each_candidate_and_deletes_only_junk():
    channel = TourChannel(verdicts=[{"verdict": "approved"},   # crop
                                    {"verdict": "approved"}])  # batch
    executor = DeletingExecutor()
    provider = ChoiceProvider(
        [_mark([]), _mark([]), _mark([])] +        # 3 survey frames
        [_judge("junk"), _judge("structure")]      # 2 candidates, size order
    )
    c = _tour_controller(provider, channel, executor)
    result = _run(c.run("cleanup_scene"))
    assert result.status == "answered"
    assert c.verdicts == {"A": "junk", "B": "structure"}
    # only cluster A (the bigger blob, 80 splats) was deleted
    assert len(executor.deleted_batches) == 1
    assert len(executor.deleted_batches[0]) == 80
    # tour flew to each candidate and tinted it
    framed = [cmd for cmd in channel.commands if cmd.get("tool") == "frame_object"]
    tinted = [cmd for cmd in channel.commands if cmd.get("tool") == "select_by_ids"]
    assert len(framed) >= 2 and len(tinted) >= 2


def test_look_closer_gets_one_extra_view_then_must_commit():
    channel = TourChannel(verdicts=[{"verdict": "approved"}, {"verdict": "approved"}])
    executor = DeletingExecutor()
    provider = ChoiceProvider(
        [_mark([]), _mark([]), _mark([])] +
        [_judge("look_closer"), _judge("junk"),          # candidate A: 2 calls
         _judge("look_closer"), _judge("look_closer")]   # candidate B: coerced
    )
    c = _tour_controller(provider, channel, executor)
    _run(c.run("cleanup_scene"))
    assert c.verdicts["A"] == "junk"
    assert c.verdicts["B"] == "structure"     # second look_closer coerces to keep
    # look_closer flew an extra view per use
    orbits = [cmd for cmd in channel.commands if cmd.get("tool") == "orbit"]
    assert len(orbits) == 2


def test_model_failure_during_tour_is_unsure_kept():
    channel = TourChannel(verdicts=[{"verdict": "approved"}, {"verdict": "approved"}])
    executor = DeletingExecutor()
    provider = ChoiceProvider([_mark([]), _mark([]), _mark([]),
                               RuntimeError("x"), RuntimeError("x"),   # A: retry then None
                               _judge("junk")])                        # B
    c = _tour_controller(provider, channel, executor)
    _run(c.run("cleanup_scene"))
    assert c.verdicts["A"] == "unsure"
    # unsure is NOT deleted
    assert all(len(b) != 80 for b in executor.deleted_batches)
    assert len(executor.deleted_batches) == 1


def test_batch_card_carries_cluster_rows_and_binds_ids():
    channel = TourChannel(verdicts=[{"verdict": "approved"}, {"verdict": "approved"}])
    executor = DeletingExecutor()
    provider = ChoiceProvider([_mark([]), _mark([]), _mark([]),
                               _judge("junk"), _judge("junk")])
    c = _tour_controller(provider, channel, executor)
    _run(c.run("cleanup_scene"))
    batch = next(cmd for cmd in channel.commands
                 if cmd.get("type") == "proposal" and cmd["args"]["kind"] == "delete_clusters")
    rows = batch["args"]["clusters"]
    assert [r["label"] for r in rows] == ["A", "B"]
    assert all({"label", "count", "verdict"} <= set(r) for r in rows)
    assert len(executor.deleted_batches) == 2   # per-cluster sequential deletes


def test_batch_rejected_deletes_nothing_and_still_summarizes():
    channel = TourChannel(verdicts=[{"verdict": "approved"},   # crop
                                    {"verdict": "rejected"}])  # batch
    executor = DeletingExecutor()
    provider = ChoiceProvider([_mark([]), _mark([]), _mark([]),
                               _judge("junk"), _judge("junk")])
    c = _tour_controller(provider, channel, executor)
    result = _run(c.run("cleanup_scene"))
    assert executor.deleted_batches == []
    assert result.status == "answered"
    assert "kept" in (result.answer or "").lower()


def test_adjust_flips_verdict_then_reproposes():
    channel = TourChannel(verdicts=[
        {"verdict": "approved"},                                   # crop
        {"verdict": "adjusted", "feedback": "keep A, it is a shed"},
        {"verdict": "approved"},                                   # re-proposed batch
    ])
    executor = DeletingExecutor()
    flip = ModelResponse(text=None, tool_calls=[ToolCall(
        "apply_feedback", {"flips": [{"label": "A", "to": "keep"}]})])
    provider = ChoiceProvider([_mark([]), _mark([]), _mark([]),
                               _judge("junk"), _judge("junk"),
                               flip])
    c = _tour_controller(provider, channel, executor)
    _run(c.run("cleanup_scene"))
    assert c.verdicts["A"] == "structure"
    assert len(executor.deleted_batches) == 1        # only B deleted
    assert len(executor.deleted_batches[0]) == 50


def test_no_candidates_short_circuits_to_clean_answer():
    rng = np.random.default_rng(0)
    arrays = {
        "means": rng.uniform(-0.5, 0.5, size=(2000, 3)),
        "opacity": np.full(2000, 0.8),
        "ids": np.arange(2000, dtype=np.int64),
    }
    channel = TourChannel(verdicts=[{"verdict": "approved"}])
    executor = DeletingExecutor()
    provider = ChoiceProvider([_mark([]), _mark([]), _mark([])])
    c = _tour_controller(provider, channel, executor, arrays=lambda: arrays)
    result = _run(c.run("cleanup_scene"))
    assert result.status == "answered"
    assert executor.deleted_batches == []
    batch_cards = [cmd for cmd in channel.commands
                   if cmd.get("type") == "proposal" and cmd["args"].get("kind") == "delete_clusters"]
    assert batch_cards == []


# ---------------------------------------------------------------------------
# Codex adversarial review: partial-edit reporting on every completion path
# ---------------------------------------------------------------------------
def _complete(channel):
    return next(e for e in channel.events if e.get("type") == "complete")


def test_interrupt_after_crop_still_reports_scene_changed():
    """An edit that landed before an interrupt must still make the viewer
    resync — otherwise the operator sees pre-crop splats over a cropped
    backend with a desynced ID map (mirrors AgentLoop._finish_status)."""
    channel = TourChannel(verdicts=[{"verdict": "approved"}])
    channel.interrupt_after = 2          # crop applied, then interrupt
    executor = RecordingExecutor()
    provider = ChoiceProvider([_mark([])] * 3)
    c = _controller(provider, channel, executor)
    result = _run(c.run("cleanup_scene"))
    assert result.status == "interrupted"
    assert "crop_bbox" in executor.edit_calls          # the edit did land
    assert _complete(channel)["scene_changed"] is True


def test_run_without_any_edit_reports_scene_changed_false():
    """Nothing was destroyed — a reload would be pure churn."""
    channel = TourChannel(verdicts=[{"verdict": "rejected"}])   # crop rejected
    executor = RecordingExecutor()
    provider = ChoiceProvider([_mark([])] * 3 + [_judge("structure")])
    c = _controller(provider, channel, executor)
    result = _run(c.run("cleanup_scene"))
    assert result.status == "answered"
    assert executor.edit_calls == []
    assert _complete(channel)["scene_changed"] is False


def test_error_path_reports_scene_changed_after_an_edit():
    channel = TourChannel(verdicts=[{"verdict": "approved"}])
    executor = RecordingExecutor()
    provider = ChoiceProvider([_mark([])] * 3)
    c = _controller(provider, channel, executor)
    # blow up after phase 1 has already cropped
    async def boom() -> None:
        raise RuntimeError("controller bug")
    c._phase2_survey_and_mark = boom          # type: ignore[assignment]
    result = _run(c.run("cleanup_scene"))
    assert result.status == "error"
    assert "crop_bbox" in executor.edit_calls
    assert _complete(channel)["scene_changed"] is True


# ---------------------------------------------------------------------------
# Codex adversarial review: a verdict requires a real, tinted, framed view
# ---------------------------------------------------------------------------
class FlakyChannel(TourChannel):
    """Fails a chosen frontend tool the way a renderer timeout does (dispatch
    turns the exception into {ok: False, error}, it never raises)."""

    def __init__(self, fail_tool: str, *, empty_capture: bool = False, **kw):
        super().__init__(**kw)
        self.fail_tool = fail_tool
        self.empty_capture = empty_capture

    async def send_command(self, cmd):
        tool = cmd.get("tool")
        if tool == self.fail_tool and tool != "survey_capture":
            self.commands.append(cmd)
            self._sends += 1
            raise TimeoutError("renderer busy")
        if tool == "capture_frame" and self.empty_capture:
            self.commands.append(cmd)
            self._sends += 1
            return {"ok": True}          # replied, but no frame came back
        return await super().send_command(cmd)


def test_capture_without_a_frame_forces_unsure_and_never_asks_the_model():
    channel = FlakyChannel("", empty_capture=True, verdicts=[{"verdict": "approved"}])
    executor = DeletingExecutor()
    provider = ChoiceProvider([_mark([]), _mark([]), _mark([]),
                               _judge("junk"), _judge("junk")])
    c = _tour_controller(provider, channel, executor)
    _run(c.run("cleanup_scene"))
    assert set(c.verdicts.values()) == {"unsure"}
    assert executor.deleted_batches == []
    # the model was never asked to judge a cluster it could not see
    judge_calls = [k for k in provider.calls if k["tools"] == ["judge_candidate"]]
    assert judge_calls == []


def test_failed_tint_forces_unsure():
    channel = FlakyChannel("select_by_ids", verdicts=[{"verdict": "approved"}])
    executor = DeletingExecutor()
    provider = ChoiceProvider([_mark([]), _mark([]), _mark([]),
                               _judge("junk"), _judge("junk")])
    c = _tour_controller(provider, channel, executor)
    _run(c.run("cleanup_scene"))
    assert set(c.verdicts.values()) == {"unsure"}
    assert executor.deleted_batches == []


def test_failed_framing_forces_unsure():
    channel = FlakyChannel("frame_object", verdicts=[{"verdict": "approved"}])
    executor = DeletingExecutor()
    provider = ChoiceProvider([_mark([]), _mark([]), _mark([]),
                               _judge("junk"), _judge("junk")])
    c = _tour_controller(provider, channel, executor)
    _run(c.run("cleanup_scene"))
    assert set(c.verdicts.values()) == {"unsure"}
    assert executor.deleted_batches == []
