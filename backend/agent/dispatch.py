"""Tool dispatch with `runs_on` routing (ARCHITECTURE.md §4.1, §6.5).

The agent loop calls tools uniformly; the dispatcher decides where each runs:

  - runs_on == "backend":  call the analysis/editing engine directly (instant,
    local numpy). Destructive tools auto-`snapshot()` first (§6.5, §3.3).
  - runs_on == "frontend": send a command over the `FrontendChannel` and AWAIT
    the result — including captured PNG frames for vision.

The backend engine is reached through the local `BackendExecutor` Protocol
below: the exact set of methods this dispatcher needs from Agent 2's engine +
Agent 1's history. We develop against a mock implementing it (mocks.py) and
bind the real engine at integration — no contract or loop change required.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol, runtime_checkable

from backend.contracts import FrontendChannel, ToolCall
from backend.contracts.tools import TOOL_BY_NAME

from .types import DESTRUCTIVE_TOOLS, VISION_TOOLS


@runtime_checkable
class BackendExecutor(Protocol):
    """Methods the dispatcher invokes for backend (`runs_on="backend"`) tools.

    Implemented by Agent 2's engine (+ Agent 1's history) at integration;
    mirrored by MockBackendExecutor for offline development. Names match the
    tool contract exactly so dispatch is a direct method lookup.
    """

    # analysis
    def get_metrics(self, region: dict | None = None) -> dict: ...
    def list_problem_regions(self) -> list[dict]: ...
    # cheap axis-aligned scene bounds (min/max only, no k-NN) — used by the
    # loop's internal spatial-grounding seed so it never pays for full metrics.
    def get_bounds(self) -> dict: ...
    # editing (each returns before/after counts)
    def opacity_threshold(self, min_alpha: float) -> dict: ...
    def remove_outliers(self, k: int, std_ratio: float) -> dict: ...
    def prune_oversized(self, max_axis_scene_frac: float) -> dict: ...
    def remove_needles(self, max_axis_ratio: float) -> dict: ...
    def crop_bbox(self, min: list[float], max: list[float]) -> dict: ...
    def crop_sphere(self, center: list[float], radius: float, invert: bool = False) -> dict: ...
    def recolor(self, selection: dict, rgb: list[float]) -> dict: ...
    def adjust_opacity(self, selection: dict, factor: float) -> dict: ...
    def truncate_sh(self, degree: int) -> dict: ...
    # selection editing (v0.2) — ids pulled from the frontend at dispatch time
    def delete_selection(self, ids: list[int]) -> dict: ...
    def keep_selection(self, ids: list[int]) -> dict: ...
    # history
    def snapshot(self) -> None: ...
    def undo(self) -> dict: ...
    def redo(self) -> dict: ...
    def export_ply(self) -> str: ...


# Frontend tool name -> WS command `type` (§6.8 vocabulary).
_FRONTEND_CMD_TYPE: dict[str, str] = {
    "look_at": "camera_move",
    "set_view": "camera_move",
    "orbit": "camera_move",
    "dolly": "camera_move",
    "scan_pause": "camera_move",
    "frame_object": "camera_move",
    "reset_view": "camera_move",
    "reframe": "camera_move",
    "reset_trail": "camera_move",
    "capture_frame": "capture_request",
    "capture_orbit": "capture_request",
    "drop_marker": "drop_marker",
    "clear_markers": "clear_markers",
    "narrate": "narrate",
    # v0.2 — editor tools ride the shared visible action layer
    "select_by_brush": "selection_tool",
    "select_by_lasso": "selection_tool",
    "select_by_polygon": "selection_tool",
    "select_by_sphere": "selection_tool",
    "select_by_box": "selection_tool",
    "invert_selection": "selection_tool",
    "clear_selection": "selection_tool",
    "get_selection_state": "selection_tool",
    "move_camera": "movement_input",
    "turn": "rotation_input",
    # v0.5 — proposal / good-cube
    "get_core_bounds": "selection_tool",
    "show_box_preview": "selection_tool",
    "adjust_box_preview": "selection_tool",
    "propose_decision": "proposal",
}

# Backend tools that operate on the CURRENT frontend selection: dispatch pulls
# the stable splat IDs over the channel first (get_selection), then hands them
# to the editing engine. The model never sees or forwards raw ID arrays.
_SELECTION_EDIT_TOOLS = frozenset({"delete_selection", "keep_selection"})

# Tools whose success means the served scene differs from what the renderer
# has loaded: destructive edits plus history restores. Drives the `complete`
# event's scene_changed flag (the frontend gates its reload on it).
_SCENE_MUTATORS = DESTRUCTIVE_TOOLS | frozenset({"undo", "redo"})


class ToolDispatcher:
    def __init__(self, executor: BackendExecutor, channel: FrontendChannel):
        self.executor = executor
        self.channel = channel
        self.snapshots_taken = 0
        self.edits_applied = 0

    async def dispatch(self, call: ToolCall) -> dict:
        """Execute one tool call. Returns a normalized envelope:

            {"ok": bool, "name": str, "result": Any,
             "frames": list[bytes]?, "error": str?, "snapshotted": bool}
        """
        entry = TOOL_BY_NAME.get(call.name)
        if entry is None:
            return {"ok": False, "name": call.name, "error": f"unknown tool {call.name!r}"}

        if entry.runs_on == "backend":
            return await self._dispatch_backend(call)
        return await self._dispatch_frontend(call)

    # -- backend ----------------------------------------------------------
    async def _dispatch_backend(self, call: ToolCall) -> dict:
        args = dict(call.args)

        # Selection edits: resolve the frontend's current selection to stable
        # IDs before touching the engine (KTD2 — one shared edit path).
        if call.name in _SELECTION_EDIT_TOOLS:
            try:
                pulled = await self.channel.send_command({"type": "get_selection", "args": {}})
            except Exception as exc:  # noqa: BLE001 - renderer gone / timeout
                return {"ok": False, "name": call.name, "error": f"selection pull failed: {exc}"}
            ids = pulled.get("ids") if isinstance(pulled, dict) else None
            if not ids:
                return {
                    "ok": False,
                    "name": call.name,
                    "error": "selection is empty — use a select_by_* tool first",
                }
            args = {"ids": ids}

        snapshotted = False
        if call.name in DESTRUCTIVE_TOOLS:
            # snapshot() copies the whole model — threads, like every executor
            # call below: heavy numpy on a multi-million-splat scene run inline
            # would FREEZE the event loop (no WS events, no HTTP, dead pings)
            # for its whole duration. The server must stay responsive while the
            # engine grinds.
            await asyncio.to_thread(self.executor.snapshot)
            self.snapshots_taken += 1
            snapshotted = True

        method = getattr(self.executor, call.name, None)
        if method is None:
            return {"ok": False, "name": call.name, "error": f"executor missing {call.name}"}
        try:
            result = await asyncio.to_thread(method, **args)
        except TypeError as exc:
            return {"ok": False, "name": call.name, "error": f"bad args: {exc}"}
        except Exception as exc:  # noqa: BLE001 - surface engine errors to the loop
            return {"ok": False, "name": call.name, "error": str(exc)}
        if call.name in _SCENE_MUTATORS:
            self.edits_applied += 1
        return {"ok": True, "name": call.name, "result": result, "snapshotted": snapshotted}

    # -- frontend ---------------------------------------------------------
    async def _dispatch_frontend(self, call: ToolCall) -> dict:
        cmd = {
            "type": _FRONTEND_CMD_TYPE.get(call.name, "camera_move"),
            "tool": call.name,
            "args": call.args,
        }
        resp = await self.channel.send_command(cmd)
        out: dict[str, Any] = {"ok": True, "name": call.name, "result": resp}
        if call.name in VISION_TOOLS:
            out["frames"] = _extract_frames(resp)
        return out


def _extract_frames(resp: dict) -> list[bytes]:
    """Pull PNG bytes out of a capture response (single or orbit).

    `ws.py` decodes the frontend's base64 reply into `frames: list[bytes]`
    (and `png: bytes` for a single capture). Accept those, plus the legacy
    `frame` key, so the loop always receives raw bytes for the model.
    """
    if not isinstance(resp, dict):
        return []
    if isinstance(resp.get("frames"), list):
        return [bytes(f) for f in resp["frames"] if isinstance(f, (bytes, bytearray))]
    for key in ("frame", "png"):
        val = resp.get(key)
        if isinstance(val, (bytes, bytearray)):
            return [bytes(val)]
    return []


__all__ = ["ToolDispatcher", "BackendExecutor"]
