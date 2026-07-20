"""GeoSplat Inspector backend — app entrypoint (Agent 4).

Wires the transport layer (REST + WebSocket) over the frozen contracts. The
splat/analysis engines (Agents 1/2) and the agent loop (Agent 3) are injected
through the `engine.py` seams; until they land, the swappable stubs provide a
real, testable end-to-end path. Model provider/name come from env
(`MODEL_PROVIDER`, `MODEL_NAME`); the API key is read from env only, never
baked into the image.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.engine import AgentRunner, SceneBackend
from backend.api.routes import create_router
from backend.api.settings import get_store
from backend.api.state import SceneStore
from backend.api.stub_agent import StubAgentRunner
from backend.api.stub_engine import StubBackend
from backend.api.ws import ConnectionManager


def _select_backend() -> SceneBackend:
    """Integration seam: real composed engine (Agent 1+2), stub as fallback."""
    try:
        from backend.api.real_engine import RealBackend

        return RealBackend()
    except Exception as exc:  # pragma: no cover - defensive boot guard
        print(f"[engine] real engine unavailable ({exc!r}); using stub", flush=True)
        return StubBackend()


def _select_runner() -> AgentRunner:
    """Integration seam: Agent 3's loop (provider chosen via env), stub fallback."""
    try:
        from backend.api.real_engine import RealAgentRunner

        return RealAgentRunner()
    except Exception as exc:  # pragma: no cover - defensive boot guard
        print(f"[agent] real runner unavailable ({exc!r}); using stub", flush=True)
        return StubAgentRunner()


def create_app() -> FastAPI:
    app = FastAPI(title="GeoSplat Inspector", version="0.1.0")

    # local-only tool, but /config/model can now accept a pasted API key, so
    # CORS is scoped to the known dev-server origins rather than "*".
    dev_origins = os.environ.get(
        "SPLATAGENT_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=dev_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    store = SceneStore(_select_backend())
    manager = ConnectionManager()
    runner = _select_runner()
    settings = get_store()

    # shared singletons (handy for tests / future wiring)
    app.state.store = store
    app.state.manager = manager
    app.state.runner = runner
    app.state.settings = settings

    @app.get("/health")
    async def health():
        cfg = settings.resolve()
        return {
            "status": "ok",
            "scenes": len(store),
            "provider": cfg.provider,
            "model": cfg.model,
        }

    app.include_router(create_router(store, manager, runner, settings))

    # serve the built frontend if present (co-run a single `docker compose up`)
    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    from fastapi.staticfiles import StaticFiles

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for candidate in (os.path.join(here, "frontend", "dist"), os.path.join(here, "dist")):
        if os.path.isdir(candidate):
            # mounted last, so API + WS routes take precedence
            app.mount("/", StaticFiles(directory=candidate, html=True), name="frontend")
            break


app = create_app()
