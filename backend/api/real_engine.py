"""Integration glue: bind Agent 1's `GaussianSplatModel` + Agent 2's analysis/
editing/history + Agent 3's loop to the API boundary Protocols (engine.py).

Lives in the API boundary (Agent 4), imports only published sibling modules and
the frozen contracts. Two facades wrap ONE shared core (`model` + `History` +
`EditingEngine`):

  * ``RealScene``           -> ``engine.Scene``         (routes/SceneStore)
  * ``RealBackendExecutor`` -> ``dispatch.BackendExecutor`` (the agent loop)

They must be separate classes because the two protocols collide on method name
with different return types (``Scene.undo()->bool`` vs
``BackendExecutor.undo()->dict``). Sharing the core keeps the agent's edits and
the served scene perfectly consistent, and a single undo stack drives both.
"""

from __future__ import annotations

import os
import tempfile

from backend.analysis import (
    EditingEngine,
    History,
    compute_metrics,
    list_problem_regions,
)
from backend.contracts.constants import (
    NEEDLE_RATIO,
    OUTLIER_K,
    OUTLIER_STD_RATIO,
    OVERSIZED_SCENE_FRAC,
)
from backend.api.tempfiles import scene_temp_dir
from backend.splat import GaussianSplatModel

# Edit ops reachable through the routes' POST /edit (deletion + attribute ops).
# Excludes history verbs (snapshot/undo/redo) — those have dedicated routes.
_EDIT_OPS = frozenset(
    {
        "opacity_threshold", "remove_outliers", "prune_oversized",
        "remove_needles",
        "recolor", "adjust_opacity", "truncate_sh",
        # v0.2 — ID-based edits from the frontend's stable ID map
        "delete_by_ids", "keep_only_ids",
    }
)
# These two take a `selection` dict as their first positional arg.
_SELECTION_OPS = frozenset({"recolor", "adjust_opacity"})

# Cross-run chat memory kept per scene (messages, newest last). 60 entries is
# roughly 10-15 agent steps of context — enough for follow-ups without letting
# a long session snowball the provider payload.
_CHAT_HISTORY_LIMIT = 60


class RealScene:
    """`engine.Scene` over the real model/history/editing core."""

    def __init__(self, model: GaussianSplatModel) -> None:
        self.model = model
        self.history = History(model)
        self.editing = EditingEngine(model, self.history)
        # Agent conversation memory for this scene: RealAgentRunner seeds each
        # run with it and writes the updated transcript back, so follow-up
        # prompts have context. Dies with the scene (new upload = fresh chat).
        # `agent_ledger` is the companion grounding evidence (typed loosely so
        # this module never imports backend.agent at boot).
        self.chat_history: list[dict] = []
        self.agent_ledger: object | None = None
        # Understand-stage survey (spec 2026-08-03): frames + labels + scene
        # revision from the last app-flown survey, reused across runs until
        # the revision changes (the frontend compares via if_revision_not).
        self.survey_store: dict | None = None

    def metrics(self, region: dict | None = None) -> dict:
        return compute_metrics(self.model, region)

    def edit(
        self, op: str, params: dict, selection: dict | None = None
    ) -> tuple[int, int]:
        if op not in _EDIT_OPS:
            raise ValueError(f"unknown edit op: {op!r}")
        method = getattr(self.editing, op)
        before = self.count()
        if op in _SELECTION_OPS:
            method(selection or {}, **(params or {}))
        else:
            method(**(params or {}))
        return before, self.count()

    def undo(self) -> bool:
        return self.history.undo()

    def redo(self) -> bool:
        return self.history.redo()

    def export(self, path: str) -> None:
        self.model.export(path)

    def count(self) -> int:
        return int(self.model.alive.sum())

    def alive_ids(self) -> list[int]:
        """Original ids of alive Gaussians, in export order (v0.2)."""
        return [int(i) for i in self.model.alive_indices()]


class RealBackend:
    """`engine.SceneBackend` factory using Agent 1's loader."""

    def load(self, path: str) -> RealScene:
        return RealScene(GaussianSplatModel.load(path))


class RealBackendExecutor:
    """`dispatch.BackendExecutor` view of a `RealScene` for the agent loop.

    Editing/history verbs delegate to the SAME `EditingEngine`/`History` the
    routes use, so an edit the agent makes is visible when the scene is re-served
    and undo is consistent across both surfaces.
    """

    def __init__(self, scene: RealScene) -> None:
        if not hasattr(scene, "editing"):
            raise TypeError("RealBackendExecutor requires a RealScene")
        self._s = scene

    # analysis
    def get_metrics(self, region: dict | None = None) -> dict:
        return compute_metrics(self._s.model, region)

    def list_problem_regions(self) -> list[dict]:
        return list_problem_regions(self._s.model)

    def get_bounds(self) -> dict:
        """Cheap AABB of alive Gaussians (single min/max pass, no k-NN)."""
        mn, mx = self._s.model.bounds()
        return {"min": [float(v) for v in mn], "max": [float(v) for v in mx]}

    # editing (delegate to the shared EditingEngine; each returns count dicts)
    def opacity_threshold(self, min_alpha: float) -> dict:
        return self._s.editing.opacity_threshold(min_alpha)

    def remove_outliers(self, k: int = OUTLIER_K, std_ratio: float = OUTLIER_STD_RATIO) -> dict:
        return self._s.editing.remove_outliers(k, std_ratio)

    def prune_oversized(self, max_axis_scene_frac: float = OVERSIZED_SCENE_FRAC) -> dict:
        return self._s.editing.prune_oversized(max_axis_scene_frac)

    def remove_needles(self, max_axis_ratio: float = NEEDLE_RATIO) -> dict:
        return self._s.editing.remove_needles(max_axis_ratio)

    def recolor(self, selection: dict, rgb: list[float]) -> dict:
        return self._s.editing.recolor(selection, rgb)

    def adjust_opacity(self, selection: dict, factor: float) -> dict:
        return self._s.editing.adjust_opacity(selection, factor)

    def truncate_sh(self, degree: int) -> dict:
        return self._s.editing.truncate_sh(degree)

    # selection editing (v0.2) — ids arrive from the frontend's stable ID map
    # via the dispatcher's get_selection WS pull (see backend/agent/dispatch.py)
    def delete_selection(self, ids: list[int]) -> dict:
        return self._s.editing.delete_by_ids(ids)

    def keep_selection(self, ids: list[int]) -> dict:
        return self._s.editing.keep_only_ids(ids)

    def keep_only_ids(self, ids: list[int]) -> dict:
        """v0.8 — the subject card's approved edit (CleanupController's
        _guarded_edit calls this by name; the mocks had it, the real executor
        didn't — live-found on the first approved card)."""
        return self._s.editing.keep_only_ids(ids)

    def get_selection_state(self, ids: list[int]) -> dict:
        return self._s.editing.selection_state(ids)

    # history
    def snapshot(self) -> None:
        self._s.editing.snapshot()  # no-op marker; edits already auto-snapshot

    def undo(self) -> dict:
        return self._s.editing.undo()

    def redo(self) -> dict:
        return self._s.editing.redo()

    def export_ply(self) -> str:
        fd, path = tempfile.mkstemp(suffix=".ply", prefix="export_", dir=scene_temp_dir())
        os.close(fd)
        self._s.model.export(path)
        return path


def _is_cleanup_prompt(prompt: str) -> bool:
    """Does a typed prompt mean 'run the cleanup routine'?

    Generous on phrasing ('clean up the scene', 'cleanup', 'clean the
    scene'), strict on scope: a prompt with QUALIFIERS ('clean up the
    floaters on the left') stays with the freeform loop, which can target
    specifics."""
    words = prompt.lower().replace("_", " ").split()
    if not words or len(words) > 5:
        return False
    core = [w for w in words if w not in ("the", "this", "my", "up", "please", "whole")]
    return core in (["clean"], ["cleanup"], ["clean", "scene"], ["cleanup", "scene"])


class RealAgentRunner:
    """`engine.AgentRunner`: builds Agent 3's loop over a RealScene and runs it.

    Provider/model/key/base_url resolve from the settings store (a UI-saved
    override, falling back to env — see `backend.api.settings.SettingsStore`).
    Built per-run so a settings change is picked up without restarting, and so
    a provider/config error surfaces as a `complete{error}` trace event
    (routes._drive) rather than at import time.
    """

    async def run(
        self, prompt: str, scene, channel, stage: str = "clean", mode: str | None = None,
    ) -> None:  # scene: RealScene
        # Imported lazily: keeps server boot independent of google-genai being
        # installed (the loop only needs it at run time).
        from backend.agent import AgentLoop, ToolDispatcher
        from backend.agent.system_prompt import Stage, system_prompt_for
        from backend.api.settings import get_store
        from backend.providers import get_provider

        resolved: Stage = "understand" if stage == "understand" else "clean"
        executor = RealBackendExecutor(scene)
        dispatcher = ToolDispatcher(executor, channel)
        cfg = get_store().resolve()

        # v0.7 — judgment-tour cleanup: the app-owned controller replaces the
        # freeform loop for cleanup runs (spec 2026-08-04). Routed by explicit
        # mode OR by a typed cleanup request (live-found: the operator typed
        # 'clean up the scene', missed the exact-literal match, and the
        # freeform loop answered with the retired crop-box flow).
        if resolved == "clean" and (mode == "cleanup" or _is_cleanup_prompt(prompt)):
            import numpy as np

            from backend.agent.cleanup_controller import CleanupController

            provider = get_provider(
                cfg.provider,
                cfg.model,
                api_key=cfg.api_key,
                base_url=cfg.base_url,
                system_instruction="You are a visual inspector for a 3D scan. "
                                   "Always answer by calling the provided tool.",
            )

            def splat_arrays() -> dict:
                m = scene.model
                return {
                    "means": np.asarray(m.means[m.alive], dtype=np.float64),
                    "opacity": np.asarray(m.opacity(alive_only=True), dtype=np.float64),
                    "ids": np.asarray(m.alive_indices(), dtype=np.int64),
                    # linear per-axis scales — the subject finder uses these to
                    # drop streak/needle gaussians from the keep-set (v0.8.1)
                    "scale": np.asarray(m.scale(alive_only=True), dtype=np.float64),
                }

            controller = CleanupController(provider, dispatcher, channel, executor, splat_arrays)
            await controller.run(prompt)
            return

        provider = get_provider(
            cfg.provider,
            cfg.model,
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            system_instruction=system_prompt_for(resolved),
        )
        # The provider carries the system prompt natively (system_instruction
        # above); an empty system_prompt stops the loop from ALSO seeding
        # messages[0] with the same text — providers were sending it twice.
        loop = AgentLoop(provider, dispatcher, channel, stage=resolved, system_prompt="")
        history = getattr(scene, "chat_history", None)
        try:
            await loop.run(
                prompt,
                history=history,
                ledger=getattr(scene, "agent_ledger", None),
                survey=getattr(scene, "survey_store", None) if resolved == "understand" else None,
            )
        finally:
            # Persist even after an error/interrupt — the follow-up should
            # still know what happened. Bounded tail so per-scene memory
            # can't grow without limit across runs.
            if history is not None:
                history[:] = loop.transcript()[-_CHAT_HISTORY_LIMIT:]
            if hasattr(scene, "agent_ledger"):
                scene.agent_ledger = loop.ledger
            if resolved == "understand" and getattr(loop, "survey_out", None) is not None:
                scene.survey_store = loop.survey_out


__all__ = ["RealBackend", "RealScene", "RealBackendExecutor", "RealAgentRunner"]
