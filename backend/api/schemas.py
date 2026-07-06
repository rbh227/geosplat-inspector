"""Pydantic request/response models for the REST surface (§6.7).

`Metrics` is the frozen TypedDict; responses carry it as a plain dict so the
transport layer stays decoupled from the analysis engine's concrete types.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class UploadResponse(BaseModel):
    id: str
    metrics: dict[str, Any]


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


class AgentRunResponse(BaseModel):
    run_id: str
    status: str


__all__ = [
    "UploadResponse",
    "EditRequest",
    "EditResponse",
    "SceneRequest",
    "HistoryResponse",
    "AgentRunRequest",
    "AgentRunResponse",
]
