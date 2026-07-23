"""The system prompt must reach the provider exactly once. RealAgentRunner
passes it as the provider's system_instruction; with system_prompt="" the loop
must not ALSO seed messages[0] with the same text."""

from __future__ import annotations

import asyncio

from backend.agent import AgentLoop, ToolDispatcher
from backend.agent.mocks import MockBackendExecutor, MockFrontendChannel, MockProvider, tool_turn


def _run(coro):
    return asyncio.run(coro)


class RecordingProvider(MockProvider):
    def __init__(self, script):
        super().__init__(script)
        self.seen: list[list[dict]] = []

    def generate(self, messages, tools, images=None):
        self.seen.append([dict(m) for m in messages])
        return super().generate(messages, tools, images)


def _drive(system_prompt):
    channel = MockFrontendChannel()
    provider = RecordingProvider([tool_turn(("answer", {"text": "ok"}))])
    loop = AgentLoop(
        provider, ToolDispatcher(MockBackendExecutor(), channel), channel,
        stage="understand", system_prompt=system_prompt,
    )
    _run(loop.run("hello"))
    return [m["role"] for m in provider.seen[0]]


def test_empty_system_prompt_seeds_no_system_message():
    roles = _drive("")
    assert "system" not in roles


def test_default_still_seeds_exactly_one_system_message_first():
    roles = _drive(None)
    assert roles.count("system") == 1 and roles[0] == "system"
