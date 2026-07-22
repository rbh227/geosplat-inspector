"""The perceive -> act -> verify agent loop (§3, §4, §7).

Provider-agnostic: it holds a `ModelProvider` and a `ToolDispatcher` and never
knows which vendor or which side (backend/frontend) a tool runs on. Swapping
`MODEL_PROVIDER` changes nothing here.

Per step:
  1. provider.generate(messages, tools, images=pending_frames)  [perceive/think]
  2. emit `thought`; for each tool_call: emit `tool_call`, dispatch, emit
     `tool_result`, feed result back                              [act]
  3. after any destructive edit: re-measure + verify_edit; keep, or undo and
     loosen-retry (≤ max_retries_per_problem)                     [verify]
Stops on `answer()`, max_steps, or a surfaced RateLimitError. Vision calls are
budgeted and frames cached (R4/R5). The final answer is grounding-checked (§8).
"""

from __future__ import annotations

import asyncio
import json
import math
from typing import Any

from backend.contracts import FrontendChannel, ModelProvider, ToolCall
from backend.providers import RateLimitError

from .config import AgentConfig
from .dispatch import ToolDispatcher
from .grounding import GroundingError, GroundingLedger
from .system_prompt import Stage, build_tool_specs, stage_tools, system_prompt_for
from .types import (
    DESTRUCTIVE_TOOLS,
    VISION_TOOLS,
    LoopResult,
    ev_complete,
    ev_narrate,
    ev_thought,
    ev_tool_call,
    ev_tool_result,
)
from .verify import silhouette_intact, verify_edit


# Destructive spatial ops locked behind an operator-approved proposal (v0.5).
# One approval unlocks exactly one edit of the matching kind.
_APPROVAL_GATED: dict[str, str] = {
    "crop_bbox": "crop_outside_box",
    "crop_sphere": "crop_outside_box",
    "delete_selection": "delete_selection",
    "keep_selection": "delete_selection",
}


class AgentLoop:
    def __init__(
        self,
        provider: ModelProvider,
        dispatcher: ToolDispatcher,
        channel: FrontendChannel,
        config: AgentConfig | None = None,
        system_prompt: str | None = None,
        stage: Stage = "clean",
    ):
        self.provider = provider
        self.dispatcher = dispatcher
        self.channel = channel
        self.config = config or AgentConfig()
        self.stage = stage
        self.system_prompt = system_prompt if system_prompt is not None else system_prompt_for(stage)
        self.tools = build_tool_specs(stage)
        self._allowed_tools = stage_tools(stage)

        # per-run state (reset in run())
        self._messages: list[dict] = []
        self._pending_frames: list[bytes] = []
        self._ledger = GroundingLedger()
        self._last_metrics: dict | None = None
        self._result = LoopResult(status="init")
        # Banked operator approvals, per proposal kind (one approval = one edit).
        self._approvals: dict[str, int] = {}
        # Fix 2 (final review): approvals bind the REVIEWED artifact, not just the
        # kind. `_previewed_box` tracks the last box shown/adjusted via preview;
        # `_approved_box` is the box captured when a crop_outside_box approval was
        # banked, and it overrides whatever coordinates the model later passes.
        self._previewed_box: dict | None = None
        self._approved_box: dict | None = None

    # -- public -----------------------------------------------------------
    async def run(self, prompt: str) -> LoopResult:
        self._messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt},
        ]
        self._pending_frames = []
        self._ledger = GroundingLedger()
        self._last_metrics = None
        self._result = LoopResult(status="running")
        self._approvals = {}
        self._previewed_box = None
        self._approved_box = None

        await self._seed_grounding()

        for step in range(1, self.config.max_steps + 1):
            self._result.steps = step
            try:
                response = await asyncio.to_thread(
                    self.provider.generate,
                    self._messages,
                    self.tools,
                    self._pending_frames or None,
                )
            except RateLimitError as exc:
                return await self._finish_error("rate_limited", str(exc))
            except Exception as exc:  # noqa: BLE001
                return await self._finish_error("error", f"provider error: {exc}")

            self._pending_frames = []  # consumed by the call above

            if response.text:
                await self._emit(ev_thought(response.text, step))
                self._messages.append({"role": "assistant", "content": response.text})

            if not response.tool_calls:
                # Treat free-form text as an implicit answer attempt.
                if response.text:
                    done = await self._try_answer(response.text)
                    if done:
                        return self._result
                    continue
                await self._nudge("Use a tool, or call answer() to finish.")
                continue

            for call in response.tool_calls:
                returned = await self._handle_call(call, step)
                if returned:  # answer() fired
                    return self._result
                verdict = await self._pause_checkpoint()
                if verdict:
                    return await self._finish_status(verdict)

        return await self._finish_status("max_steps")

    # -- spatial grounding (real scenes are NOT at the origin) -------------
    async def _seed_grounding(self) -> None:
        """Inject the scene's real center / bbox / scale before the model acts.

        Test scenes sit at the origin at unit scale, so a model with no spatial
        context defaults every camera and selection coordinate to [0,0,0] and
        gets away with it. Real captures are centered thousands of units away
        with a huge extent — there, origin-relative aiming stares into empty
        space (blank frames) and origin-relative selection grabs the whole
        scene. We read the bounds the engine already computes (get_metrics) and
        hand the model the real coordinates. Best-effort: never abort a run.

        Reads a CHEAP bounds-only accessor (single min/max pass, no k-NN) rather
        than full get_metrics — the seed runs on every request (incl. look-only
        Understand), so it must never trigger the expensive metrics pass. The
        call is internal (no tool_call event, no ledger write), so it does not
        count as a model tool call — Understand stays look-only and the grounding
        ledger keeps policing only what the model itself measured.
        """
        get_bounds = getattr(getattr(self.dispatcher, "executor", None), "get_bounds", None)
        if not callable(get_bounds):
            return
        try:
            bounds = get_bounds()
        except Exception:  # noqa: BLE001 — grounding is optional, never fatal
            return
        if not isinstance(bounds, dict):
            return
        mn, mx = bounds.get("min"), bounds.get("max")
        if not (
            isinstance(mn, (list, tuple)) and isinstance(mx, (list, tuple))
            and len(mn) == 3 and len(mx) == 3
        ):
            return
        mn, mx = list(mn), list(mx)
        center = [round((a + b) / 2, 3) for a, b in zip(mn, mx)]
        radius = round(0.5 * math.dist(mn, mx), 3)
        msg = (
            "[scene] The loaded scene is NOT centered at the origin. Real world "
            "coordinates, for SELECTION and marker placement (navigate with the "
            "buttons — move_camera / turn / dolly — not coordinates):\n"
            f"- center: {center}\n"
            f"- bounding box: min {[round(v, 3) for v in mn]} max {[round(v, 3) for v in mx]}\n"
            f"- radius (half-diagonal): {radius}\n"
            "Selection spheres/boxes must sit inside the bounding box; a radius "
            "near the scene radius covers everything, so use a small fraction of "
            "it to target a region."
        )
        self._messages.insert(1, {"role": "user", "content": msg})

    # -- pause / takeover (KTD9, R14) --------------------------------------
    async def _pause_checkpoint(self) -> str | None:
        """Between tool calls: honor operator takeover. Pause is stateful and
        holds the loop until an explicit resume; interrupt aborts the run.
        Channels without pause support (mocks, stubs) fall through silently.
        """
        if getattr(self.channel, "interrupted", False):  # consume-once abort
            await self._emit(ev_narrate("Stopped by the operator."))
            return "interrupted"
        if getattr(self.channel, "paused", False):
            await self._emit(ev_narrate("Paused — the operator has control."))
            wait = getattr(self.channel, "wait_resume", None)
            if wait is not None:
                await wait()
            if getattr(self.channel, "interrupted", False):
                await self._emit(ev_narrate("Stopped by the operator."))
                return "interrupted"
            # the operator may have edited during the pause: re-measure so the
            # next verify compares against the real current state
            self._last_metrics = None
            await self._emit(ev_narrate("Resumed."))
        return None

    # -- per-call handling ------------------------------------------------
    async def _handle_call(self, call: ToolCall, step: int) -> bool:
        await self._emit(ev_tool_call(call.name, call.args, step))

        # Stage backstop (defense in depth, AE2): the spec filter already keeps
        # blocked tools out of the model's list, but a hallucinated call must
        # ALSO never reach the dispatcher in a look-only stage.
        if call.name != "answer" and call.name not in self._allowed_tools:
            rejection = {
                "ok": False,
                "error": f"{call.name} is not available in the {self.stage} stage"
                + (" — the operator must switch to Clean to edit" if self.stage == "understand" else ""),
            }
            await self._emit(ev_tool_result(call.name, rejection, step))
            self._feed_back(call.name, rejection)
            return False

        # Approval gate (v0.5): destructive spatial ops require a banked,
        # operator-approved proposal of the matching kind. One approval unlocks
        # exactly one edit. Only in the clean stage — understand rejected these
        # at the backstop above.
        if self.stage == "clean" and call.name in _APPROVAL_GATED:
            kind = _APPROVAL_GATED[call.name]
            if self._approvals.get(kind, 0) <= 0:
                rejection = {
                    "ok": False,
                    "error": f"{call.name} is locked: get an approved "
                             f"propose_decision(kind='{kind}') first — preview what "
                             "you intend to remove, then propose it to the operator",
                }
                await self._emit(ev_tool_result(call.name, rejection, step))
                self._feed_back(call.name, rejection)
                return False
            self._approvals[kind] -= 1

            # Fix 2: bind the reviewed artifact to the edit. When the operator
            # approved a crop_outside_box, the reviewed artifact is a specific
            # box — enforce it deterministically instead of trusting the model
            # to re-pass the same coordinates.
            #   crop_bbox  -> override min/max with the approved box.
            #   crop_sphere-> reject (the reviewed artifact is a box, not a
            #                 sphere) and refund the approval so a crop_bbox
            #                 retry can still consume it.
            # delete_selection/keep_selection bind no extra state here: the
            # selection is resolved to IDs as-of-now at dispatch time, so the
            # approval binds the COUNT the operator reviewed but not the exact
            # IDs (known looseness — full ID-binding is tracked follow-up work,
            # see the 2026-07-22 final review).
            if kind == "crop_outside_box" and self._approved_box is not None:
                if call.name == "crop_sphere":
                    self._approvals[kind] += 1  # refund: still spendable via crop_bbox
                    rejection = {
                        "ok": False,
                        "error": "the operator reviewed a box, not a sphere — "
                                 "call crop_bbox to crop to the approved box "
                                 "(crop_sphere is not bound to the reviewed artifact)",
                    }
                    await self._emit(ev_tool_result(call.name, rejection, step))
                    self._feed_back(call.name, rejection)
                    return False
                approved_min = self._approved_box["min"]
                approved_max = self._approved_box["max"]
                if call.args.get("min") != approved_min or call.args.get("max") != approved_max:
                    await self._emit(ev_narrate(
                        f"Cropping to the box the operator approved (min {approved_min}, "
                        f"max {approved_max}), overriding the model's requested box."
                    ))
                    call.args["min"] = approved_min
                    call.args["max"] = approved_max

        if call.name == "answer":
            return await self._try_answer(str(call.args.get("text", "")))

        if call.name in VISION_TOOLS:
            await self._handle_vision(call, step)
            return False

        if call.name in DESTRUCTIVE_TOOLS and self.config.verify_after_edit:
            await self._handle_destructive(call, step)
            return False

        result = await self.dispatcher.dispatch(call)

        # Bank an operator approval so the next matching edit can pass the gate.
        if call.name == "propose_decision" and result.get("ok"):
            payload = result.get("result")
            if isinstance(payload, dict) and payload.get("verdict") == "approved":
                kind = str(call.args.get("kind", ""))
                self._approvals[kind] = self._approvals.get(kind, 0) + 1
                # Fix 2: bind the box the operator actually reviewed to this
                # approval. propose_decision carries no box, so we snapshot the
                # last previewed box (show_box_preview / adjust_box_preview).
                if kind == "crop_outside_box":
                    self._approved_box = dict(self._previewed_box) if self._previewed_box else None

        await self._emit(ev_tool_result(call.name, result, step))
        self._absorb_result(call.name, result)
        self._feed_back(call.name, result)
        return False

    async def _handle_vision(self, call: ToolCall, step: int) -> None:
        if self._result.vision_calls >= self.config.max_vision_calls:
            note = {"ok": True, "skipped": "vision budget exhausted"}
            await self._emit(ev_tool_result(call.name, note, step))
            self._feed_back(call.name, note)
            return
        # Captures are ALWAYS fresh: a percept only means anything at the pose and
        # scene revision it was taken at (Codex boundary — capture freshness). The
        # old key-by-args cache served capture_frame (args={}) a stale first frame
        # forever, so the model never saw where it had moved.
        result = await self.dispatcher.dispatch(call)
        frames = result.get("frames", [])
        self._result.vision_calls += 1
        resp = result.get("result")
        percept = resp.get("percept") if isinstance(resp, dict) else None
        if frames:
            self._pending_frames.extend(frames)
            self._ledger.record_frame()
        await self._emit(ev_tool_result(call.name, {"n_frames": len(frames)}, step))
        note: dict[str, Any] = {"captured": len(frames)}
        if percept is not None:
            note["percept"] = percept  # where/when this frame was taken
        self._feed_back(call.name, note)

    async def _handle_destructive(self, call: ToolCall, step: int) -> None:
        before = await self._ensure_metrics()
        result = await self.dispatcher.dispatch(call)  # auto-snapshots + edits
        await self._emit(ev_tool_result(call.name, result, step))
        if not result.get("ok"):
            self._feed_back(call.name, result)
            return

        after = await self._measure()

        # Subject-loss guard: a single edit shouldn't destroy the dense subject
        # (judged by the SOLID, non-near-transparent core — not the raw total,
        # since on messy scenes the noise is often the majority). Cropping TO a
        # problem region (instead of removing the bad Gaussians inside it) keeps
        # the junk and wipes the object — and the per-tool metric still
        # "improves", so verify_edit alone would keep it. Revert and steer the
        # model toward targeted removal.
        if not silhouette_intact(before, after):
            undo_res = await self.dispatcher.dispatch(ToolCall("undo", {}))
            self._result.edits_reverted += 1
            self._last_metrics = before
            b, a = before["gaussianCount"], after["gaussianCount"]
            detail = f"{call.name} removed {b - a}/{b} Gaussians, destroying the subject's solid core"
            await self._emit(ev_narrate(f"Reverted {call.name}: {detail}"))
            await self._emit(ev_tool_result(f"verify:{call.name}", detail, step))
            await self._emit(ev_tool_result("undo", undo_res, step))
            self._feed_back(
                call.name,
                {
                    "kept": False,
                    "reverted": True,
                    "reason": detail,
                    "hint": "that deleted most of the scene. Target the bad "
                    "Gaussians with remove_outliers / opacity_threshold / "
                    "prune_oversized; do NOT crop to a problem region "
                    "(crop_bbox/crop_sphere KEEP what's inside and delete the rest).",
                },
            )
            return

        vr = verify_edit(call.name, before, after)
        await self._emit(ev_tool_result(f"verify:{call.name}", vr.detail, step))

        if vr.improved:
            self._result.edits_kept += 1
            self._last_metrics = after
            self._feed_back(
                call.name,
                {"kept": True, "verify": vr.detail, "counts": result.get("result")},
            )
        else:
            undo_res = await self.dispatcher.dispatch(ToolCall("undo", {}))
            self._result.edits_reverted += 1
            self._last_metrics = before
            await self._emit(ev_narrate(f"Reverted {call.name}: {vr.detail}"))
            await self._emit(ev_tool_result("undo", undo_res, step))
            self._feed_back(
                call.name,
                {
                    "kept": False,
                    "reverted": True,
                    "verify": vr.detail,
                    "hint": "loosen parameters and retry (≤2 per problem)",
                },
            )

    # -- answer / grounding ----------------------------------------------
    async def _try_answer(self, text: str) -> bool:
        if self.config.enforce_grounding:
            try:
                self._ledger.check(text)
            except GroundingError as exc:
                await self._emit(ev_tool_result("answer", {"ungrounded": str(exc)}, self._result.steps))
                self._nudge_sync(
                    f"Answer rejected (grounding): {exc}. "
                    "Measure or capture before asserting, then answer again."
                )
                return False
        self._result.status = "answered"
        self._result.answer = text
        await self._emit(ev_complete("answered", answer=text))
        return True

    # -- metrics helpers --------------------------------------------------
    async def _ensure_metrics(self) -> dict:
        if self._last_metrics is None:
            return await self._measure()
        return self._last_metrics

    async def _measure(self) -> dict:
        result = await self.dispatcher.dispatch(ToolCall("get_metrics", {}))
        metrics = result.get("result", {}) if result.get("ok") else {}
        if metrics:
            self._ledger.record_metrics(metrics)
            self._last_metrics = metrics
        return metrics

    # -- bookkeeping ------------------------------------------------------
    def _absorb_result(self, name: str, result: dict) -> None:
        if not result.get("ok"):
            return
        payload = result.get("result")
        if name == "get_metrics" and isinstance(payload, dict):
            self._ledger.record_metrics(payload)
            self._last_metrics = payload
        else:
            self._ledger.record_tool_result(payload)
        # Fix 2: remember the last previewed box so a later crop_outside_box
        # approval can bind it (both preview tools return {ok, min, max}).
        if name in ("show_box_preview", "adjust_box_preview") and isinstance(payload, dict):
            mn, mx = payload.get("min"), payload.get("max")
            if _is_vec3(mn) and _is_vec3(mx):
                self._previewed_box = {"min": [float(v) for v in mn], "max": [float(v) for v in mx]}

    def _feed_back(self, name: str, result: Any) -> None:
        self._messages.append(
            {"role": "user", "content": f"[tool_result {name}] {json.dumps(result, default=_safe)}"}
        )

    def _nudge_sync(self, text: str) -> None:
        self._messages.append({"role": "user", "content": f"[system] {text}"})

    async def _nudge(self, text: str) -> None:
        self._nudge_sync(text)

    async def _emit(self, event: dict) -> None:
        self._result.trace.append(event)
        await self.channel.emit_event(event)

    async def _finish_status(self, status: str) -> LoopResult:
        self._result.status = status
        await self._emit(ev_complete(status))
        return self._result

    async def _finish_error(self, status: str, error: str) -> LoopResult:
        self._result.status = status
        self._result.error = error
        await self._emit(ev_complete(status, error=error))
        return self._result


def _is_vec3(v: Any) -> bool:
    return (
        isinstance(v, (list, tuple))
        and len(v) == 3
        and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v)
    )


def _safe(obj: Any) -> str:
    if isinstance(obj, (bytes, bytearray)):
        return f"<{len(obj)} bytes>"
    return str(obj)


__all__ = ["AgentLoop"]
