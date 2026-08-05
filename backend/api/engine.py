"""Integration seams between the transport layer and the engines / loop.

These Protocols are the *only* contract the API depends on. Agent 1's data
layer + Agent 2's analysis/editing/history are composed into a `Scene` at
integration time; Agent 3's loop satisfies `AgentRunner`. Until then,
`stub_engine.StubBackend` and `stub_agent.StubAgentRunner` provide real,
swappable implementations so the transport layer is fully testable.

Nothing here is a frozen contract — it lives in the API boundary. The frozen
contracts (Metrics, FrontendChannel, SplatModel, ...) are imported from
`backend.contracts`.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from backend.contracts import FrontendChannel, Metrics


@runtime_checkable
class Scene(Protocol):
    """A loaded scene: a `SplatModel` plus analysis/editing/history.

    Edits operate on the alive mask and snapshot internally (every destructive
    op snapshots first — ARCHITECTURE §3.3 / §6.5). `export` writes a valid
    INRIA `.ply` of the *current alive* Gaussians.
    """

    def metrics(self, region: dict | None = None) -> Metrics: ...

    def edit(
        self, op: str, params: dict, selection: dict | None = None
    ) -> tuple[int, int]:
        """Apply a backend edit op. Returns (before_count, after_count)."""
        ...

    def undo(self) -> bool:
        """Revert the last snapshot. Returns False if nothing to undo."""
        ...

    def redo(self) -> bool:
        """Re-apply the last undone snapshot. Returns False if nothing to redo."""
        ...

    def export(self, path: str) -> None:
        """Write the current alive set to `path` as a valid INRIA `.ply`."""
        ...

    def count(self) -> int:
        """Number of currently-alive Gaussians."""
        ...

    def alive_ids(self) -> list[int]:
        """Original ids of alive Gaussians, in export order (v0.2)."""
        ...


@runtime_checkable
class SceneBackend(Protocol):
    """Factory that loads a `.ply` into a `Scene`."""

    def load(self, path: str) -> Scene: ...


@runtime_checkable
class AgentRunner(Protocol):
    """The perceive->act->verify loop (Agent 3), driven over a FrontendChannel.

    Runs to completion, emitting trace events and issuing camera/capture
    commands through `channel`. Must honor cancellation cooperatively.
    """

    async def run(
        self,
        prompt: str,
        scene: Scene,
        channel: FrontendChannel,
        stage: str = "clean",
        mode: str | None = None,
    ) -> None: ...
