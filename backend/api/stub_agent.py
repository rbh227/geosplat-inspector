"""Stub agent runner — exercises the `FrontendChannel` to prove the WS plumbing
end to end before Agent 3's real perceive->act->verify loop lands.

It emits the §6.8 trace events and issues a camera move + a capture (awaiting a
real frame reply), then completes. Swap for Agent 3's `AgentRunner` at
integration; routes are unchanged.
"""

from __future__ import annotations

from backend.api.engine import Scene
from backend.contracts import FrontendChannel


class StubAgentRunner:
    async def run(self, prompt: str, scene: Scene, channel: FrontendChannel) -> None:
        await channel.emit_event({"type": "thought", "payload": {"text": f"Received: {prompt}"}})

        # measure (backend-local) — legible trace of a tool call
        await channel.emit_event({"type": "tool_call", "payload": {"name": "get_metrics", "args": {}}})
        metrics = scene.metrics()
        await channel.emit_event({
            "type": "tool_result",
            "payload": {"name": "get_metrics", "gaussianCount": metrics["gaussianCount"]},
        })

        # act on the renderer: move the camera, then capture a frame (awaits reply)
        bounds = metrics["bounds"]
        center = [
            (bounds["min"][0] + bounds["max"][0]) / 2,
            (bounds["min"][1] + bounds["max"][1]) / 2,
            (bounds["min"][2] + bounds["max"][2]) / 2,
        ]
        await channel.emit_event({"type": "tool_call", "payload": {"name": "look_at", "args": {"target": center}}})
        try:
            await channel.send_command({"type": "camera_move", "payload": {"target": center, "duration_ms": 800}})
            frame = await channel.send_command({"type": "capture_request", "payload": {}})
            got = "png" in frame or "png_base64" in frame
            await channel.emit_event({"type": "tool_result", "payload": {"name": "capture_frame", "got_frame": got}})
        except Exception as exc:  # no renderer / timeout — still complete cleanly
            await channel.emit_event({"type": "tool_result", "payload": {"name": "capture_frame", "error": str(exc)}})

        await channel.emit_event({
            "type": "complete",
            "payload": {"text": "Stub run complete.", "gaussianCount": metrics["gaussianCount"]},
        })


__all__ = ["StubAgentRunner"]
