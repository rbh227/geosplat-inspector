"""Single forced-choice model calls for the CleanupController (spec §4).

Every call: fresh context — one short user instruction, one image, exactly one
tool schema. Bounded retries, then None; the caller substitutes a safe default
('unsure'). The run can therefore never stall on the model.
"""
from __future__ import annotations

import asyncio
from typing import Any

from backend.contracts import ModelProvider, ToolSpec


async def ask_forced(
    provider: ModelProvider,
    instruction: str,
    tool_spec: dict,
    image: bytes | None = None,
    *,
    timeout_s: float = 45.0,
    retries: int = 1,
) -> dict[str, Any] | None:
    spec = ToolSpec(
        name=tool_spec["name"],
        description=tool_spec.get("description", ""),
        parameters=tool_spec["parameters"],
    )
    messages = [{"role": "user", "content": instruction}]
    images = [image] if image else None
    for _ in range(retries + 1):
        try:
            resp = await asyncio.wait_for(
                asyncio.to_thread(provider.generate, messages, [spec], images),
                timeout=timeout_s,
            )
        except Exception:  # noqa: BLE001 — timeout, provider error: safe None
            continue
        for call in resp.tool_calls or []:
            if call.name == spec.name and isinstance(call.args, dict):
                return call.args
    return None
