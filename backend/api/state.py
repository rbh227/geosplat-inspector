"""Scene state: hold loaded scenes by id; edits mutate state; serving reflects
the current alive set.

A `SceneState` owns the source upload path, the engine `Scene`, a per-scene
async lock (serialize edits), a `dirty` flag, and a cached export path. When a
scene is unedited it serves the original upload directly; once edited it
re-exports the alive set to a temp file and serves that — always a file on
disk, so serving streams (never builds the `.ply` in memory).
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import uuid

from backend.api.engine import Scene, SceneBackend
from backend.api.tempfiles import scene_temp_dir


class SceneState:
    def __init__(self, scene_id: str, scene: Scene, source_path: str) -> None:
        self.id = scene_id
        self.scene = scene
        self.source_path = source_path        # original uploaded .ply
        self._source_count = scene.count()    # alive count as loaded from source
        self._epoch = 0                       # bumped by mark_dirty()
        self._exported: tuple[int, int] | None = None  # (epoch, count) last written
        self._export_path: str | None = None  # cached re-export of alive set
        self.lock = asyncio.Lock()            # serialize edits per scene

    def mark_dirty(self) -> None:
        """Signal an edit. Optional: staleness is *derived* (see `dirty`), so a
        path that forgets to call this still serves correctly. It only sharpens
        cache invalidation when an edit leaves the alive count unchanged."""
        self._epoch += 1

    @property
    def dirty(self) -> bool:
        """Whether the alive set diverges from the source upload.

        Derived from the scene's alive count rather than tracked by hand. The
        agent edits through the tool dispatcher and never reaches the `/edit`
        route, so a flag only that route set left `GET /scene/{id}.ply` serving
        the original upload — and since the frontend reloads that URL after any
        run reporting `scene_changed`, an approved crop was undone on screen.
        Edits are removal-only, so `count == source_count` means everything is
        alive and the source file is exactly right.
        """
        return self.scene.count() != self._source_count

    def current_ply_path(self) -> str:
        """Path to a `.ply` reflecting the current alive set (for serving).

        Unedited -> the source file. Edited -> a cached export, regenerated
        only when the alive set may have moved since the last write. Either way
        it's a real file on disk, so serving streams instead of building the
        `.ply` in memory.
        """
        count = self.scene.count()
        if count == self._source_count:
            return self.source_path
        if self._export_path is None:
            fd, path = tempfile.mkstemp(
                suffix=".ply", prefix=f"scene_{self.id}_", dir=scene_temp_dir()
            )
            os.close(fd)
            self._export_path = path
        stamp = (self._epoch, count)
        if self._exported != stamp:
            self.scene.export(self._export_path)
            self._exported = stamp
        return self._export_path

    def cleanup(self) -> None:
        # The source is the app's own temp copy of the upload (routes.py writes
        # it into scene_temp_dir()), so it goes with the scene.
        for path in (self._export_path, self.source_path):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass


class SceneStore:
    """Async-safe registry of loaded scenes keyed by id."""

    def __init__(self, backend: SceneBackend) -> None:
        self._backend = backend
        self._scenes: dict[str, SceneState] = {}
        self._lock = asyncio.Lock()

    async def create(self, source_path: str) -> SceneState:
        # Threaded: parsing a multi-million-splat .ply inline would freeze the
        # event loop (and with it every WS/HTTP request) for the whole parse.
        scene = await asyncio.to_thread(self._backend.load, source_path)
        scene_id = uuid.uuid4().hex[:12]
        state = SceneState(scene_id, scene, source_path)
        async with self._lock:
            self._scenes[scene_id] = state
        return state

    def get(self, scene_id: str) -> SceneState | None:
        return self._scenes.get(scene_id)

    def require(self, scene_id: str) -> SceneState:
        state = self._scenes.get(scene_id)
        if state is None:
            raise KeyError(scene_id)
        return state

    async def remove(self, scene_id: str) -> None:
        async with self._lock:
            state = self._scenes.pop(scene_id, None)
        if state:
            state.cleanup()

    async def clear(self) -> None:
        """Drop every scene and delete its temp files (shutdown path)."""
        async with self._lock:
            states = list(self._scenes.values())
            self._scenes.clear()
        for state in states:
            state.cleanup()

    def __len__(self) -> int:
        return len(self._scenes)


__all__ = ["SceneState", "SceneStore"]
