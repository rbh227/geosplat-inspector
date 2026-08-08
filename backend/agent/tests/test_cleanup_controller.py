"""CleanupController phases 1-3: subject lock-on, gridded survey + marks,
lock-in. Scaffolding mirrors test_proposals.py: scripted provider + channel,
recording executor. No model freedom anywhere: we assert the exact command
stream.

v0.8: phase 1 is the subject lock-on — every run starts with up to
`subject_judge_rounds` voting rounds of forced `judge_subject` calls (3 frames
each) before the keep_only_subject card. Scripts therefore open with
`_o3() + _good3()` (three 'good' votes → one round, one script item per ask) unless
the subject phase cannot reach the model at all (failed framing / empty
captures)."""
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


def _js(verdict, reason="because"):
    return ModelResponse(text=None, tool_calls=[
        ToolCall("judge_subject", {"verdict": verdict, "reason": reason})])


def _good3():
    """One clean subject-voting round: 3 'good' votes → no level change, no
    second round — each ask consumes exactly one script item."""
    return [_js("good")] * 3


def _ol(x0=0.0, y0=0.0, x1=1.0, y1=1.0):
    return ModelResponse(text=None, tool_calls=[
        ToolCall("outline_scene", {"x0": x0, "y0": y0, "x1": x1, "y1": y1})])


def _o3():
    """v0.8.1 scene-hull: phase 1 opens with one outline_scene ask per survey
    frame (TourChannel serves 3). Full-frame boxes against TourChannel's
    off-axis pose carve nothing, so the statistical subject stands — existing
    assertions are unaffected."""
    return [_ol()] * 3


def _controller(provider, channel, executor, arrays=None, **cfg):
    dispatcher = ToolDispatcher(executor, channel)
    config = CleanupConfig(call_timeout_s=5.0, **cfg)
    return CleanupController(
        provider, dispatcher, channel, executor, arrays or _scene_arrays, config
    )


def test_subject_votes_loosen_then_card():
    """All clipping_structure votes → the controller loosens one step (default
    level 2 → 3), re-tints via a level-only show_subject_preview, then parks
    ONE keep_only_subject card."""
    channel = TourChannel(verdicts=[{"verdict": "rejected"}])
    executor = RecordingExecutor()
    provider = ChoiceProvider(_o3() + [_js("clipping_structure")] * 3)
    c = _controller(provider, channel, executor)
    result = _run(c.run("cleanup_scene"))
    previews = [cmd for cmd in channel.commands if cmd.get("tool") == "show_subject_preview"]
    assert len(previews) == 2
    assert previews[0]["args"]["level"] == 2            # default level of 5
    # complement form: ship the (small) excluded set, never the keep-set
    assert "outside_ids" in previews[0]["args"]
    assert "base_ids" not in previews[0]["args"]
    assert previews[1]["args"] == {"level": 3}          # loosened, level-only re-tint
    cards = [cmd for cmd in channel.commands
             if cmd.get("type") == "proposal" and cmd["args"]["kind"] == "keep_only_subject"]
    assert len(cards) == 1
    assert result.status == "answered"


def test_subject_model_unavailable_degrades_to_default_level():
    """Every ask fails → no level change, the card is still parked, and the
    run continues into the survey — it never stalls on the model."""
    channel = TourChannel(verdicts=[{"verdict": "rejected"}])
    executor = RecordingExecutor()
    provider = ChoiceProvider([RuntimeError("down")] * 12)
    c = _controller(provider, channel, executor)
    result = _run(c.run("cleanup_scene"))
    previews = [cmd for cmd in channel.commands if cmd.get("tool") == "show_subject_preview"]
    assert len(previews) == 1                           # never re-tinted
    assert previews[0]["args"]["level"] == 2
    cards = [cmd for cmd in channel.commands
             if cmd.get("type") == "proposal" and cmd["args"]["kind"] == "keep_only_subject"]
    assert len(cards) == 1
    assert any(cmd.get("tool") == "survey_capture" for cmd in channel.commands)
    assert result.status == "answered"


def test_subject_approve_executes_keep_only_with_reply_level():
    """The approved reply's slider level binds the edit: keep_only_ids runs
    with level_ids[4], counts as one applied edit, and resyncs the viewer."""
    from backend.analysis.subject import find_subject

    arrays = _scene_arrays()
    channel = SceneChannel(verdicts=[{"verdict": "approved", "level": 4}])
    executor = RecordingExecutor()
    provider = ChoiceProvider(_o3() + _good3())
    c = _controller(provider, channel, executor, arrays=lambda: arrays)
    result = _run(c.run("cleanup_scene"))
    expected = find_subject(
        np.asarray(arrays["means"]), np.asarray(arrays["opacity"]),
        np.asarray(arrays["ids"]), cell_frac=0.03, levels=5,
    )
    assert executor.kept_ids is not None
    assert sorted(executor.kept_ids) == [int(i) for i in expected.level_ids[4]]
    assert "keep_only_ids" in executor.edit_calls
    assert c._edits_applied == 1
    assert len(_reloads(channel)) == 1                  # resync sent
    assert result.status == "answered"


def test_subject_reject_skips_edit():
    channel = TourChannel(verdicts=[{"verdict": "rejected"}])
    executor = RecordingExecutor()
    provider = ChoiceProvider(_o3() + _good3() + [_mark([]), _mark([]), _mark([])])
    c = _controller(provider, channel, executor)
    result = _run(c.run("cleanup_scene"))
    assert "keep_only_ids" not in executor.edit_calls
    assert executor.kept_ids is None
    # survey still ran
    assert any(cmd.get("tool") == "survey_capture" for cmd in channel.commands)
    assert result.status == "answered"


def test_model_breaker_stops_asking_after_consecutive_failures():
    """Live-found: a tunnel that dies mid-run makes EVERY forced call ride the
    full timeout ladder (45s x 2 attempts), turning graceful degradation into
    ~30 minutes of silent dead air across the phases. After
    `model_failure_limit` consecutive failed asks the provider must not be
    consulted again this run — everything degrades to safe defaults fast."""
    channel = TourChannel(verdicts=[{"verdict": "rejected"}])
    executor = RecordingExecutor()
    provider = ChoiceProvider([RuntimeError("down")] * 50)
    c = _controller(provider, channel, executor)
    result = _run(c.run("cleanup_scene"))
    assert result.status == "answered"
    # 2 failed asks x (try + retry) = 4 provider calls; nothing after the trip
    assert len(provider.calls) == 4
    # the operator was told once that the model is out of the loop
    texts = [e.get("text", "") for e in channel.events if e.get("type") == "narrate"]
    assert any("safe defaults" in t for t in texts)


def test_model_breaker_resets_on_success():
    """One flaky ask must not poison the run: a success between failures
    resets the count, so the model stays in the loop."""
    channel = TourChannel(verdicts=[{"verdict": "rejected"}])
    executor = RecordingExecutor()
    provider = ChoiceProvider(
        [RuntimeError("blip"), RuntimeError("blip"),   # outline 1 fails (try+retry)
         _ol(), _ol()] +                               # outlines 2-3 succeed: reset
        _good3() +                                     # subject votes
        [_mark(["B3"]), _mark([]), _mark([])]          # marks still consulted
    )
    c = _controller(provider, channel, executor)
    result = _run(c.run("cleanup_scene"))
    assert result.status == "answered"
    mark_calls = [k for k in provider.calls if k["tools"] == ["mark_noise"]]
    assert len(mark_calls) == 3                        # breaker never tripped


def test_giant_scale_splats_land_in_outside_ids():
    """When the arrays carry per-splat scales, the controller must pass them
    to find_subject so streak/needle gaussians are excluded from the keep-set
    (they arrive at the frontend in outside_ids and die with the approval)."""
    arrays = _scene_arrays()
    n = len(arrays["ids"])
    scales = np.full((n, 3), 0.01)
    scales[:10, 0] = 20.0                      # 10 giant streaks in the core
    arrays["scale"] = scales
    channel = TourChannel(verdicts=[{"verdict": "rejected"}])
    executor = RecordingExecutor()
    provider = ChoiceProvider(_o3() + _good3())
    c = _controller(provider, channel, executor, arrays=lambda: arrays)
    _run(c.run("cleanup_scene"))
    preview = next(cmd for cmd in channel.commands
                   if cmd.get("tool") == "show_subject_preview")
    outside = set(preview["args"]["outside_ids"])
    assert set(range(10)) <= outside


def test_outlined_views_carve_the_keep_set():
    """v0.8.1 scene-hull: the model's outlines are the PRIMARY keep decision.
    With a camera that actually frames the building and outlines covering only
    the LEFT half of every view, the right half of the building must land in
    the excluded set at the default level — reasoning carved it, not stats."""
    class HullChannel(TourChannel):
        async def send_command(self, cmd):
            if cmd.get("type") == "capture_request" and cmd.get("tool") == "survey_capture":
                self.commands.append(cmd)
                self._sends += 1
                return {
                    "frames": [self.frame] * 3,
                    "labels": ["a", "b", "c"],
                    # render-space camera at z=8 looking at the origin: the
                    # building (backend +-0.5) is centered in frame
                    "poses": [{"position": [0, 0, 8], "target": [0, 0, 0],
                               "fov": 60.0, "aspect": 1.0}] * 3,
                    "revision": 1,
                }
            return await super().send_command(cmd)

    arrays = _scene_arrays()
    means = np.asarray(arrays["means"])
    channel = HullChannel(verdicts=[{"verdict": "rejected"}])
    executor = RecordingExecutor()
    provider = ChoiceProvider([_ol(0.0, 0.0, 0.5, 1.0)] * 3 + _good3())
    c = _controller(provider, channel, executor, arrays=lambda: arrays)
    result = _run(c.run("cleanup_scene"))
    assert result.status == "answered"
    preview = next(cmd for cmd in channel.commands
                   if cmd.get("tool") == "show_subject_preview")
    args = preview["args"]
    # excluded at the DEFAULT level = outside ∪ deltas[default:]
    excl = set(args["outside_ids"])
    for d in args["deltas"][2:]:
        excl |= set(d)
    right = set(int(i) for i in np.where(means[:, 0] > 0.05)[0] if i < 2000)
    left = set(int(i) for i in np.where(means[:, 0] < -0.05)[0] if i < 2000)
    assert right <= excl                       # reasoning carved the right half
    assert len(left & excl) <= len(left) * 0.1  # ...and kept the left


def test_no_subject_found_skips_phase():
    """A degenerate scene (find_subject → None): no preview, no card, phase 2
    still runs."""
    rng = np.random.default_rng(0)
    arrays = {
        "means": rng.normal(size=(10, 3)),
        "opacity": np.full(10, 0.9),
        "ids": np.arange(10, dtype=np.int64),
    }
    channel = TourChannel(verdicts=[])
    executor = RecordingExecutor()
    provider = ChoiceProvider([_mark([]), _mark([]), _mark([])])
    c = _controller(provider, channel, executor, arrays=lambda: arrays)
    result = _run(c.run("cleanup_scene"))
    assert not any(cmd.get("tool") == "show_subject_preview" for cmd in channel.commands)
    assert not any(cmd.get("type") == "proposal" and cmd["args"].get("kind") == "keep_only_subject"
                   for cmd in channel.commands)
    assert any(cmd.get("tool") == "survey_capture" for cmd in channel.commands)
    assert result.status == "answered"


def test_phase2_one_mark_call_per_frame_with_gridded_survey():
    channel = TourChannel(n_frames=3, verdicts=[{"verdict": "approved"}])
    executor = RecordingExecutor()
    provider = ChoiceProvider(_o3() + _good3() + [_mark(["B3"]), _mark([]), _mark([])])
    c = _controller(provider, channel, executor)
    _run(c.run("cleanup_scene"))
    mark_calls = [k for k in provider.calls if k["tools"] == ["mark_noise"]]
    assert len(mark_calls) == 3
    # the MARKS survey is gridded; phase 1's outline survey (first) is not
    surveys = [cmd for cmd in channel.commands if cmd.get("tool") == "survey_capture"]
    assert len(surveys) == 2
    assert surveys[0]["args"].get("grid") is not True
    assert surveys[-1]["args"].get("grid") is True


def test_phase2_respects_max_survey_frames():
    channel = TourChannel(n_frames=9, verdicts=[{"verdict": "approved"}])
    executor = RecordingExecutor()
    # phase-1 outlines are capped at outline_views (4), not n_frames
    provider = ChoiceProvider([_ol()] * 4 + _good3() + [_mark([])] * 9)
    c = _controller(provider, channel, executor)
    _run(c.run("cleanup_scene"))
    mark_calls = [k for k in provider.calls if k["tools"] == ["mark_noise"]]
    assert len(mark_calls) == 6  # capped


def test_phase3_stats_cluster_survives_model_silence():
    # ALL asks fail (subject votes and marks) -> candidates come from
    # statistics alone (spec §8)
    channel = TourChannel(verdicts=[{"verdict": "approved"}])
    executor = RecordingExecutor()
    provider = ChoiceProvider([RuntimeError("down")] * 14)
    c = _controller(provider, channel, executor)
    result = _run(c.run("cleanup_scene"))
    assert len(c.candidates) == 1          # the far blob
    assert c.candidates[0].provenance == "stats"
    assert result.status == "answered"     # the run still completes


def test_interrupt_aborts_run_with_interrupted_status():
    channel = TourChannel(verdicts=[{"verdict": "approved"}])
    channel.interrupt_after = 1
    executor = RecordingExecutor()
    provider = ChoiceProvider(_o3() + _good3() + [_mark([])] * 3)
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
    channel = TourChannel(verdicts=[{"verdict": "approved"},   # subject card
                                    {"verdict": "approved"}])  # batch
    executor = DeletingExecutor()
    provider = ChoiceProvider(
        _o3() + _good3() +                                 # subject voting round
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
        _o3() + _good3() +
        [_mark([]), _mark([]), _mark([])] +
        [_judge("look_closer"), _judge("junk"),          # candidate A: 2 calls
         _judge("look_closer"), _judge("look_closer")]   # candidate B: coerced
    )
    c = _tour_controller(provider, channel, executor)
    _run(c.run("cleanup_scene"))
    assert c.verdicts["A"] == "junk"
    assert c.verdicts["B"] == "structure"     # second look_closer coerces to keep
    # look_closer flew an extra view per use (deg=70 — the subject phase's own
    # voting orbits use 360//subject_judge_frames and must not be counted)
    orbits = [cmd for cmd in channel.commands
              if cmd.get("tool") == "orbit" and cmd["args"].get("deg") == 70]
    assert len(orbits) == 2


def test_model_failure_during_tour_is_unsure_kept():
    channel = TourChannel(verdicts=[{"verdict": "approved"}, {"verdict": "approved"}])
    executor = DeletingExecutor()
    provider = ChoiceProvider(_o3() + _good3() +
                              [_mark([]), _mark([]), _mark([]),
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
    provider = ChoiceProvider(_o3() + _good3() +
                              [_mark([]), _mark([]), _mark([]),
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
    channel = TourChannel(verdicts=[{"verdict": "approved"},   # subject card
                                    {"verdict": "rejected"}])  # batch
    executor = DeletingExecutor()
    provider = ChoiceProvider(_o3() + _good3() +
                              [_mark([]), _mark([]), _mark([]),
                               _judge("junk"), _judge("junk")])
    c = _tour_controller(provider, channel, executor)
    result = _run(c.run("cleanup_scene"))
    assert executor.deleted_batches == []
    assert result.status == "answered"
    assert "kept" in (result.answer or "").lower()


def test_adjust_flips_verdict_then_reproposes():
    channel = TourChannel(verdicts=[
        {"verdict": "approved"},                                   # subject card
        {"verdict": "adjusted", "feedback": "keep A, it is a shed"},
        {"verdict": "approved"},                                   # re-proposed batch
    ])
    executor = DeletingExecutor()
    flip = ModelResponse(text=None, tool_calls=[ToolCall(
        "apply_feedback", {"flips": [{"label": "A", "to": "keep"}]})])
    provider = ChoiceProvider(_o3() + _good3() +
                              [_mark([]), _mark([]), _mark([]),
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
    provider = ChoiceProvider(_o3() + _good3() + [_mark([]), _mark([]), _mark([])])
    c = _tour_controller(provider, channel, executor, arrays=lambda: arrays)
    result = _run(c.run("cleanup_scene"))
    assert result.status == "answered"
    assert executor.deleted_batches == []
    batch_cards = [cmd for cmd in channel.commands
                   if cmd.get("type") == "proposal" and cmd["args"].get("kind") == "delete_clusters"]
    assert batch_cards == []


# ---------------------------------------------------------------------------
# Hard stop: ws.py cancels the run task on user_interrupt (live-found: the
# cooperative flag alone cannot stop a run parked on a proposal, which has NO
# timeout, or one grinding a dead model's 90s-per-ask ladder)
# ---------------------------------------------------------------------------
def test_hard_cancel_mid_parked_proposal_completes_interrupted():
    class ParkedChannel(TourChannel):
        parked = False

        async def send_command(self, cmd):
            if cmd.get("type") == "proposal":
                self.commands.append(cmd)
                self.parked = True
                await asyncio.Event().wait()      # a card nobody ever decides
            return await super().send_command(cmd)

    async def scenario():
        channel = ParkedChannel()
        executor = RecordingExecutor()
        provider = ChoiceProvider(_o3() + _good3())
        c = _controller(provider, channel, executor)
        task = asyncio.create_task(c.run("cleanup_scene"))
        for _ in range(500):
            if channel.parked:
                break
            await asyncio.sleep(0.01)
        assert channel.parked, "run never reached the parked proposal"
        task.cancel()
        return await task, channel

    result, channel = _run(scenario())
    assert result.status == "interrupted"
    done = _complete(channel)
    assert done["status"] == "interrupted"
    assert done["scene_changed"] is False      # nothing was edited before the stop


# ---------------------------------------------------------------------------
# Codex adversarial review: partial-edit reporting on every completion path
# ---------------------------------------------------------------------------
def _complete(channel):
    return next(e for e in channel.events if e.get("type") == "complete")


def test_interrupt_after_keep_only_still_reports_scene_changed():
    """An edit that landed before an interrupt must still make the viewer
    resync — otherwise the operator sees pre-edit splats over a keep-only'd
    backend with a desynced ID map (mirrors AgentLoop._finish_status)."""
    channel = TourChannel(verdicts=[{"verdict": "approved"}])
    channel.interrupt_after = 2          # keep-only applied, then interrupt
    executor = RecordingExecutor()
    provider = ChoiceProvider(_o3() + _good3() + [_mark([])] * 3)
    c = _controller(provider, channel, executor)
    result = _run(c.run("cleanup_scene"))
    assert result.status == "interrupted"
    assert "keep_only_ids" in executor.edit_calls      # the edit did land
    assert _complete(channel)["scene_changed"] is True


def test_run_without_any_edit_reports_scene_changed_false():
    """Nothing was destroyed — a reload would be pure churn."""
    channel = TourChannel(verdicts=[{"verdict": "rejected"}])   # subject rejected
    executor = RecordingExecutor()
    provider = ChoiceProvider(_o3() + _good3() + [_mark([])] * 3 + [_judge("structure")])
    c = _controller(provider, channel, executor)
    result = _run(c.run("cleanup_scene"))
    assert result.status == "answered"
    assert executor.edit_calls == []
    assert _complete(channel)["scene_changed"] is False


def test_error_path_reports_scene_changed_after_an_edit():
    channel = TourChannel(verdicts=[{"verdict": "approved"}])
    executor = RecordingExecutor()
    provider = ChoiceProvider(_o3() + _good3() + [_mark([])] * 3)
    c = _controller(provider, channel, executor)
    # blow up after phase 1 has already applied the keep-only edit
    async def boom() -> None:
        raise RuntimeError("controller bug")
    c._phase2_survey_and_mark = boom          # type: ignore[assignment]
    result = _run(c.run("cleanup_scene"))
    assert result.status == "error"
    assert "keep_only_ids" in executor.edit_calls
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
    provider = ChoiceProvider(_o3() +
                              [_mark([]), _mark([]), _mark([]),
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
    provider = ChoiceProvider(_o3() + _good3() +
                              [_mark([]), _mark([]), _mark([]),
                               _judge("junk"), _judge("junk")])
    c = _tour_controller(provider, channel, executor)
    _run(c.run("cleanup_scene"))
    assert set(c.verdicts.values()) == {"unsure"}
    assert executor.deleted_batches == []


def test_failed_subject_preview_fails_closed_and_skips_the_card():
    """Live-found: the controller used to ignore a failed tint dispatch and
    march on to judge/propose a highlight nobody could see. A preview that
    cannot be shown must skip the whole keep-only pass — same rule as an
    unframed tour candidate."""
    channel = FlakyChannel("show_subject_preview", verdicts=[{"verdict": "approved"}])
    executor = DeletingExecutor()
    provider = ChoiceProvider(_o3() +
                              [_mark([]), _mark([]), _mark([]),
                               _judge("structure"), _judge("structure")])
    c = _tour_controller(provider, channel, executor)
    result = _run(c.run("cleanup_scene"))
    # no card, no keep-only edit, no subject votes on an invisible tint
    assert not any(cmd.get("type") == "proposal" and cmd["args"].get("kind") == "keep_only_subject"
                   for cmd in channel.commands)
    assert "keep_only_ids" not in executor.edit_calls
    assert [k for k in provider.calls if k["tools"] == ["judge_subject"]] == []
    # the run continues: survey + tour still happen
    assert any(cmd.get("tool") == "survey_capture" for cmd in channel.commands)
    assert result.status == "answered"


def test_failed_framing_forces_unsure():
    channel = FlakyChannel("frame_object", verdicts=[{"verdict": "approved"}])
    executor = DeletingExecutor()
    provider = ChoiceProvider(_o3() +
                              [_mark([]), _mark([]), _mark([]),
                               _judge("junk"), _judge("junk")])
    c = _tour_controller(provider, channel, executor)
    _run(c.run("cleanup_scene"))
    assert set(c.verdicts.values()) == {"unsure"}
    assert executor.deleted_batches == []


# ---------------------------------------------------------------------------
# Codex adversarial review: the per-edit guard must not run k-NN metrics
# ---------------------------------------------------------------------------
class MetricsCountingExecutor(DeletingExecutor):
    """compute_metrics does a full k-NN pass (minutes on a 2M-splat scene);
    the guard must never reach it."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.metrics_calls = 0

    def get_metrics(self, region=None):
        self.metrics_calls += 1
        return super().get_metrics(region)


def _live_arrays():
    """Arrays that actually shrink as clusters are deleted, so the guard sees
    real before/after state instead of a frozen snapshot."""
    rng = np.random.default_rng(0)
    building = rng.uniform(-0.5, 0.5, size=(2000, 3))
    blob_a = np.array([10.0, 0.0, 0.0]) + rng.normal(0, 0.05, size=(80, 3))
    blob_b = np.array([0.0, 12.0, 0.0]) + rng.normal(0, 0.05, size=(50, 3))
    means = np.vstack([building, blob_a, blob_b])
    state = {
        "means": means,
        "opacity": np.full(len(means), 0.8),
        "ids": np.arange(len(means), dtype=np.int64),
    }
    return lambda: state


def test_guard_never_calls_full_metrics():
    channel = TourChannel(verdicts=[{"verdict": "approved"}, {"verdict": "approved"}])
    executor = MetricsCountingExecutor()
    provider = ChoiceProvider(_o3() + _good3() +
                              [_mark([]), _mark([]), _mark([]),
                               _judge("junk"), _judge("junk")])
    c = _tour_controller(provider, channel, executor, arrays=_live_arrays())
    _run(c.run("cleanup_scene"))
    assert len(executor.deleted_batches) == 2     # edits really ran
    assert executor.metrics_calls == 0            # ...with no k-NN pass


def test_guard_still_reverts_an_edit_that_wipes_the_core():
    """The cheap guard must keep its teeth: a delete that takes the subject
    with it is undone and reported."""
    from backend.agent.cleanup_controller import CleanupConfig, CleanupController

    means = np.vstack([
        np.random.default_rng(0).uniform(-0.5, 0.5, size=(2000, 3)),
        np.array([10.0, 0.0, 0.0]) + np.random.default_rng(1).normal(0, 0.05, size=(80, 3)),
    ])
    state = {
        "means": means,
        "opacity": np.full(len(means), 0.8),
        "ids": np.arange(len(means), dtype=np.int64),
    }

    class WipingExecutor(DeletingExecutor):
        undo_calls = 0

        def delete_selection(self, ids):
            out = super().delete_selection(ids)
            state["means"] = state["means"][:1]      # everything is gone
            state["opacity"] = state["opacity"][:1]
            state["ids"] = state["ids"][:1]
            return out

        def undo(self):
            self.undo_calls += 1
            return super().undo()

    channel = TourChannel(verdicts=[{"verdict": "rejected"},   # skip the keep-only
                                    {"verdict": "approved"}])
    executor = WipingExecutor()
    provider = ChoiceProvider(_o3() + _good3() +
                              [_mark([]), _mark([]), _mark([]), _judge("junk")])
    dispatcher = ToolDispatcher(executor, channel)
    c = CleanupController(provider, dispatcher, channel, executor, lambda: state,
                          CleanupConfig(call_timeout_s=5.0))
    result = _run(c.run("cleanup_scene"))
    assert executor.undo_calls == 1                       # reverted
    assert "0 clusters deleted" in (result.answer or "")


# ---------------------------------------------------------------------------
# Codex adversarial review: perception must run on the authoritative scene
# ---------------------------------------------------------------------------
class SceneChannel(TourChannel):
    """A channel that knows its scene id — the real WSChannel does."""

    scene_id = "scene-1"


def _reloads(channel):
    return [c for c in channel.commands if c.get("type") == "reload_scene"]


def test_applied_keep_only_resyncs_the_renderer_before_the_survey():
    """The survey must photograph the KEPT-ONLY scene: without a reload the
    renderer still shows the splats the backend just deleted, so the model
    marks junk that no longer exists."""
    channel = SceneChannel(verdicts=[{"verdict": "approved"}])
    executor = RecordingExecutor()
    provider = ChoiceProvider(_o3() + _good3() + [_mark([])] * 3)
    c = _controller(provider, channel, executor)
    _run(c.run("cleanup_scene"))

    reloads = _reloads(channel)
    assert len(reloads) == 1
    payload = reloads[0]["payload"]
    assert payload["url"] == "/scene/scene-1.ply"
    assert payload["scene_id"] == "scene-1"
    # ...and it happened BEFORE the marks survey (the LAST survey_capture —
    # v0.8.1 flies an earlier outline survey in phase 1, before any edit)
    order = [cmd.get("type") if cmd.get("type") == "reload_scene" else cmd.get("tool")
             for cmd in channel.commands]
    last_survey = len(order) - 1 - order[::-1].index("survey_capture")
    assert order.index("reload_scene") < last_survey


def test_rejected_subject_does_not_reload():
    channel = SceneChannel(verdicts=[{"verdict": "rejected"}])
    executor = RecordingExecutor()
    provider = ChoiceProvider(_o3() + _good3() + [_mark([])] * 3)
    c = _controller(provider, channel, executor)
    _run(c.run("cleanup_scene"))
    assert _reloads(channel) == []


def test_batch_deletions_resync_once_when_finished():
    channel = SceneChannel(verdicts=[{"verdict": "approved"}, {"verdict": "approved"}])
    executor = DeletingExecutor()
    provider = ChoiceProvider(_o3() + _good3() +
                              [_mark([]), _mark([]), _mark([]),
                               _judge("junk"), _judge("junk")])
    c = _tour_controller(provider, channel, executor)
    _run(c.run("cleanup_scene"))
    # one after the keep-only, one after the whole batch — not one per cluster
    assert len(_reloads(channel)) == 2


def test_channel_without_a_scene_id_degrades_quietly():
    """MockFrontendChannel and other harnesses have no scene id; the run must
    still complete rather than crash on the resync."""
    channel = TourChannel(verdicts=[{"verdict": "approved"}])
    executor = RecordingExecutor()
    provider = ChoiceProvider(_o3() + _good3() + [_mark([])] * 3)
    c = _controller(provider, channel, executor)
    result = _run(c.run("cleanup_scene"))
    assert result.status == "answered"
    assert _reloads(channel) == []
