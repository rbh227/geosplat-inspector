"""REST + WebSocket routes (§6.7, §6.8).

Wired with injected singletons (`SceneStore`, `ConnectionManager`,
`AgentRunner`) so the concrete engine/loop are swappable. Scene serving streams
from disk via `FileResponse` and never materializes the `.ply` in memory.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import uuid

from fastapi import (
    APIRouter,
    File,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse

from backend.api.engine import AgentRunner
from backend.api.schemas import (
    AgentRunRequest,
    AgentRunResponse,
    EditRequest,
    EditResponse,
    HistoryResponse,
    ModelConfigRequest,
    ModelConfigResponse,
    SceneRequest,
    TestConnectionRequest,
    TestConnectionResponse,
    UploadResponse,
)
from backend.api.settings import (
    UNSET,
    SettingsStore,
    UnknownPresetError,
    providers_public,
    registry_entry,
)
from backend.api.state import SceneStore
from backend.api.ws import DEFAULT_CLIENT, ConnectionManager, WSChannel

_UPLOAD_CHUNK = 1024 * 1024  # 1 MiB streaming copy
_TEST_TIMEOUT_S = 20


def _redact(text: str, *candidates: str | None) -> str:
    """Strip any candidate secret (e.g. an API key) out of provider error text
    before it reaches the client. Vendor SDKs sometimes echo the key/base_url
    they were given inside an exception message."""
    for candidate in candidates:
        if candidate and len(candidate) >= 6:
            text = text.replace(candidate, "•••")
    return text


def create_router(
    store: SceneStore,
    manager: ConnectionManager,
    runner: AgentRunner,
    settings: SettingsStore,
) -> APIRouter:
    router = APIRouter()
    _runs: set[asyncio.Task] = set()  # keep background runs from being GC'd
    # One active run per scene (Codex adversarial review): a second concurrent
    # loop would race edits/undo against the same history and orphan a parked
    # no-timeout proposal, hanging the first loop forever.
    _active_runs: dict[str, asyncio.Task] = {}

    def _require(scene_id: str):
        state = store.get(scene_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"scene {scene_id} not found")
        return state

    # ---- POST /scene : upload -> id + metrics ---------------------------- #
    @router.post("/scene", response_model=UploadResponse)
    async def upload_scene(file: UploadFile = File(...)):
        # stream the upload to a temp file (never read the whole .ply into RAM)
        fd, tmp_path = tempfile.mkstemp(suffix=".ply", prefix="upload_")
        os.close(fd)
        try:
            with open(tmp_path, "wb") as out:
                while chunk := await file.read(_UPLOAD_CHUNK):
                    out.write(chunk)
        finally:
            await file.close()
        try:
            state = await store.create(tmp_path)
        except Exception as exc:
            os.remove(tmp_path)
            raise HTTPException(status_code=400, detail=f"failed to load scene: {exc}")
        # Metrics are NOT computed here: the k-NN pass takes minutes on a
        # 2M-splat scene and saturates the cores SparkJS needs for its
        # CPU-side sort, so the viewer renders and then freezes for the whole
        # computation. Nothing in the upload path needs them — `GET /metrics`
        # computes on demand for the callers that do.
        return UploadResponse(id=state.id, count=state.scene.count())

    # ---- GET /scene/{id}.ply : chunked serve of the current alive set ---- #
    # `?version=original` serves the untouched upload instead, so the editor can
    # show a before/after WITHOUT changing any server state — it is a viewing
    # lens, never a checkout. Edits are unaffected either way.
    @router.get("/scene/{scene_id}.ply")
    async def get_scene_ply(scene_id: str, version: str = Query("current")):
        state = _require(scene_id)
        if version == "original":
            # No lock and no export: source_path is immutable for the scene's
            # lifetime, so this cannot race an in-flight edit.
            return FileResponse(
                state.source_path,
                media_type="application/octet-stream",
                filename=f"{scene_id}-original.ply",
            )
        if version != "current":
            raise HTTPException(
                status_code=400,
                detail=f"unknown version {version!r} — expected 'current' or 'original'",
            )
        async with state.lock:
            path = await asyncio.to_thread(state.current_ply_path)  # may export 2M splats
        return FileResponse(
            path,
            media_type="application/octet-stream",
            filename=f"{scene_id}.ply",
        )

    # ---- GET /agent/history : the conversation the backend already keeps --- #
    # `scene.chat_history` survives a browser reload (it lives with the scene),
    # so the agent still remembers — only the visible bubbles were lost. This
    # lets the frontend put them back.
    #
    # DISPLAY-SAFE, deliberately: chat_history is the MODEL's transcript, and
    # AgentLoop encodes tool results and nudges as `role: "user"` turns
    # ("[tool_result ...]", "[system] ..."). Restoring by role alone would fill
    # the operator's chat with machine chatter and bury the real exchange.
    @router.get("/agent/history")
    async def get_agent_history(scene_id: str = Query(...)):
        state = _require(scene_id)
        raw = list(getattr(state.scene, "chat_history", []) or [])
        shown = [
            m for m in raw
            if m.get("role") in ("user", "assistant")
            and isinstance(m.get("content"), str)
            and m["content"].strip()
            and not m["content"].lstrip().startswith(("[tool_result", "[system]", "[scene]"))
        ]
        return {"messages": shown}

    # ---- GET /ids : alive original Gaussian ids (v0.2) ------------------- #
    # After a backend-driven reload the frontend adopts these so its stable
    # ID map matches the backend's ID space (packed index i <-> i-th entry).
    @router.get("/ids")
    async def get_alive_ids(scene_id: str = Query(...)):
        state = _require(scene_id)
        async with state.lock:
            ids = await asyncio.to_thread(state.scene.alive_ids)
        return {"ids": ids}

    # ---- GET /metrics : compute metrics (optional region) ---------------- #
    @router.get("/metrics")
    async def get_metrics(
        scene_id: str = Query(...),
        region: str | None = Query(None, description="JSON {min:[3],max:[3]}"),
    ):
        state = _require(scene_id)
        parsed = None
        if region:
            try:
                parsed = json.loads(region)
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="region must be JSON")
        return await asyncio.to_thread(state.scene.metrics, parsed)

    # ---- POST /edit : mutate alive set -> counts + metrics --------------- #
    @router.post("/edit", response_model=EditResponse)
    async def edit_scene(req: EditRequest):
        state = _require(req.scene_id)
        async with state.lock:
            try:
                before, after = await asyncio.to_thread(
                    state.scene.edit, req.op, req.params, req.selection
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            state.mark_dirty()
            metrics = await asyncio.to_thread(state.scene.metrics)
        return EditResponse(before=before, after=after, metrics=metrics)

    # ---- POST /undo, /redo ----------------------------------------------- #
    @router.post("/undo", response_model=HistoryResponse)
    async def undo(req: SceneRequest):
        state = _require(req.scene_id)
        async with state.lock:
            ok = await asyncio.to_thread(state.scene.undo)
            if ok:
                state.mark_dirty()
            metrics = await asyncio.to_thread(state.scene.metrics)
        return HistoryResponse(ok=ok, count=state.scene.count(), metrics=metrics)

    @router.post("/redo", response_model=HistoryResponse)
    async def redo(req: SceneRequest):
        state = _require(req.scene_id)
        async with state.lock:
            ok = await asyncio.to_thread(state.scene.redo)
            if ok:
                state.mark_dirty()
            metrics = await asyncio.to_thread(state.scene.metrics)
        return HistoryResponse(ok=ok, count=state.scene.count(), metrics=metrics)

    # ---- GET /agent/skills : the shared skills vocabulary (R10/R11) ------ #
    @router.get("/agent/skills")
    async def agent_skills(stage: str = Query("clean")):
        from backend.agent.system_prompt import skills_for

        resolved = "understand" if stage == "understand" else "clean"
        return {"stage": resolved, "skills": skills_for(resolved)}

    # ---- GET /config/providers : the model picker's registry (R-modelpicker) #
    @router.get("/config/providers")
    async def config_providers():
        return {"providers": providers_public()}

    # ---- GET/POST /config/model : current selection / save a new one ----- #
    @router.get("/config/model", response_model=ModelConfigResponse)
    async def get_model_config():
        return ModelConfigResponse(**settings.public())

    @router.post("/config/model", response_model=ModelConfigResponse)
    async def set_model_config(req: ModelConfigRequest):
        try:
            settings.update(
                preset=req.preset,
                model=req.model,
                api_key=req.api_key if req.api_key is not None else UNSET,
                base_url=req.base_url,
            )
        except UnknownPresetError:
            raise HTTPException(status_code=400, detail=f"unknown preset {req.preset!r}")
        return ModelConfigResponse(**settings.public())

    # ---- POST /config/test : cheap live round-trip for the "Test" button - #
    @router.post("/config/test", response_model=TestConnectionResponse)
    async def test_model_config(req: TestConnectionRequest):
        from backend.providers import get_provider
        from backend.providers.errors import ProviderConfigError

        cfg = settings.resolve()
        preset = req.preset or cfg.preset
        entry = registry_entry(preset)
        if entry is None:
            return TestConnectionResponse(ok=False, error=f"unknown preset {preset!r}")

        provider_name = entry["provider"]
        model = req.model or cfg.model
        api_key = req.api_key if req.api_key else cfg.api_key
        base_url = req.base_url if req.base_url is not None else cfg.base_url

        try:
            provider = get_provider(provider_name, model, api_key=api_key, base_url=base_url)
            await asyncio.wait_for(
                asyncio.to_thread(
                    provider.generate,
                    [{"role": "user", "content": "Reply with the single word OK."}],
                    [],
                ),
                timeout=_TEST_TIMEOUT_S,
            )
            return TestConnectionResponse(ok=True, model=model)
        except ProviderConfigError as exc:
            return TestConnectionResponse(ok=False, error=_redact(str(exc), api_key))
        except TimeoutError:
            return TestConnectionResponse(ok=False, error="Timed out waiting for a response.")
        except Exception as exc:  # noqa: BLE001 - surface as a friendly test failure, not a 500
            return TestConnectionResponse(ok=False, error=_redact(str(exc)[:300], api_key))

    # ---- POST /agent/run : kick off the loop (streams over WS) ----------- #
    @router.post("/agent/run", response_model=AgentRunResponse)
    async def agent_run(req: AgentRunRequest):
        state = _require(req.scene_id)
        existing = _active_runs.get(req.scene_id)
        if existing is not None and not existing.done():
            raise HTTPException(
                status_code=409,
                detail="an agent run is already active for this scene — "
                       "stop it or wait for it to finish",
            )
        if not manager.is_connected(req.scene_id):
            raise HTTPException(
                status_code=409,
                detail="no renderer connected for this scene — completion events "
                       "would be dropped silently; open the viewer first",
            )
        # Stale stop/pause signals from the previous run's end-race window must
        # not kill or invisibly pause this run's first action.
        manager.reset_run_flags(req.scene_id)
        # Bind the run to the window that asked for it: with the editor AND the
        # analyst open on one scene, the run's tools must execute in the
        # renderer whose operator started it. Unnamed falls back to the sole
        # connected client.
        if req.client_id is not None and req.client_id not in manager.clients(req.scene_id):
            raise HTTPException(
                status_code=409,
                detail=f"client {req.client_id!r} has no renderer connected for this scene",
            )
        channel = WSChannel(req.scene_id, manager, req.client_id)

        async def _drive():
            try:
                await runner.run(req.prompt, state.scene, channel, stage=req.stage)
            except Exception as exc:  # surface failures as a trace event
                await manager.emit_event(req.scene_id, "complete", {"error": str(exc)})

        task = asyncio.create_task(_drive())
        _runs.add(task)
        _active_runs[req.scene_id] = task

        def _cleanup(t: asyncio.Task, sid: str = req.scene_id) -> None:
            _runs.discard(t)
            if _active_runs.get(sid) is t:
                _active_runs.pop(sid, None)

        task.add_done_callback(_cleanup)
        return AgentRunResponse(run_id=uuid.uuid4().hex, status="started")

    # ---- WS /ws/{scene_id} : renderer channel ---------------------------- #
    # `?client=` identifies the WINDOW. Two windows (editor + analyst) are two
    # renderers on one scene; without it they evict each other's socket.
    @router.websocket("/ws/{scene_id}")
    async def scene_ws(websocket: WebSocket, scene_id: str, client: str = Query(DEFAULT_CLIENT)):
        await manager.connect(scene_id, websocket, client)
        try:
            while True:
                message = await websocket.receive_json()
                manager.handle_message(scene_id, message)
        except WebSocketDisconnect:
            manager.disconnect(scene_id, websocket, client)
        except Exception:
            manager.disconnect(scene_id, websocket, client)

    return router


__all__ = ["create_router"]
