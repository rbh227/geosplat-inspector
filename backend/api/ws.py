"""WebSocket connection management + the `FrontendChannel` implementation.

Wire format (matches the frozen `/frontend/src/contracts.ts` envelopes):

  backend -> frontend command : {"type": <WSCommandType>, "id": <corr>, "payload": {...}}
  backend -> frontend trace   : {"type": <WSTraceType>,   "payload": {...}}        (no id)
  frontend -> backend reply   : {"type": "frame"|"user_interrupt", "id": <corr>, "payload": {...}}

`send_command` issues a correlated command and awaits the matching reply
(e.g. a captured frame, base64-encoded in `payload.png_base64`); `emit_event`
is fire-and-forget. `WSChannel` is the `FrontendChannel` handed to Agent 3's
loop — it never knows a socket is involved.
"""

from __future__ import annotations

import asyncio
import base64
import uuid
from typing import Any

from backend.contracts import FrontendChannel

# §6.8 type sets, kept local so we can validate without importing the TS file.
# v0.2 adds: get_selection / selection_tool / movement_input commands, the
# correlated selection / tool_result replies, and the stateful agent_pause /
# agent_resume signals (distinct from user_interrupt, which aborts a run).
COMMAND_TYPES = {
    "camera_move", "capture_request", "drop_marker",
    "clear_markers", "narrate", "reload_scene",
    "get_selection", "selection_tool", "movement_input", "rotation_input",
    "proposal",
}
TRACE_TYPES = {"thought", "tool_call", "tool_result", "complete"}
REPLY_TYPES = {"frame", "user_interrupt", "selection", "tool_result", "agent_pause", "agent_resume"}

DEFAULT_COMMAND_TIMEOUT = 30.0  # seconds to await a frontend reply


class ConnectionManager:
    """Tracks one renderer socket per scene and routes correlated replies."""

    def __init__(self) -> None:
        self._conns: dict[str, Any] = {}                 # scene_id -> WebSocket
        self._pending: dict[str, asyncio.Future] = {}    # corr_id -> Future
        self._pending_scene: dict[str, str] = {}         # corr_id -> scene_id
        self._interrupted: set[str] = set()              # scene_ids interrupted
        self._paused: set[str] = set()                   # scene_ids paused (stateful, non-consuming)
        self._resume_events: dict[str, asyncio.Event] = {}  # scene_id -> resume signal

    # ---- connection lifecycle -------------------------------------------- #
    async def connect(self, scene_id: str, websocket: Any) -> None:
        await websocket.accept()
        # one renderer per scene: drop a stale socket if present
        old = self._conns.get(scene_id)
        if old is not None:
            try:
                await old.close()
            except Exception:
                pass
        self._conns[scene_id] = websocket
        self._interrupted.discard(scene_id)

    def disconnect(self, scene_id: str, websocket: Any | None = None) -> None:
        """Remove a scene's renderer. With `websocket` given, remove it only if
        it is STILL the registered socket: connect() swaps in a replacement
        before the old socket's route cleanup runs, and that stale cleanup must
        never evict the replacement (observed reconnect race)."""
        if websocket is not None and self._conns.get(scene_id) is not websocket:
            return
        self._conns.pop(scene_id, None)
        # fail any in-flight commands for this scene
        for corr_id, sid in list(self._pending_scene.items()):
            if sid == scene_id:
                fut = self._pending.pop(corr_id, None)
                self._pending_scene.pop(corr_id, None)
                if fut and not fut.done():
                    fut.set_exception(ConnectionError("renderer disconnected"))

    def is_connected(self, scene_id: str) -> bool:
        return scene_id in self._conns

    # ---- inbound routing -------------------------------------------------- #
    def handle_message(self, scene_id: str, message: dict) -> None:
        """Route a frontend->backend message (already JSON-decoded)."""
        mtype = message.get("type")
        if mtype == "user_interrupt":
            self._interrupted.add(scene_id)
            # an abort also releases a paused loop so it can wind down
            self._paused.discard(scene_id)
            ev = self._resume_events.get(scene_id)
            if ev is not None:
                ev.set()
            return
        if mtype == "agent_pause":
            self._paused.add(scene_id)
            self._resume_events.setdefault(scene_id, asyncio.Event()).clear()
            return
        if mtype == "agent_resume":
            self._paused.discard(scene_id)
            ev = self._resume_events.get(scene_id)
            if ev is not None:
                ev.set()
            return
        if mtype == "frame" or "id" in message:
            corr_id = message.get("id")
            fut = self._pending.get(corr_id)
            if fut and not fut.done():
                fut.set_result(message.get("payload", {}))

    def take_interrupt(self, scene_id: str) -> bool:
        """Consume and clear the interrupt flag for a scene."""
        if scene_id in self._interrupted:
            self._interrupted.discard(scene_id)
            return True
        return False

    # ---- pause/resume (v0.2, stateful — unlike the consume-once interrupt) -- #
    def is_paused(self, scene_id: str) -> bool:
        return scene_id in self._paused

    async def wait_resume(self, scene_id: str) -> None:
        """Block until the operator resumes (or aborts) a paused run."""
        if scene_id not in self._paused:
            return
        ev = self._resume_events.setdefault(scene_id, asyncio.Event())
        await ev.wait()

    # ---- outbound: command (await reply) ---------------------------------- #
    async def send_command(
        self,
        scene_id: str,
        ctype: str,
        payload: dict | None = None,
        timeout: float | None = DEFAULT_COMMAND_TIMEOUT,
    ) -> dict:
        ws = self._conns.get(scene_id)
        if ws is None:
            raise ConnectionError(f"no renderer connected for scene {scene_id}")
        corr_id = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[corr_id] = fut
        self._pending_scene[corr_id] = scene_id
        try:
            await ws.send_json({"type": ctype, "id": corr_id, "payload": payload or {}})
            reply = await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending.pop(corr_id, None)
            self._pending_scene.pop(corr_id, None)
        # Decode captured frames into raw PNG bytes the agent loop feeds to the
        # model. Frontend sends BARE base64 (no data: prefix): single capture ->
        # {"png_base64": <str>}, orbit -> {"frames_base64": [<str>, ...]}. Both
        # normalize to `frames: list[bytes]` (dispatch._extract_frames reads it).
        if isinstance(reply, dict):
            reply = self._decode_frames(reply)
        return reply

    @staticmethod
    def _decode_frames(reply: dict) -> dict:
        frames: list[bytes] = []

        def _decode(s: str) -> None:
            try:
                raw = base64.b64decode(s)
            except Exception:
                return
            if raw:  # drop empties (e.g. base64 of non-alphabet junk)
                frames.append(raw)

        single = reply.get("png_base64")
        if isinstance(single, str):
            _decode(single)
        multi = reply.get("frames_base64")
        if isinstance(multi, list):
            for item in multi:
                if isinstance(item, str):
                    _decode(item)
        if not frames:
            return reply
        out = {**reply, "frames": frames}
        if len(frames) == 1 and "png" not in out:
            out["png"] = frames[0]  # convenience for single capture
        return out

    # ---- outbound: trace (fire-and-forget) -------------------------------- #
    async def emit_event(self, scene_id: str, etype: str, payload: dict | None = None) -> None:
        ws = self._conns.get(scene_id)
        if ws is None:
            return  # no renderer attached; drop the trace event
        try:
            await ws.send_json({"type": etype, "payload": payload or {}})
        except Exception:
            self.disconnect(scene_id, ws)


class WSChannel(FrontendChannel):
    """Per-scene `FrontendChannel` (§6.8) backed by a `ConnectionManager`.

    Handed to Agent 3's loop; the loop calls `send_command`/`emit_event`
    uniformly and never sees the socket.
    """

    def __init__(self, scene_id: str, manager: ConnectionManager) -> None:
        self._scene_id = scene_id
        self._mgr = manager

    async def send_command(self, cmd: dict) -> dict:
        ctype = cmd.get("type")
        if ctype not in COMMAND_TYPES:
            raise ValueError(f"unknown command type: {ctype!r}")
        payload = cmd.get("payload", {k: v for k, v in cmd.items() if k != "type"})
        # A proposal parks on the operator's decision — no timeout (asyncio's
        # wait_for(timeout=None) already waits forever).
        timeout = None if ctype == "proposal" else DEFAULT_COMMAND_TIMEOUT
        return await self._mgr.send_command(self._scene_id, ctype, payload, timeout)

    async def emit_event(self, event: dict) -> None:
        etype = event.get("type")
        payload = event.get("payload", {k: v for k, v in event.items() if k != "type"})
        await self._mgr.emit_event(self._scene_id, etype, payload)

    @property
    def interrupted(self) -> bool:
        return self._mgr.take_interrupt(self._scene_id)

    @property
    def paused(self) -> bool:
        """Non-consuming pause state (v0.2). The loop checks this between tool calls."""
        return self._mgr.is_paused(self._scene_id)

    async def wait_resume(self) -> None:
        await self._mgr.wait_resume(self._scene_id)


__all__ = ["ConnectionManager", "WSChannel", "COMMAND_TYPES", "TRACE_TYPES", "REPLY_TYPES"]
