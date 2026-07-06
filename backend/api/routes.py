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
    SceneRequest,
    UploadResponse,
)
from backend.api.state import SceneStore
from backend.api.ws import ConnectionManager, WSChannel

_UPLOAD_CHUNK = 1024 * 1024  # 1 MiB streaming copy


def create_router(
    store: SceneStore,
    manager: ConnectionManager,
    runner: AgentRunner,
) -> APIRouter:
    router = APIRouter()
    _runs: set[asyncio.Task] = set()  # keep background runs from being GC'd

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
        return UploadResponse(id=state.id, metrics=state.scene.metrics())

    # ---- GET /scene/{id}.ply : chunked serve of the current alive set ---- #
    @router.get("/scene/{scene_id}.ply")
    async def get_scene_ply(scene_id: str):
        state = _require(scene_id)
        async with state.lock:
            path = state.current_ply_path()
        return FileResponse(
            path,
            media_type="application/octet-stream",
            filename=f"{scene_id}.ply",
        )

    # ---- GET /ids : alive original Gaussian ids (v0.2) ------------------- #
    # After a backend-driven reload the frontend adopts these so its stable
    # ID map matches the backend's ID space (packed index i <-> i-th entry).
    @router.get("/ids")
    async def get_alive_ids(scene_id: str = Query(...)):
        state = _require(scene_id)
        async with state.lock:
            ids = state.scene.alive_ids()
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
        return state.scene.metrics(parsed)

    # ---- POST /edit : mutate alive set -> counts + metrics --------------- #
    @router.post("/edit", response_model=EditResponse)
    async def edit_scene(req: EditRequest):
        state = _require(req.scene_id)
        async with state.lock:
            try:
                before, after = state.scene.edit(req.op, req.params, req.selection)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            state.mark_dirty()
            metrics = state.scene.metrics()
        return EditResponse(before=before, after=after, metrics=metrics)

    # ---- POST /undo, /redo ----------------------------------------------- #
    @router.post("/undo", response_model=HistoryResponse)
    async def undo(req: SceneRequest):
        state = _require(req.scene_id)
        async with state.lock:
            ok = state.scene.undo()
            if ok:
                state.mark_dirty()
            metrics = state.scene.metrics()
        return HistoryResponse(ok=ok, count=state.scene.count(), metrics=metrics)

    @router.post("/redo", response_model=HistoryResponse)
    async def redo(req: SceneRequest):
        state = _require(req.scene_id)
        async with state.lock:
            ok = state.scene.redo()
            if ok:
                state.mark_dirty()
            metrics = state.scene.metrics()
        return HistoryResponse(ok=ok, count=state.scene.count(), metrics=metrics)

    # ---- GET /agent/skills : the shared skills vocabulary (R10/R11) ------ #
    @router.get("/agent/skills")
    async def agent_skills(stage: str = Query("clean")):
        from backend.agent.system_prompt import skills_for

        resolved = "understand" if stage == "understand" else "clean"
        return {"stage": resolved, "skills": skills_for(resolved)}

    # ---- POST /agent/run : kick off the loop (streams over WS) ----------- #
    @router.post("/agent/run", response_model=AgentRunResponse)
    async def agent_run(req: AgentRunRequest):
        state = _require(req.scene_id)
        channel = WSChannel(req.scene_id, manager)

        async def _drive():
            try:
                await runner.run(req.prompt, state.scene, channel, stage=req.stage)
            except Exception as exc:  # surface failures as a trace event
                await manager.emit_event(req.scene_id, "complete", {"error": str(exc)})

        task = asyncio.create_task(_drive())
        _runs.add(task)
        task.add_done_callback(_runs.discard)
        return AgentRunResponse(run_id=uuid.uuid4().hex, status="started")

    # ---- WS /ws/{scene_id} : renderer channel ---------------------------- #
    @router.websocket("/ws/{scene_id}")
    async def scene_ws(websocket: WebSocket, scene_id: str):
        await manager.connect(scene_id, websocket)
        try:
            while True:
                message = await websocket.receive_json()
                manager.handle_message(scene_id, message)
        except WebSocketDisconnect:
            manager.disconnect(scene_id)
        except Exception:
            manager.disconnect(scene_id)

    return router


__all__ = ["create_router"]
