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

    # local-only tool: permissive CORS so the Vite dev server can call the API
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    store = SceneStore(_select_backend())
    manager = ConnectionManager()
    runner = _select_runner()

    # shared singletons (handy for tests / future wiring)
    app.state.store = store
    app.state.manager = manager
    app.state.runner = runner

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "scenes": len(store),
            "provider": os.environ.get("MODEL_PROVIDER", "gemini"),
            "model": os.environ.get("MODEL_NAME", "gemini-2.5-flash"),
        }

    app.include_router(create_router(store, manager, runner))

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
