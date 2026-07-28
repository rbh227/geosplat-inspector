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


DEFAULT_CLIENT = "default"


class ConnectionManager:
    """Tracks renderer sockets per scene (keyed by client) and routes replies.

    Sockets are keyed by (scene_id, client_id), NOT scene alone: the editor and
    the analyst window are two renderers on the SAME scene, and keying by scene
    made each one's connect() close the other's socket — the two windows could
    never be live at once. Commands are addressed to one client (the renderer
    that owns the run); trace events broadcast to every window on the scene, so
    a run started in one is visible in the other and a scene-changing run makes
    both resync.

    Run state (interrupt/pause) stays keyed by SCENE, because only one run per
    scene is allowed regardless of which window started it.
    """

    def __init__(self) -> None:
        # scene_id -> {client_id -> WebSocket}
        self._conns: dict[str, dict[str, Any]] = {}
        self._pending: dict[str, asyncio.Future] = {}    # corr_id -> Future
        # corr_id -> (scene_id, client_id)
        self._pending_scene: dict[str, tuple[str, str]] = {}
        self._interrupted: set[str] = set()              # scene_ids interrupted
        self._paused: set[str] = set()                   # scene_ids paused (stateful, non-consuming)
        self._resume_events: dict[str, asyncio.Event] = {}  # scene_id -> resume signal

    # ---- connection lifecycle -------------------------------------------- #
    async def connect(
        self, scene_id: str, websocket: Any, client_id: str = DEFAULT_CLIENT
    ) -> None:
        await websocket.accept()
        clients = self._conns.setdefault(scene_id, {})
        # One socket per CLIENT: a reconnecting window replaces only its own.
        old = clients.get(client_id)
        if old is not None:
            try:
                await old.close()
            except Exception:
                pass
            # Commands in flight on the OLD socket can never be answered by the
            # replacement (it never saw them) — fail them now or they park
            # forever (a proposal has NO timeout: the run would hang and the
            # scene would 409 every future /agent/run).
            self._fail_pending(scene_id, "renderer reconnected mid-command", client_id)
        clients[client_id] = websocket
        self._interrupted.discard(scene_id)

    def _fail_pending(
        self, scene_id: str, reason: str, client_id: str | None = None
    ) -> None:
        for corr_id, (sid, cid) in list(self._pending_scene.items()):
            if sid != scene_id:
                continue
            if client_id is not None and cid != client_id:
                continue
            fut = self._pending.pop(corr_id, None)
            self._pending_scene.pop(corr_id, None)
            if fut and not fut.done():
                fut.set_exception(ConnectionError(reason))

    def reset_run_flags(self, scene_id: str) -> None:
        """Clear stale interrupt/pause state before a NEW run starts — signals
        sent in the previous run's end-race window must not kill or invisibly
        pause the next run's first action."""
        self._interrupted.discard(scene_id)
        self._paused.discard(scene_id)

    def disconnect(
        self,
        scene_id: str,
        websocket: Any | None = None,
        client_id: str = DEFAULT_CLIENT,
    ) -> None:
        """Remove one renderer. With `websocket` given, remove it only if it is
        STILL the registered socket for that client: connect() swaps in a
        replacement before the old socket's route cleanup runs, and that stale
        cleanup must never evict the replacement (observed reconnect race)."""
        clients = self._conns.get(scene_id)
        if clients is None:
            return
        if websocket is not None and clients.get(client_id) is not websocket:
            return
        clients.pop(client_id, None)
        if not clients:
            self._conns.pop(scene_id, None)
        self._fail_pending(scene_id, "renderer disconnected", client_id)
        # A disconnect must also release a paused loop (wait_resume would
        # otherwise park forever with nobody left to press Resume) — but only
        # once the LAST window on the scene is gone; the other one can resume.
        if not clients:
            ev = self._resume_events.get(scene_id)
            if ev is not None:
                ev.set()
            self._paused.discard(scene_id)

    def is_connected(self, scene_id: str) -> bool:
        return bool(self._conns.get(scene_id))

    def clients(self, scene_id: str) -> list[str]:
        return list(self._conns.get(scene_id, {}))

    def _resolve_client(self, scene_id: str, client_id: str | None) -> str | None:
        """Which renderer a command should go to.

        An explicit client wins. Otherwise fall back to the only connected one
        — with two windows open and no client named, there is no defensible
        choice, so refuse rather than picking arbitrarily.
        """
        clients = self._conns.get(scene_id) or {}
        if client_id is not None:
            return client_id if client_id in clients else None
        return next(iter(clients)) if len(clients) == 1 else None

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
        client_id: str | None = None,
    ) -> dict:
        target = self._resolve_client(scene_id, client_id)
        ws = (self._conns.get(scene_id) or {}).get(target) if target else None
        if ws is None:
            raise ConnectionError(f"no renderer connected for scene {scene_id}")
        corr_id = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[corr_id] = fut
        self._pending_scene[corr_id] = (scene_id, target)
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
        """Broadcast to EVERY window on the scene, not just the run's owner: a
        run started in one window should be visible in the other, and a
        scene-changing run must make both resync."""
        for client_id, ws in list((self._conns.get(scene_id) or {}).items()):
            try:
                await ws.send_json({"type": etype, "payload": payload or {}})
            except Exception:
                self.disconnect(scene_id, ws, client_id)


class WSChannel(FrontendChannel):
    """Per-scene `FrontendChannel` (§6.8) backed by a `ConnectionManager`.

    Handed to Agent 3's loop; the loop calls `send_command`/`emit_event`
    uniformly and never sees the socket.
    """

    def __init__(
        self,
        scene_id: str,
        manager: ConnectionManager,
        client_id: str | None = None,
    ) -> None:
        self._scene_id = scene_id
        self._mgr = manager
        # Which window's renderer executes this run's tools. None falls back to
        # the sole connected client (single-window and test setups).
        self._client_id = client_id

    async def send_command(self, cmd: dict) -> dict:
        ctype = cmd.get("type")
        if ctype not in COMMAND_TYPES:
            raise ValueError(f"unknown command type: {ctype!r}")
        payload = cmd.get("payload", {k: v for k, v in cmd.items() if k != "type"})
        # A proposal parks on the operator's decision — no timeout (asyncio's
        # wait_for(timeout=None) already waits forever).
        timeout = None if ctype == "proposal" else DEFAULT_COMMAND_TIMEOUT
        return await self._mgr.send_command(
            self._scene_id, ctype, payload, timeout, self._client_id,
        )

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
