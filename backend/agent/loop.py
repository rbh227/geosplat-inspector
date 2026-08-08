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
from .system_prompt import Stage, build_tool_specs, skills_for, stage_tools, system_prompt_for
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
    # Keep-only DELETES EVERYTHING ELSE — materially different consent than
    # deleting the selection, so it has its own kind (Codex adversarial review).
    "keep_selection": "keep_only_selection",
    # Statistical cleaners delete splats too — "every delete is reviewed"
    # (operator decision, 2026-07-22): one bulk_edit approval per sweep.
    "opacity_threshold": "bulk_edit",
    "remove_outliers": "bulk_edit",
    "prune_oversized": "bulk_edit",
    "remove_needles": "bulk_edit",
}

# The sweeps a bulk_edit proposal may name in its `operation` — a bulk approval
# authorizes exactly one named sweep with the reviewed parameters.
_BULK_SWEEPS: frozenset[str] = frozenset(
    {"opacity_threshold", "remove_outliers", "prune_oversized", "remove_needles"}
)

# Kinds whose reviewed artifact is the current selection (ID snapshot at
# approval; void if the selection changes before the edit).
_SELECTION_KINDS: frozenset[str] = frozenset({"delete_selection", "keep_only_selection"})

# Phrases that mark text as a PLAN rather than a result. Judged on the tail of
# the message: a report that ends by announcing the next move is a plan.
_INTENT_MARKERS = ("i'll ", "i will ", "let me ", "i'm going to ", "i am going to ", "now i ", "next i ")


def _looks_like_intent(text: str) -> bool:
    """True when text announces future work ("Let me now clean up:") instead of
    reporting done work — accepting it as an answer is how the agent 'says it
    will do something and then just stops'."""
    t = (text or "").strip().lower()
    if t.endswith(":"):
        return True
    # "let me know ..." is a closing courtesy, not a plan — without this a
    # perfectly good final answer gets bounced (and could falsely stall).
    t = t.replace("let me know", "")
    return any(m in t[-200:] for m in _INTENT_MARKERS)


# Consecutive plan-without-action events (plan-shaped answer() calls or
# text-only planning turns) before the run ends as honestly stalled. Any real
# tool call resets the count. A plan must NEVER be accepted as the result —
# ending with "Let me capture another frame:" reads as the agent giving up
# mid-thought, and the operator can't even tell the run is over.
_MAX_PLAN_STALLS = 4
_STALL_MSG = (
    "the model kept announcing plans ('Let me…') without executing them, "
    "instead of calling tools. Send the request again, rephrase it, or "
    "configure a stronger model in Settings."
)


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
        # Models routinely call skill NAMES as if they were tools (the prompt
        # lists them right next to the tools). Map name -> recipe so that
        # mistake gets answered with the actual steps, not a cryptic rejection.
        self._skill_recipes = {s["name"]: s["recipe"] for s in skills_for(stage)}

        # per-run state (reset in run())
        self._messages: list[dict] = []
        self._pending_frames: list[bytes] = []
        self._textonly_streak = 0  # consecutive no-tool text turns
        self._plan_rejections = 0  # answers bounced for being plans, per run
        self._last_narrate = ""    # normalized last narration (repeat guard)
        # Understand-stage survey (spec 2026-08-03): frames the app captured
        # for this run; attached to EVERY model call so the model can always
        # look again. survey_out is what the caller persists per scene.
        self._survey_frames: list[bytes] = []
        self.survey_out: dict | None = None
        self._ledger = GroundingLedger()
        self._last_metrics: dict | None = None
        self._result = LoopResult(status="init")
        # Banked operator approvals, per proposal kind (one approval = one edit).
        self._approvals: dict[str, int] = {}
        # Approvals bind the REVIEWED OPERATION, not just a kind (final review
        # Fix 2 + Codex adversarial review): `_previewed_box` tracks the last box
        # shown/adjusted via preview; the `_approved_*` fields hold the exact
        # artifact the operator reviewed, captured at approval-banking time.
        # Approvals that would bind nothing (no preview, no named sweep, empty
        # selection) are REFUSED at banking, so the enforcement branch can rely
        # on the artifact being present.
        self._previewed_box: dict | None = None
        self._approved_box: dict | None = None
        self._approved_sweep: dict | None = None      # {"tool": str, "params": dict}
        self._approved_ids: frozenset[int] | None = None

    # -- public -----------------------------------------------------------
    async def run(
        self,
        prompt: str,
        history: list[dict] | None = None,
        ledger: GroundingLedger | None = None,
        survey: dict | None = None,
    ) -> LoopResult:
        """One agent run. `history` is the prior conversation for this scene
        (from `transcript()` of an earlier run) so follow-ups have context —
        without it every request starts amnesiac. `ledger` carries the prior
        runs' grounding evidence for the same reason: what the agent measured
        or saw earlier in the conversation still backs its answers now.
        `survey` is the previous Understand run's app-owned survey
        ({"frames", "labels", "revision"}) — reused when the scene revision is
        unchanged so follow-ups answer instantly from the same views.
        """
        try:
            return await self._run_inner(prompt, history, ledger, survey)
        except asyncio.CancelledError:
            # Hard stop: ws.py cancels the run task on user_interrupt, so Stop
            # works even mid-await (a slow/dead model call, a wedged frontend
            # command). Swallowing the cancellation is deliberate — the stop
            # is consumed by finishing the run.
            return await self._finish_status("interrupted")

    async def _run_inner(
        self,
        prompt: str,
        history: list[dict] | None = None,
        ledger: GroundingLedger | None = None,
        survey: dict | None = None,
    ) -> LoopResult:
        self._messages = []
        if self.system_prompt:
            self._messages.append({"role": "system", "content": self.system_prompt})
        if history:
            self._messages.extend(dict(m) for m in history)
        self._messages.append({"role": "user", "content": prompt})
        self._pending_frames = []
        self._textonly_streak = 0
        self._plan_rejections = 0
        self._last_narrate = ""
        self._ledger = ledger if ledger is not None else GroundingLedger()
        self._last_metrics = None
        self._result = LoopResult(status="running")
        self._approvals = {}
        self._previewed_box = None
        self._approved_box = None
        self._approved_sweep = None
        self._approved_ids = None
        if hasattr(self.dispatcher, "edits_applied"):
            self.dispatcher.edits_applied = 0
        self._survey_frames = []
        self.survey_out = None

        await self._seed_grounding()

        # App-owned survey (Understand stage, spec 2026-08-03): the app flies
        # the camera and captures the views BEFORE the model's first turn.
        if self.stage == "understand":
            if not await self._run_survey(survey):
                return self._result  # finished with an error already

        for step in range(1, self.config.max_steps + 1):
            self._result.steps = step
            if step == self.config.max_steps:
                # Land the plane: a run that dies at max_steps mid-motion reads
                # as an unexplained stop. Spend the final turn on a summary.
                self._nudge_sync(
                    "FINAL step — your budget is exhausted. Call answer(text=...) "
                    "NOW with a grounded summary of what you did and found. "
                    "No other tool."
                )
            try:
                response = await asyncio.to_thread(
                    self.provider.generate,
                    self._messages,
                    self.tools,
                    ([*self._survey_frames, *self._pending_frames] or None),
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
                if response.text:
                    # Narrated intent ("I'll turn right...") with no tool call
                    # used to complete the run as an implicit answer — the agent
                    # announced a plan and then just stopped. Nudge it to act;
                    # only a SECOND consecutive text-only turn that reads as a
                    # RESULT (not another plan) is accepted as the answer.
                    self._textonly_streak += 1
                    if _looks_like_intent(response.text):
                        self._plan_rejections += 1
                        if self._plan_rejections >= _MAX_PLAN_STALLS:
                            return await self._finish_error("stalled", _STALL_MSG)
                    elif self._textonly_streak >= 2:
                        done = await self._try_answer(response.text)
                        if done:
                            return self._result
                        continue
                    self._nudge_sync(
                        "You said what you would do but executed nothing — "
                        "actions only happen through tool calls. Call the tool "
                        "you just described NOW, or call answer(text=...) if "
                        "you are finished."
                    )
                    continue
                await self._nudge("Use a tool, or call answer() to finish.")
                continue

            self._textonly_streak = 0
            calls = list(response.tool_calls)
            for idx, call in enumerate(calls):
                # Honor Stop/Pause BEFORE the action, not one action late.
                verdict = await self._pause_checkpoint()
                if verdict:
                    return await self._finish_status(verdict)
                returned = await self._handle_call(call, step)
                if returned:  # answer() fired
                    return self._result
                # Perception barrier: anything queued after a capture in this
                # same response would execute before the model ever sees the
                # frame. Drop the tail and tell the model why.
                if call.name in VISION_TOOLS and idx < len(calls) - 1 and self._pending_frames:
                    dropped = [c.name for c in calls[idx + 1:]]
                    self._nudge_sync(
                        f"capture taken — dropped {len(dropped)} queued action(s) "
                        f"({', '.join(dropped)}): look at the frame before acting again."
                    )
                    break
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
        pos = 1 if self._messages and self._messages[0].get("role") == "system" else 0
        self._messages.insert(pos, {"role": "user", "content": msg})

    # -- app-owned survey (Understand stage; spec 2026-08-03) ---------------
    async def _run_survey(self, stored: dict | None) -> bool:
        """Dispatch survey_capture app-side and attach the frames for the
        whole run. Returns False after finishing the run with an error."""
        args: dict = {}
        if stored and stored.get("revision") is not None and stored.get("frames"):
            args["if_revision_not"] = stored["revision"]
        await self._emit(ev_tool_call("survey_capture", args, 0))
        result = await self.dispatcher.dispatch(ToolCall("survey_capture", args))
        payload = result.get("result") if isinstance(result.get("result"), dict) else {}
        frames = result.get("frames") or []

        if result.get("ok") and payload.get("unchanged") and stored:
            frames = list(stored["frames"])
            labels = [str(x) for x in (stored.get("labels") or [])]
            revision = stored.get("revision")
        elif result.get("ok") and frames:
            labels = [str(x) for x in (payload.get("labels") or [])]
            revision = payload.get("revision")
        elif stored and stored.get("frames"):
            # Re-survey failed (viewer busy/gone) but we still hold an older
            # survey of this scene — answer from it rather than dying.
            frames = list(stored["frames"])
            labels = [str(x) for x in (stored.get("labels") or [])]
            revision = stored.get("revision")
        else:
            await self._emit(ev_tool_result("survey_capture", result, 0))
            await self._finish_error(
                "error",
                "survey failed: could not capture the scene — check that a "
                "scene is loaded and the viewer is connected, then ask again.",
            )
            return False

        await self._emit(ev_tool_result("survey_capture", {"n_frames": len(frames)}, 0))
        self._survey_frames = frames
        self.survey_out = {"frames": frames, "labels": labels, "revision": revision}
        self._ledger.record_frame()
        lines = [
            f"View {i + 1}: {labels[i] if i < len(labels) else 'additional view'}"
            for i in range(len(frames))
        ]
        self._nudge_sync(
            "the app surveyed the scene; the attached images are, in order: "
            + "; ".join(lines)
            + ". Answer the operator's question from these views."
        )
        return True

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

        # Any real tool call is progress — only CONSECUTIVE planning stalls.
        # (answer() is excluded: a plan-shaped answer is itself a stall event.
        # narrate() too: talking is not acting, and a forced-tool-choice model
        # uses narrate as its prose outlet.)
        if call.name not in ("answer", "narrate"):
            self._plan_rejections = 0

        # Narrate-loop guard (observed live): the model repeats the same
        # narration turn after turn instead of acting. A repeat is a stall
        # event and is NOT delivered to the operator again.
        if call.name == "narrate":
            key = " ".join(str(call.args.get("text", "")).lower().split())[:60]
            if key and key == self._last_narrate:
                self._plan_rejections += 1
                if self._plan_rejections >= _MAX_PLAN_STALLS:
                    await self._finish_error("stalled", _STALL_MSG)
                    return True
                rejection = {
                    "ok": False,
                    "error": "you already said exactly that — no more narration; "
                             "call an ACTION tool now, or answer(text=...) to finish",
                }
                await self._emit(ev_tool_result(call.name, rejection, step))
                self._feed_back(call.name, rejection)
                return False
            self._last_narrate = key

        # A skill name is a recipe, not a tool: execute nothing, hand back the
        # steps so the model spends its next turn on real tool calls.
        if call.name in self._skill_recipes and call.name not in self._allowed_tools:
            rejection = {
                "ok": False,
                "error": f"{call.name} is a routine, not a tool — nothing ran. "
                         f"Execute its recipe with real tool calls: "
                         f"{self._skill_recipes[call.name]}",
            }
            await self._emit(ev_tool_result(call.name, rejection, step))
            self._feed_back(call.name, rejection)
            return False

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
            # Bind the reviewed OPERATION to the edit (Codex adversarial review):
            # an approval authorizes exactly the artifact the operator saw, never
            # a category. Checks run BEFORE the approval is consumed, so a
            # mismatched call leaves it intact for the correct retry; consuming
            # clears the bound artifact (one approval = one edit).
            if kind == "crop_outside_box":
                # Banking refuses box approvals without a preview, so the box is set.
                if call.name == "crop_sphere":
                    rejection = {
                        "ok": False,
                        "error": "the operator reviewed a box, not a sphere — "
                                 "call crop_bbox to crop to the approved box "
                                 "(crop_sphere is not bound to the reviewed artifact)",
                    }
                    await self._emit(ev_tool_result(call.name, rejection, step))
                    self._feed_back(call.name, rejection)
                    return False
                approved_min = self._approved_box["min"] if self._approved_box else None
                approved_max = self._approved_box["max"] if self._approved_box else None
                if approved_min is None or approved_max is None:
                    # Defensive: should be unreachable (banking requires a preview).
                    rejection = {"ok": False, "error": "no reviewed box on record — propose_decision again after show_box_preview"}
                    await self._emit(ev_tool_result(call.name, rejection, step))
                    self._feed_back(call.name, rejection)
                    return False
                if call.args.get("min") != approved_min or call.args.get("max") != approved_max:
                    await self._emit(ev_narrate(
                        f"Cropping to the box the operator approved (min {approved_min}, "
                        f"max {approved_max}), overriding the model's requested box."
                    ))
                call.args["min"] = approved_min
                call.args["max"] = approved_max
                self._approvals[kind] -= 1
                self._approved_box = None
            elif kind == "bulk_edit":
                sweep = self._approved_sweep or {}
                if call.name != sweep.get("tool"):
                    rejection = {
                        "ok": False,
                        "error": f"the operator approved the sweep "
                                 f"'{sweep.get('tool')}' — call that tool, or "
                                 f"propose_decision(kind='bulk_edit') again naming {call.name}",
                    }
                    await self._emit(ev_tool_result(call.name, rejection, step))
                    self._feed_back(call.name, rejection)
                    return False
                approved_params = dict(sweep.get("params") or {})
                if dict(call.args) != approved_params:
                    await self._emit(ev_narrate(
                        f"Running {call.name} with the parameters the operator approved "
                        f"({approved_params}), overriding the model's requested parameters."
                    ))
                call.args.clear()
                call.args.update(approved_params)
                self._approvals[kind] -= 1
                self._approved_sweep = None
            elif kind in _SELECTION_KINDS:
                current = await self._pull_selection_ids()
                if current is None or current != self._approved_ids:
                    # The reviewed selection is gone — the approval reviews nothing
                    # anymore. Drop it and make the model re-propose.
                    self._approvals[kind] -= 1
                    self._approved_ids = None
                    rejection = {
                        "ok": False,
                        "error": "the selection changed since the operator approved it — "
                                 "the approval is void. Re-select (or leave the tinted "
                                 "selection untouched) and propose_decision again",
                    }
                    await self._emit(ev_tool_result(call.name, rejection, step))
                    self._feed_back(call.name, rejection)
                    return False
                self._approvals[kind] -= 1
                self._approved_ids = None
            else:
                self._approvals[kind] -= 1

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
        # Banking REFUSES approvals that would bind no reviewed artifact (Codex
        # adversarial review) — an unbound approval would let arbitrary edits
        # through the gate.
        if call.name == "propose_decision" and result.get("ok"):
            payload = result.get("result")
            if isinstance(payload, dict) and payload.get("verdict") == "approved":
                kind = str(call.args.get("kind", ""))
                refusal = await self._bank_approval(kind, call.args, payload)
                if refusal:
                    self._nudge_sync(refusal)

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
        # An approval-gated tool that reached dispatch had its banked, bound
        # approval consumed above — the operator reviewed THIS operation, so the
        # guard relaxes to its catastrophic floor (see verify.silhouette_intact).
        approved = self.stage == "clean" and call.name in _APPROVAL_GATED
        if not silhouette_intact(before, after, approved=approved):
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
        # An empty answer is always a defect upstream (typically truncated
        # tool-call JSON) — completing with a blank chat bubble helps no one.
        if not text.strip():
            self._nudge_sync(
                "answer() arrived with empty text — call it again with the "
                "full result text."
            )
            return False
        # A plan is NEVER the answer: "Let me now clean up the floaters:" would
        # end the run with the work undone and read like the agent gave up
        # mid-thought. Bounce it; a model that does nothing BUT plan ends the
        # run as honestly stalled instead (visible error, not a fake result).
        if _looks_like_intent(text):
            self._plan_rejections += 1
            if self._plan_rejections >= _MAX_PLAN_STALLS:
                await self._finish_error("stalled", _STALL_MSG)
                return True
            await self._emit(ev_tool_result("answer", {"rejected": "reads like a plan, not a result"}, self._result.steps))
            self._nudge_sync(
                "That reads like a plan ('let me / I'll ...'), not a final answer. "
                "answer() ENDS the run — call it only with the finished result. "
                "Execute the plan NOW by calling the tool you named; to talk "
                "while working, use narrate()."
            )
            return False
        # v0.6: the old "look before you assert" bounce (answering without a
        # captured frame) is gone — in the Understand stage the app-owned
        # survey guarantees frames before the model's first turn, or the run
        # has already ended in an error.
        # A clarifying QUESTION asserts nothing and the prompt explicitly
        # invites one — exempt it from the must-have-measured rule, which
        # otherwise rejects "which cluster do you mean?" on the first turn.
        if self.config.enforce_grounding and not text.rstrip().endswith("?"):
            try:
                self._ledger.check(text)
            except GroundingError as exc:
                await self._emit(ev_tool_result("answer", {"ungrounded": str(exc)}, self._result.steps))
                self._nudge_sync(
                    f"Answer rejected (grounding): {exc}. "
                    "Measure or capture before asserting, then answer again."
                )
                return False
        # Record the answer in the conversation — it's the part of a run a
        # follow-up most needs to see. (The implicit text-only path already
        # appended it as the assistant turn; don't duplicate.)
        last = self._messages[-1] if self._messages else None
        if not (last and last.get("role") == "assistant" and last.get("content") == text):
            self._messages.append({"role": "assistant", "content": text})
        self._result.status = "answered"
        self._result.answer = text
        await self._emit(ev_complete("answered", answer=text, scene_changed=self._scene_changed()))
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

    # -- approval banking (v0.5) ------------------------------------------
    async def _bank_approval(
        self, kind: str, args: dict, decision: dict | None = None
    ) -> str | None:
        """Bank an approved proposal, capturing the reviewed artifact.

        Returns a refusal message (and banks nothing) when the approval would
        bind no artifact — the gate must never be passable by an approval the
        operator couldn't have meaningfully reviewed.
        """
        if kind == "crop_outside_box":
            # v0.6: the operator can move/resize the box before approving, and
            # the reply carries what they finally looked at. Prefer it over the
            # agent's preview — the approval must bind the reviewed artifact,
            # and the reviewed artifact is theirs.
            operator_box = (decision or {}).get("box")
            if (
                isinstance(operator_box, dict)
                and _is_vec3(operator_box.get("min"))
                and _is_vec3(operator_box.get("max"))
            ):
                self._approved_box = {
                    "min": [float(v) for v in operator_box["min"]],
                    "max": [float(v) for v in operator_box["max"]],
                }
            elif self._previewed_box is None:
                return (
                    "[system] approval not banked: no box was previewed. Call "
                    "show_box_preview, verify with a capture, then propose again."
                )
            else:
                self._approved_box = dict(self._previewed_box)
        elif kind == "bulk_edit":
            op = args.get("operation")
            tool = op.get("tool") if isinstance(op, dict) else None
            if tool not in _BULK_SWEEPS:
                return (
                    "[system] approval not banked: bulk_edit proposals must name "
                    "the exact sweep — propose_decision(kind='bulk_edit', "
                    "operation={'tool': <sweep>, 'params': {...}}) where <sweep> "
                    f"is one of {sorted(_BULK_SWEEPS)}."
                )
            self._approved_sweep = {"tool": tool, "params": dict(op.get("params") or {})}
        elif kind in _SELECTION_KINDS:
            ids = await self._pull_selection_ids()
            if not ids:
                return (
                    "[system] approval not banked: the selection is empty. Select "
                    "the splats first (they tint), then propose again."
                )
            self._approved_ids = ids
        self._approvals[kind] = self._approvals.get(kind, 0) + 1
        return None

    async def _pull_selection_ids(self) -> frozenset[int] | None:
        """Current selection as stable IDs, pulled over the channel. None on
        failure or when nothing is selected."""
        try:
            pulled = await self.channel.send_command({"type": "get_selection", "args": {}})
        except Exception:  # noqa: BLE001 — renderer gone; caller treats as no selection
            return None
        ids = pulled.get("ids") if isinstance(pulled, dict) else None
        if not ids:
            return None
        return frozenset(int(i) for i in ids)

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

    def _scene_changed(self) -> bool:
        return getattr(self.dispatcher, "edits_applied", 0) > 0

    @property
    def ledger(self) -> GroundingLedger:
        """The run's grounding evidence — persist it next to the transcript so
        follow-up runs may assert what earlier runs measured/saw."""
        return self._ledger

    def transcript(self) -> list[dict]:
        """The conversation to carry into the next run: everything except the
        system prompt and the per-run [scene] grounding seed (both are
        re-injected fresh each run)."""
        out: list[dict] = []
        for m in self._messages:
            if m.get("role") == "system":
                continue
            content = m.get("content")
            if isinstance(content, str) and content.startswith("[scene]"):
                continue
            out.append(m)
        return out

    async def _finish_status(self, status: str) -> LoopResult:
        self._result.status = status
        await self._emit(ev_complete(status, scene_changed=self._scene_changed()))
        return self._result

    async def _finish_error(self, status: str, error: str) -> LoopResult:
        self._result.status = status
        self._result.error = error
        await self._emit(ev_complete(status, error=error, scene_changed=self._scene_changed()))
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
