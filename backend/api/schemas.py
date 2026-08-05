"""Pydantic request/response models for the REST surface (§6.7).

`Metrics` is the frozen TypedDict; responses carry it as a plain dict so the
transport layer stays decoupled from the analysis engine's concrete types.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class UploadResponse(BaseModel):
    id: str
    count: int


class EditRequest(BaseModel):
    scene_id: str
    op: str
    params: dict[str, Any] = Field(default_factory=dict)
    selection: dict[str, Any] | None = None


class EditResponse(BaseModel):
    before: int
    after: int
    metrics: dict[str, Any]


class SceneRequest(BaseModel):
    scene_id: str


class HistoryResponse(BaseModel):
    ok: bool
    count: int
    metrics: dict[str, Any]


class AgentRunRequest(BaseModel):
    scene_id: str
    prompt: str
    # v0.2 (R12): operator-selected workflow stage; gates the agent's tool surface.
    stage: Literal["clean", "understand"] = "clean"
    # Which window's renderer runs this. Two windows (editor + analyst) can be
    # open on one scene; None falls back to the sole connected renderer.
    client_id: str | None = None
    # v0.7 (judgment-tour cleanup): "cleanup" routes a Clean-stage run to the
    # app-owned CleanupController instead of the freeform loop. The backend
    # also routes a bare "cleanup_scene" prompt there, so typing works too.
    mode: str | None = None


class AgentRunResponse(BaseModel):
    run_id: str
    status: str


# ---- Model settings (in-app model picker) ---------------------------------
# NOTE: no request/response model here ever carries a bare `api_key` field in
# a *response* — ModelConfigResponse only reports whether one is set.

class ModelConfigRequest(BaseModel):
    preset: str
    model: str | None = None
    api_key: str | None = None  # omit to keep the existing key; "" clears it
    base_url: str | None = None


class ModelConfigResponse(BaseModel):
    preset: str
    provider: str
    model: str | None
    base_url: str | None
    key_set: bool
    key_source: str | None
    source: str


class TestConnectionRequest(BaseModel):
    preset: str | None = None
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None


class TestConnectionResponse(BaseModel):
    ok: bool
    model: str | None = None
    error: str | None = None


__all__ = [
    "UploadResponse",
    "EditRequest",
    "EditResponse",
    "SceneRequest",
    "HistoryResponse",
    "AgentRunRequest",
    "AgentRunResponse",
    "ModelConfigRequest",
    "ModelConfigResponse",
    "TestConnectionRequest",
    "TestConnectionResponse",
]
