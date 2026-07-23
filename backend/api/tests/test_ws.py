"""WebSocket acceptance: a send_command round-trip (await a frame reply) and a
fire-and-forget emit_event, both against a mock renderer client; plus a full
/agent/run drive over a real TestClient websocket."""

from __future__ import annotations

import asyncio
import base64
import os

import pytest
from fastapi.testclient import TestClient

from backend.api.ws import ConnectionManager, WSChannel
from backend.server import create_app

MESSY = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "examples", "messy.ply",
)


class MockWS:
    """Minimal stand-in for a Starlette WebSocket (a mock renderer)."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)

    async def close(self) -> None:
        pass


@pytest.mark.anyio
async def test_send_command_roundtrip_and_emit_event():
    mgr = ConnectionManager()
    ws = MockWS()
    await mgr.connect("s1", ws)
    assert ws.accepted
    channel = WSChannel("s1", mgr)

    # emit_event is fire-and-forget
    await channel.emit_event({"type": "thought", "payload": {"text": "hello"}})
    assert ws.sent[-1] == {"type": "thought", "payload": {"text": "hello"}}

    # send_command awaits a correlated reply (a captured frame)
    task = asyncio.create_task(channel.send_command({"type": "capture_request", "payload": {}}))
    await asyncio.sleep(0)  # let the command go out
    cmd = ws.sent[-1]
    assert cmd["type"] == "capture_request"
    corr = cmd["id"]

    png = b"\x89PNG\r\n\x1a\nFRAMEBYTES"
    mgr.handle_message("s1", {"type": "frame", "id": corr, "payload": {"png_base64": base64.b64encode(png).decode()}})

    reply = await asyncio.wait_for(task, timeout=2)
    assert reply["png"] == png  # decoded for the loop


@pytest.mark.anyio
async def test_disconnect_fails_pending():
    mgr = ConnectionManager()
    await mgr.connect("s2", MockWS())
    channel = WSChannel("s2", mgr)
    task = asyncio.create_task(channel.send_command({"type": "capture_request"}))
    await asyncio.sleep(0)
    mgr.disconnect("s2")
    with pytest.raises(ConnectionError):
        await asyncio.wait_for(task, timeout=2)


@pytest.fixture
def anyio_backend():
    return "asyncio"


class AutoReplyWS(MockWS):
    """A mock renderer that auto-acks every command (frame for captures)."""

    def __init__(self, manager: ConnectionManager, scene_id: str) -> None:
        super().__init__()
        self._mgr = manager
        self._scene_id = scene_id

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)
        if "id" in message:  # a command awaiting a reply
            payload = {"ok": True}
            if message["type"] == "capture_request":
                payload = {"png_base64": base64.b64encode(b"PNG").decode()}
            self._mgr.handle_message(
                self._scene_id, {"type": "frame", "id": message["id"], "payload": payload}
            )


@pytest.mark.anyio
async def test_runner_drives_channel_end_to_end():
    """The real StubAgentRunner -> WSChannel -> ConnectionManager -> renderer."""
    from backend.api.stub_agent import StubAgentRunner
    from backend.api.stub_engine import StubBackend

    mgr = ConnectionManager()
    ws = AutoReplyWS(mgr, "s3")
    await mgr.connect("s3", ws)
    scene = StubBackend().load(MESSY)

    await StubAgentRunner().run("inspect the scene", scene, WSChannel("s3", mgr))

    types_seen = [m["type"] for m in ws.sent]
    assert "thought" in types_seen
    assert "camera_move" in types_seen          # a command went out and was acked
    assert "capture_request" in types_seen      # capture round-trip completed
    assert types_seen[-1] == "complete"


def test_agent_run_route_returns_started():
    """POST /agent/run wires up and returns a run id (drive verified above)."""
    app = create_app()
    client = TestClient(app)
    with open(MESSY, "rb") as f:
        scene_id = client.post("/scene", files={"file": ("m.ply", f, "application/octet-stream")}).json()["id"]
    asyncio.run(app.state.manager.connect(scene_id, MockWS()))
    r = client.post("/agent/run", json={"scene_id": scene_id, "prompt": "hi"})
    assert r.status_code == 200
    assert r.json()["status"] == "started"
    assert r.json()["run_id"]


@pytest.mark.anyio
async def test_stale_socket_cleanup_does_not_evict_replacement():
    """The reconnect race: connect() swaps A→B, then A's route cleanup fires.
    Keyed-by-scene disconnect used to evict B, leaving no renderer registered."""
    mgr = ConnectionManager()
    a, b = MockWS(), MockWS()
    await mgr.connect("s1", a)
    await mgr.connect("s1", b)   # one-renderer-per-scene: closes and replaces a
    mgr.disconnect("s1", a)      # stale route cleanup for the OLD socket
    assert mgr.is_connected("s1"), "replacement socket must survive stale cleanup"
    mgr.disconnect("s1", b)      # the CURRENT socket's cleanup still removes
    assert not mgr.is_connected("s1")


@pytest.mark.anyio
async def test_disconnect_without_socket_still_removes():
    mgr = ConnectionManager()
    await mgr.connect("s1", MockWS())
    mgr.disconnect("s1")
    assert not mgr.is_connected("s1")
