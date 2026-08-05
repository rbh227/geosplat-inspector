"""App-owned judgment-tour cleanup (spec 2026-08-04-judgment-tour-cleanup).

A Python phase machine replaces the freeform loop for cleanup runs. The model
is consulted ONLY through ask_forced(): grid marks in phase 2, verdicts in
phase 4, feedback flips in phase 5. Everything spatial and procedural is code.

Phases: 1 crop -> 2 survey & mark -> 3 lock-in -> 4 tour -> 5 batch proposal
-> 6 summary. Every phase boundary checks interrupt/pause; every model failure
degrades one datum to a safe default (unsure = keep). The run always reaches
the summary.
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
from backend.contracts import FrontendChannel, ModelProvider, ToolCall
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


_MARK_INSTRUCTION = (
    "This is one view of a 3D-scanned scene with a {grid}x{grid} labeled grid "
    "(columns A-D left to right, rows 1-4 top to bottom). Call mark_noise with "
    "the cells that contain floating junk, debris mist, or fragments "
    "disconnected from the main structure. Use [] if this view looks clean."
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
        return await ask_forced(
            self.provider, instruction, CONTROLLER_CHOICE_SPECS[spec_name], image,
            timeout_s=self.config.call_timeout_s, retries=self.config.call_retries,
        )

    def _scene_changed(self) -> bool:
        return self._edits_applied > 0

    def _arrays(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        a = self.splat_arrays()
        return np.asarray(a["means"]), np.asarray(a["opacity"]), np.asarray(a["ids"])

    # ---- destructive edit with the standard guard ------------------------ #
    async def _guarded_edit(self, fn_name: str, *args) -> dict:
        """snapshot -> edit -> silhouette check (approved=True: the operator
        reviewed this exact operation) -> undo on catastrophe."""
        before = await asyncio.to_thread(self.executor.get_metrics)
        await asyncio.to_thread(self.executor.snapshot)
        result = await asyncio.to_thread(getattr(self.executor, fn_name), *args)
        after = await asyncio.to_thread(self.executor.get_metrics)
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
            await self._phase1_crop()
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
        except Exception as exc:  # noqa: BLE001 — a controller bug must still end the run
            result.status = "error"
            result.error = str(exc)
            await self._emit(ev_complete(
                "error", error=str(exc), scene_changed=self._scene_changed(),
            ))
        result.steps = self._step
        return result

    # ---- phase 1: crop ---------------------------------------------------- #
    async def _phase1_crop(self) -> None:
        means, _, _ = self._arrays()
        mn, mx = core_box(means)
        box_min = [float(v) for v in mn]
        box_max = [float(v) for v in mx]
        await self._say(
            "Proposing a crop to the dense core — adjust the box or reject to skip cropping."
        )
        await self._dispatch("show_box_preview", {"min": box_min, "max": box_max})
        reply = await self._dispatch("propose_decision", {
            "kind": "crop_outside_box",
            "summary": "Crop away everything outside the highlighted core box. "
                       "Drag the box to adjust before approving.",
        })
        verdict = (reply.get("result") or {}) if reply.get("ok") else {}
        if isinstance(verdict, dict) and verdict.get("verdict") == "approved":
            box = verdict.get("box") or {"min": box_min, "max": box_max}
            out = await self._guarded_edit("crop_bbox", box["min"], box["max"])
            if out["ok"]:
                self.crop_result = out["result"]
                await self._say("Crop applied.")
        else:
            await self._say("Crop skipped — moving on to the noise survey.")

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
