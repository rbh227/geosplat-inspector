"""App-owned judgment-tour cleanup (spec 2026-08-04-judgment-tour-cleanup;
subject-first rework 2026-08-07).

A Python phase machine replaces the freeform loop for cleanup runs. The model
is consulted ONLY through ask_forced(): subject votes in phase 1, grid marks
in phase 2, verdicts in phase 4, feedback flips in phase 5. Everything spatial
and procedural is code.

Phases: 1 subject lock-on -> 2 survey & mark -> 3 lock-in -> 4 tour -> 5 batch
proposal -> 6 summary. Every phase boundary checks interrupt/pause; every
model failure degrades one datum to a safe default (unsure = keep / default
level). The run always reaches the summary.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from backend.analysis.clusters import (
    Cluster,
    core_box,
    find_clusters,
    resolve_marks,
)
from backend.analysis.subject import SubjectLevels, find_subject
from backend.contracts import FrontendChannel, ModelProvider, ToolCall
from backend.contracts.constants import VISIBILITY_ALPHA
from backend.contracts.tools import CONTROLLER_CHOICE_SPECS

from .dispatch import ToolDispatcher
from .forced_choice import ask_forced
from .types import LoopResult, ev_complete, ev_narrate, ev_tool_call, ev_tool_result
from .verify import silhouette_intact


@dataclass
class CleanupConfig:
    max_survey_frames: int = 6
    grid: int = 4
    max_candidates: int = 12
    max_look_closer: int = 1
    call_timeout_s: float = 45.0
    call_retries: int = 1
    max_adjust_rounds: int = 3
    min_cluster_splats: int = 30
    cell_frac: float = 0.03
    subject_levels: int = 5
    subject_judge_frames: int = 3
    subject_judge_rounds: int = 2
    # Consecutive failed asks before the model is dropped for the rest of the
    # run (live-found: a tunnel that dies mid-run otherwise costs the full
    # 45s x 2 timeout ladder on EVERY remaining datum — ~30 min of dead air).
    model_failure_limit: int = 2


_MARK_INSTRUCTION = (
    "This is one view of a 3D-scanned scene with a {grid}x{grid} labeled grid "
    "(columns A-D left to right, rows 1-4 top to bottom). Call mark_noise with "
    "the cells that contain floating junk, debris mist, or fragments "
    "disconnected from the main structure. Use [] if this view looks clean."
)

_SUBJECT_INSTRUCTION = (
    "The bright-tinted splats are the region I plan to KEEP; everything dim "
    "will be DELETED. Call judge_subject: 'good' if the tint covers exactly "
    "the real structure, 'clipping_structure' if any real scenery is dim "
    "(keep-region too tight), or 'including_junk' if floating debris or "
    "disconnected fragments are tinted (too loose)."
)

_JUDGE_INSTRUCTION = (
    "The highlighted (tinted) cluster of points is candidate {label}: "
    "{count} splats, {dist:.1f} units from the main structure. Call "
    "judge_candidate: 'junk' if it is floating debris/noise to delete, "
    "'structure' if it is part of a real object to keep, or 'look_closer' "
    "for one more view if you truly cannot tell."
)

# Controller-private (not a contract tool): translate operator adjust-feedback
# into per-cluster keep/delete flips via one forced call.
_FEEDBACK_SPEC = {
    "name": "apply_feedback",
    "description": "Translate the operator's feedback into per-cluster flips.",
    "parameters": {
        "type": "object",
        "properties": {
            "flips": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "to": {"type": "string", "enum": ["keep", "delete"]},
                    },
                    "required": ["label", "to"],
                },
            },
        },
        "required": ["flips"],
    },
}


class RunInterrupted(Exception):
    pass


class CleanupController:
    def __init__(
        self,
        provider: ModelProvider,
        dispatcher: ToolDispatcher,
        channel: FrontendChannel,
        executor: Any,
        splat_arrays: Callable[[], dict],
        config: CleanupConfig | None = None,
    ) -> None:
        self.provider = provider
        self.dispatcher = dispatcher
        self.channel = channel
        self.executor = executor
        self.splat_arrays = splat_arrays
        self.config = config or CleanupConfig()
        self._step = 0
        # Model circuit breaker: consecutive failed asks; once the limit trips
        # the model is out of the loop for the rest of the run.
        self._ask_failures = 0
        self._model_down = False
        # True while a destructive edit is running in a worker thread — a hard
        # Stop landing then must still report scene_changed.
        self._edit_in_flight = False
        # Did any destructive edit actually land? Reported as `scene_changed`
        # on EVERY completion path: an edit that succeeded before an interrupt
        # or a controller bug still leaves the renderer showing a stale scene
        # with a desynced ID map unless the viewer resyncs (same invariant as
        # AgentLoop._finish_status / _finish_error).
        self._edits_applied = 0
        # phase-3 outputs
        self.candidates: list[Cluster] = []
        self.marks: list[dict] = []
        self.unresolved_marks = 0
        self.crop_result: dict | None = None
        # phase-4 outputs
        self.verdicts: dict[str, str] = {}
        self.reasons: dict[str, str] = {}

    # ---- plumbing -------------------------------------------------------- #
    async def _emit(self, event: dict) -> None:
        await self.channel.emit_event(event)

    async def _say(self, text: str) -> None:
        await self._emit(ev_narrate(text))

    async def _checkpoint(self) -> None:
        """Interrupt/pause gate — called at every phase boundary and tour stop."""
        if getattr(self.channel, "interrupted", False):
            raise RunInterrupted
        if getattr(self.channel, "paused", False):
            await self._say("Paused — resume to continue the cleanup.")
            wait = getattr(self.channel, "wait_resume", None)
            if wait is not None:
                await wait()
            if getattr(self.channel, "interrupted", False):
                raise RunInterrupted

    async def _dispatch(self, name: str, args: dict) -> dict:
        self._step += 1
        await self._emit(ev_tool_call(name, args, self._step))
        result = await self.dispatcher.dispatch(ToolCall(name, dict(args)))
        await self._emit(ev_tool_result(
            name, {k: v for k, v in result.items() if k != "frames"}, self._step,
        ))
        return result

    async def _ask(self, instruction: str, spec_name: str, image: bytes | None) -> dict | None:
        if self._model_down:
            return None
        args = await ask_forced(
            self.provider, instruction, CONTROLLER_CHOICE_SPECS[spec_name], image,
            timeout_s=self.config.call_timeout_s, retries=self.config.call_retries,
        )
        if args is None:
            self._ask_failures += 1
            if self._ask_failures >= self.config.model_failure_limit:
                self._model_down = True
                await self._say(
                    "The model isn't responding — continuing with safe defaults "
                    "(everything unjudged is kept)."
                )
        else:
            self._ask_failures = 0
        return args

    def _scene_changed(self) -> bool:
        return self._edits_applied > 0

    async def _resync_renderer(self) -> None:
        """Make the viewer show the scene the backend actually has.

        Every phase after an edit is PERCEPTION: the survey photographs the
        scene and the tour judges tinted clusters. Without this the renderer
        still holds the pre-edit splats and a stale ID map, so the model marks
        and judges geometry the backend already deleted. Best-effort — a
        renderer that cannot reload must not abort the run.
        """
        scene_id = getattr(self.channel, "scene_id", None)
        if not scene_id:
            return  # test harnesses / channels without a scene: nothing to resync
        try:
            await self.channel.send_command({
                "type": "reload_scene",
                "payload": {"url": f"/scene/{scene_id}.ply", "scene_id": scene_id},
            })
        except Exception as exc:  # noqa: BLE001 — a failed reload is not fatal
            await self._say(f"Could not refresh the viewer ({exc}); continuing.")

    def _arrays(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        a = self.splat_arrays()
        return np.asarray(a["means"]), np.asarray(a["opacity"]), np.asarray(a["ids"])

    # ---- destructive edit with the standard guard ------------------------ #
    def _guard_metrics(self) -> dict:
        """The ONLY two fields `silhouette_intact` reads, computed O(N) with no
        k-NN.

        `compute_metrics` runs a full KD-tree query — documented in
        splat/model.py as taking MINUTES on a 2M-splat scene — and the tour can
        fire up to 12 guarded deletions in one approval, so calling it
        before/after each edit would make an approved batch effectively
        non-terminating at demo scale.
        """
        _, opacity, ids = self._arrays()
        count = int(len(ids))
        near = float((np.asarray(opacity) < VISIBILITY_ALPHA).mean()) if count else 0.0
        return {"gaussianCount": count, "opacity": {"nearTransparentFraction": near}}

    async def _guarded_edit(self, fn_name: str, *args) -> dict:
        """snapshot -> edit -> silhouette check (approved=True: the operator
        reviewed this exact operation) -> undo on catastrophe."""
        # A hard Stop that lands mid-edit cannot know whether the mutation
        # finished (the worker thread keeps running); the flag makes the
        # cancellation path report scene_changed conservatively. Never reset:
        # every COMPLETED guarded edit increments _edits_applied, which makes
        # scene_changed true on its own.
        self._edit_in_flight = True
        before = await asyncio.to_thread(self._guard_metrics)
        await asyncio.to_thread(self.executor.snapshot)
        result = await asyncio.to_thread(getattr(self.executor, fn_name), *args)
        after = await asyncio.to_thread(self._guard_metrics)
        if not silhouette_intact(before, after, approved=True):
            await asyncio.to_thread(self.executor.undo)
            # The snapshot+undo round trip is itself a mutation the renderer
            # never saw; count it so the viewer resyncs rather than trusting
            # its local copy.
            self._edits_applied += 1
            await self._say(f"Reverted {fn_name}: it would have destroyed the subject's core.")
            return {"ok": False, "reverted": True, "result": result}
        self._edits_applied += 1
        return {"ok": True, "result": result, "before": before, "after": after}

    # ---- run ------------------------------------------------------------- #
    async def run(self, prompt: str) -> LoopResult:
        result = LoopResult(status="answered")
        try:
            await self._phase1_subject()
            await self._checkpoint()
            await self._phase2_survey_and_mark()
            await self._checkpoint()
            self._phase3_lock_in()
            await self._say(self._lock_in_summary())
            await self._checkpoint()
            answer = await self._phases_4_to_6()
            result.answer = answer
            await self._emit(ev_complete(
                "answered", answer=answer, scene_changed=self._scene_changed(),
            ))
        except RunInterrupted:
            result.status = "interrupted"
            await self._emit(ev_complete("interrupted", scene_changed=self._scene_changed()))
        except asyncio.CancelledError:
            # Hard stop: ws.py cancels the run task on user_interrupt, so Stop
            # works even mid-await (model timeout ladder, wedged frontend
            # command, parked proposal). Swallowing the cancellation here is
            # deliberate — the stop is consumed by completing the run.
            result.status = "interrupted"
            await self._emit(ev_complete(
                "interrupted",
                scene_changed=self._scene_changed() or self._edit_in_flight,
            ))
        except Exception as exc:  # noqa: BLE001 — a controller bug must still end the run
            result.status = "error"
            result.error = str(exc)
            await self._emit(ev_complete(
                "error", error=str(exc), scene_changed=self._scene_changed(),
            ))
        result.steps = self._step
        return result

    # ---- phase 1: subject lock-on ----------------------------------------- #
    async def _phase1_subject(self) -> None:
        # Narrate BEFORE the analysis: on a 2M-splat scene the subject search
        # takes ~15s and the operator must not stare at dead air. to_thread
        # keeps the event loop (WS heartbeats, Stop/pause) responsive.
        await self._say("Looking for the main subject — this can take a moment on big scenes.")
        a = self.splat_arrays()
        means, opacity, ids = (
            np.asarray(a["means"]), np.asarray(a["opacity"]), np.asarray(a["ids"]),
        )
        subject = await asyncio.to_thread(
            find_subject, means, opacity, ids,
            cell_frac=self.config.cell_frac, levels=self.config.subject_levels,
            # Per-splat scales let the finder drop streak/needle gaussians
            # from the keep-set; harnesses that omit them just skip the filter.
            scales=a.get("scale"),
        )
        if subject is None:
            await self._say("Could not isolate a subject — skipping the keep-only pass.")
            return
        level = subject.default_level
        await self._say("Locking onto the subject — bright is what I plan to keep.")
        # Complement form (live-found at 2M splats): ship the small excluded
        # set, never the ~N-id keep-set. The viewer inverts locally.
        outside = np.setdiff1d(ids, subject.level_ids[-1])
        shown = await self._dispatch("show_subject_preview", {
            "outside_ids": [int(i) for i in outside],
            "deltas": [
                [int(i) for i in np.setdiff1d(b, a)]
                for a, b in zip(subject.level_ids, subject.level_ids[1:])
            ],
            "counts": subject.counts,
            "level": level,
        })
        if not shown.get("ok"):
            # Fail closed — never judge or propose a highlight nobody can see
            # (same rule as an unframed tour candidate).
            await self._say(
                "The viewer could not show the subject highlight — skipping the keep-only pass."
            )
            return
        level = await self._judge_subject_rounds(subject, level)

        n_total = len(ids)
        n_keep = subject.counts[level]
        reply = await self._dispatch("propose_decision", {
            "kind": "keep_only_subject",
            "summary": f"Keep the highlighted subject ({n_keep} splats) and delete "
                       f"the {n_total - n_keep} splats outside it. Slide "
                       "looser/tighter to adjust before approving.",
        })
        verdict = (reply.get("result") or {}) if reply.get("ok") else {}
        if isinstance(verdict, dict) and verdict.get("verdict") == "approved":
            # The reply's level is the slider's FINAL position — it binds the
            # edit to exactly what the operator reviewed on screen.
            try:
                lvl = int(verdict.get("level", level))
            except (TypeError, ValueError):
                lvl = level
            lvl = max(0, min(len(subject.level_ids) - 1, lvl))
            out = await self._guarded_edit(
                "keep_only_ids", [int(i) for i in subject.level_ids[lvl]],
            )
            if out["ok"]:
                self.crop_result = out["result"]
                await self._say("Kept the subject — everything outside it is gone.")
            # Resync either way: a reverted edit also snapshotted+undid, and the
            # survey that follows must photograph the authoritative scene.
            await self._resync_renderer()
        else:
            await self._say("Keep-only skipped — moving on to the noise survey.")
        await self._dispatch("clear_selection", {})

    async def _judge_subject_rounds(self, subject: SubjectLevels, level: int) -> int:
        """Up to subject_judge_rounds voting rounds; each frames the subject,
        orbits between captures, and takes one forced judge_subject vote per
        frame. Model failures are abstentions — the level never moves on them."""
        max_level = len(subject.level_ids) - 1
        for r in range(self.config.subject_judge_rounds):
            await self._checkpoint()
            # Narrate per round: each vote can take a full model call, and the
            # operator must never face minutes of unexplained silence.
            await self._say(
                f"Reviewing the highlight from {self.config.subject_judge_frames} "
                f"angles (round {r + 1})."
            )
            framed = await self._dispatch("frame_object", {
                "bbox": {"min": subject.bbox_min, "max": subject.bbox_max},
                "duration_ms": 900,
            })
            if not framed.get("ok"):
                return level          # fail closed: never judge an unframed view
            votes: list[str] = []
            center = [(a + b) / 2 for a, b in zip(subject.bbox_min, subject.bbox_max)]
            for j in range(self.config.subject_judge_frames):
                if j:
                    await self._dispatch("orbit", {
                        "center": center,
                        "deg": 360 // self.config.subject_judge_frames,
                        "axis": "y", "duration_ms": 700,
                    })
                cap = await self._dispatch("capture_frame", {})
                frames = cap.get("frames") or []
                if not frames:
                    continue
                args = await self._ask(_SUBJECT_INSTRUCTION, "judge_subject", frames[0])
                v = (args or {}).get("verdict")
                if v in ("good", "clipping_structure", "including_junk"):
                    votes.append(v)
            loosen = votes.count("clipping_structure")
            tighten = votes.count("including_junk")
            if loosen > tighten and level < max_level:
                level += 1
                await self._say("The model says the highlight clips real structure — loosening one step.")
            elif tighten > loosen and level > 0:
                level -= 1
                await self._say("The model says the highlight includes junk — tightening one step.")
            else:
                break
            await self._dispatch("show_subject_preview", {"level": level})
        return level

    # ---- phase 2: survey & mark ------------------------------------------ #
    async def _phase2_survey_and_mark(self) -> None:
        await self._say("Surveying the scene — the model will mark where it sees noise.")
        res = await self._dispatch("survey_capture", {"grid": True})
        payload = res.get("result") or {}
        frames: list[bytes] = list(res.get("frames") or [])[: self.config.max_survey_frames]
        poses: list[dict] = []
        if isinstance(payload, dict):
            poses = list(payload.get("poses") or [])[: len(frames)]
        self.marks = []
        for i, (frame, pose) in enumerate(zip(frames, poses)):
            await self._checkpoint()
            args = await self._ask(
                _MARK_INSTRUCTION.format(grid=self.config.grid), "mark_noise", frame,
            )
            cells = [c for c in (args or {}).get("cells", []) if isinstance(c, str)]
            if args is None:
                await self._say(f"View {i + 1}: model unavailable — skipping its marks.")
            elif cells:
                await self._say(f"View {i + 1}: model marked {', '.join(cells)}.")
            self.marks.append({"cells": cells, "pose": pose})

    # ---- phase 3: lock-in -------------------------------------------------- #
    def _phase3_lock_in(self) -> None:
        means, opacity, ids = self._arrays()
        mn, mx = core_box(means)
        stats = find_clusters(
            means, opacity, ids, mn, mx,
            cell_frac=self.config.cell_frac,
            min_splats=self.config.min_cluster_splats,
            max_clusters=self.config.max_candidates,
        )
        n_marked = sum(1 for m in self.marks if m["cells"])
        merged = resolve_marks(
            means, opacity, ids, self.marks, stats, mn, mx,
            grid=self.config.grid, min_splats=self.config.min_cluster_splats,
        ) if n_marked else stats
        self.unresolved_marks = max(
            0,
            sum(len(m["cells"]) for m in self.marks)
            - sum(c.mark_votes for c in merged),
        )
        self.candidates = merged[: self.config.max_candidates]

    def _lock_in_summary(self) -> str:
        n = len(self.candidates)
        from_model = sum(1 for c in self.candidates if c.provenance == "model")
        both = sum(1 for c in self.candidates if c.provenance == "both")
        return (
            f"Found {n} junk candidate{'s' if n != 1 else ''} "
            f"({both} confirmed by both statistics and the model, "
            f"{from_model} spotted only by the model)."
        )

    # ---- phase 4: judgment tour ------------------------------------------ #
    async def _phase4_tour(self) -> None:
        for cand in self.candidates:
            await self._checkpoint()
            await self._say(
                f"Visiting candidate {cand.label} ({cand.count} splats, {cand.provenance})."
            )
            framed = await self._frame_and_tint(cand)
            verdict, reason = await self._judge_once(cand, framed)
            looks = 0
            while verdict == "look_closer":
                looks += 1
                if looks > self.config.max_look_closer:
                    verdict, reason = "structure", "could not decide — keeping it (safe default)"
                    break
                orbit = await self._dispatch("orbit", {
                    "center": [(a + b) / 2 for a, b in zip(cand.bbox_min, cand.bbox_max)],
                    "deg": 70, "axis": "y", "duration_ms": 800,
                })
                verdict, reason = await self._judge_once(cand, bool(orbit.get("ok")))
                if verdict == "look_closer" and looks >= self.config.max_look_closer:
                    verdict, reason = "structure", "could not decide — keeping it (safe default)"
                    break
            self.verdicts[cand.label] = verdict
            self.reasons[cand.label] = reason
            await self._say(f"Candidate {cand.label}: {verdict} — {reason}")
        await self._dispatch("clear_selection", {})

    async def _frame_and_tint(self, cand: Cluster) -> bool:
        """Fly to the cluster and tint it. Returns False if either step failed —
        the model must never judge an unframed or untinted view."""
        pad = max(cand.extent * 0.5, 0.25)
        bbox = {
            "min": [v - pad for v in cand.bbox_min],
            "max": [v + pad for v in cand.bbox_max],
        }
        framed = await self._dispatch("frame_object", {"bbox": bbox, "duration_ms": 900})
        tinted = await self._dispatch(
            "select_by_ids", {"ids": [int(i) for i in cand.ids], "mode": "replace"},
        )
        return bool(framed.get("ok")) and bool(tinted.get("ok"))

    async def _judge_once(self, cand: Cluster, framed: bool = True) -> tuple[str, str]:
        """One forced verdict. Fails CLOSED: without a framed, tinted, actually
        captured view there is nothing to judge, so the cluster is kept and the
        model is not asked at all (a blind 'junk' would delete real geometry)."""
        if not framed:
            await self._say(
                f"Candidate {cand.label}: the viewer could not frame or tint it — keeping it."
            )
            return "unsure", "viewer could not show the cluster — kept by default"
        cap = await self._dispatch("capture_frame", {})
        frames = cap.get("frames") or []
        if not frames:
            await self._say(
                f"Candidate {cand.label}: no frame came back from the viewer — keeping it."
            )
            return "unsure", "no captured view — kept by default"
        args = await self._ask(
            _JUDGE_INSTRUCTION.format(label=cand.label, count=cand.count, dist=cand.dist_from_core),
            "judge_candidate", frames[0],
        )
        if args is None:
            return "unsure", "model unavailable — kept by default"
        verdict = args.get("verdict")
        if verdict not in ("junk", "structure", "look_closer"):
            return "unsure", "unusable model reply — kept by default"
        return verdict, str(args.get("reason", ""))[:120]

    # ---- phase 5: batch proposal + bound execution ------------------------- #
    def _rows(self) -> list[dict]:
        return [{
            "label": c.label, "count": c.count,
            "verdict": self.verdicts.get(c.label, "unsure"),
            "reason": self.reasons.get(c.label, ""),
            "provenance": c.provenance,
        } for c in self.candidates]

    async def _phase5_batch(self) -> tuple[int, int, int]:
        """Returns (clusters_deleted, splats_deleted, clusters_skipped)."""
        junk = [c for c in self.candidates if self.verdicts.get(c.label) == "junk"]
        if not junk:
            await self._say("No clusters judged junk — nothing to delete.")
            return 0, 0, 0
        rounds = 0
        while True:
            total = sum(c.count for c in junk)
            kept = len(self.candidates) - len(junk)
            reply = await self._dispatch("propose_decision", {
                "kind": "delete_clusters",
                "summary": f"Delete {len(junk)} cluster{'s' if len(junk) != 1 else ''} "
                           f"({total:,} splats). Keeping {kept} judged structure/unsure.",
                "clusters": self._rows(),
            })
            verdict = (reply.get("result") or {}) if reply.get("ok") else {}
            v = verdict.get("verdict") if isinstance(verdict, dict) else None
            if v == "approved":
                return await self._execute_junk(junk)
            if v == "adjusted" and rounds < self.config.max_adjust_rounds:
                rounds += 1
                await self._apply_feedback(str(verdict.get("feedback", "")))
                junk = [c for c in self.candidates if self.verdicts.get(c.label) == "junk"]
                if not junk:
                    await self._say("After your adjustments nothing is marked junk.")
                    return 0, 0, 0
                continue
            await self._say("Batch rejected — keeping everything.")
            return 0, 0, 0

    async def _apply_feedback(self, feedback: str) -> None:
        labels = ", ".join(c.label for c in self.candidates)
        # _FEEDBACK_SPEC is controller-private (not a contract tool), so this
        # calls ask_forced directly rather than going through self._ask.
        args = await ask_forced(
            self.provider,
            f"Cluster labels: {labels}. Current verdicts: "
            + "; ".join(f"{k}={v}" for k, v in self.verdicts.items())
            + f'. Operator feedback: "{feedback}". Call apply_feedback with the flips.',
            _FEEDBACK_SPEC, None,
            timeout_s=self.config.call_timeout_s, retries=self.config.call_retries,
        )
        if not args:
            await self._say("Couldn't parse that feedback — showing the card again unchanged.")
            return
        for flip in args.get("flips", []):
            if not isinstance(flip, dict):
                continue
            label = str(flip.get("label", "")).upper()
            if label in self.verdicts:
                self.verdicts[label] = "structure" if flip.get("to") == "keep" else "junk"
                self.reasons[label] = f"operator: {feedback}"[:120]

    async def _execute_junk(self, junk: list[Cluster]) -> tuple[int, int, int]:
        alive_ids = set(int(i) for i in self._arrays()[2])
        deleted = splats = skipped = 0
        for c in junk:
            await self._checkpoint()
            ids = [int(i) for i in c.ids]
            if not all(i in alive_ids for i in ids):
                skipped += 1
                await self._say(
                    f"Cluster {c.label} changed since review — skipped (approval void for it)."
                )
                continue
            await self._dispatch("select_by_ids", {"ids": ids, "mode": "replace"})
            out = await self._guarded_edit("delete_selection", ids)
            if out["ok"]:
                deleted += 1
                splats += len(ids)
                alive_ids.difference_update(ids)
                await self._say(f"Deleted cluster {c.label} ({len(ids):,} splats).")
            else:
                skipped += 1
        await self._dispatch("clear_selection", {})
        # One resync for the whole batch (not per cluster — each reload refetches
        # the .ply): the operator watches the approved clusters actually vanish.
        if deleted:
            await self._resync_renderer()
        return deleted, splats, skipped

    # ---- phase 6: summary --------------------------------------------------- #
    async def _phases_4_to_6(self) -> str:
        if not self.candidates:
            answer = "Scene looks clean: no junk candidates found after the crop."
            await self._say(answer)
            return answer
        await self._phase4_tour()
        deleted, splats, skipped = await self._phase5_batch()
        kept = len(self.candidates) - deleted - skipped
        parts = [
            f"Cleanup done: {deleted} cluster{'s' if deleted != 1 else ''} "
            f"deleted ({splats:,} splats)"
        ]
        parts.append(f"{kept} kept")
        if skipped:
            parts.append(f"{skipped} skipped (changed or reverted)")
        if self.unresolved_marks:
            parts.append(f"{self.unresolved_marks} model mark(s) resolved to nothing")
        answer = ", ".join(parts) + "."
        await self._say(answer)
        return answer


__all__ = ["CleanupConfig", "CleanupController", "RunInterrupted"]
