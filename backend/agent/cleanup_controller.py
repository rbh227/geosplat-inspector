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
            await self._say(f"Reverted {fn_name}: it would have destroyed the subject's core.")
            return {"ok": False, "reverted": True, "result": result}
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
            await self._emit(ev_complete("answered", answer=answer, scene_changed=True))
        except RunInterrupted:
            result.status = "interrupted"
            await self._emit(ev_complete("interrupted"))
        except Exception as exc:  # noqa: BLE001 — a controller bug must still end the run
            result.status = "error"
            result.error = str(exc)
            await self._emit(ev_complete("error", error=str(exc)))
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

    # ---- phases 4-6 (judgment tour, batch proposal, summary) --------------- #
    async def _phases_4_to_6(self) -> str:
        # Implemented in the next task; the stub keeps phases 1-3 runnable.
        return f"Cleanup survey complete: {len(self.candidates)} candidates."


__all__ = ["CleanupConfig", "CleanupController", "RunInterrupted"]
