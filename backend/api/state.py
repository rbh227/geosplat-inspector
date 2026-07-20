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


class SceneState:
    def __init__(self, scene_id: str, scene: Scene, source_path: str) -> None:
        self.id = scene_id
        self.scene = scene
        self.source_path = source_path        # original uploaded .ply
        self.dirty = False                    # alive set diverged from source?
        self._export_path: str | None = None  # cached re-export of alive set
        self.lock = asyncio.Lock()            # serialize edits per scene

    def mark_dirty(self) -> None:
        self.dirty = True

    def current_ply_path(self) -> str:
        """Path to a `.ply` reflecting the current alive set (for serving).

        Unedited -> the source file. Edited -> a cached export, regenerated
        only when `dirty`. Either way it's a real file on disk.
        """
        if not self.dirty:
            return self.source_path
        if self._export_path is None:
            fd, path = tempfile.mkstemp(suffix=".ply", prefix=f"scene_{self.id}_")
            os.close(fd)
            self._export_path = path
        self.scene.export(self._export_path)
        self.dirty = False
        return self._export_path

    def cleanup(self) -> None:
        if self._export_path and os.path.exists(self._export_path):
            try:
                os.remove(self._export_path)
            except OSError:
                pass


class SceneStore:
    """Async-safe registry of loaded scenes keyed by id."""

    def __init__(self, backend: SceneBackend) -> None:
        self._backend = backend
        self._scenes: dict[str, SceneState] = {}
        self._lock = asyncio.Lock()

    async def create(self, source_path: str) -> SceneState:
        scene = self._backend.load(source_path)
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

    def __len__(self) -> int:
        return len(self._scenes)


__all__ = ["SceneState", "SceneStore"]
