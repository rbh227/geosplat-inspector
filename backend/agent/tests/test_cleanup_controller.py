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
