"""FrontendChannel protocol (ARCHITECTURE.md §6.8). Frozen."""

from __future__ import annotations

from typing import Protocol


class FrontendChannel(Protocol):
    async def send_command(self, cmd: dict) -> dict:
        """Send a command and await the result (e.g. a captured frame)."""
        ...

    async def emit_event(self, event: dict) -> None:
        """Fire-and-forget trace/narration event."""
        ...
