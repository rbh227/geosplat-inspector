"""U10 pause/takeover (KTD9, R14, AE1): the loop holds at the next tool-call
boundary on pause, resumes on the explicit signal, and aborts on interrupt."""

from __future__ import annotations

import asyncio

from backend.agent.config import AgentConfig
from backend.agent.loop import AgentLoop
from backend.agent.mocks import MockBackendExecutor, MockFrontendChannel, MockProvider, tool_turn
from backend.agent.dispatch import ToolDispatcher


class PausableChannel(MockFrontendChannel):
    """Mock channel with the WSChannel pause/interrupt surface."""

    def __init__(self) -> None:
        super().__init__()
        self._paused = False
        self._interrupted = False
        self._resume = asyncio.Event()
        self.wait_resume_calls = 0

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def interrupted(self) -> bool:  # consume-once, like WSChannel
        if self._interrupted:
            self._interrupted = False
            return True
        return False

    async def wait_resume(self) -> None:
        self.wait_resume_calls += 1
        await self._resume.wait()


def _loop(provider, channel):
    dispatcher = ToolDispatcher(MockBackendExecutor(), channel)
    config = AgentConfig(enforce_grounding=False)
    return AgentLoop(provider, dispatcher, channel, config=config)


def test_pause_holds_between_tool_calls_then_resumes():
    channel = PausableChannel()
    provider = MockProvider(script=[
        tool_turn(("scan_pause", {"ms": 1})),
        tool_turn(("answer", {"text": "done"})),
    ])
    loop = _loop(provider, channel)

    async def scenario():
        channel._paused = True  # operator input arrived before the run's first checkpoint

        async def release():
            await asyncio.sleep(0.05)
            channel._paused = False
            channel._resume.set()

        releaser = asyncio.create_task(release())
        result = await loop.run("clean")
        await releaser
        return result

    result = asyncio.run(scenario())
    assert result.status == "answered"
    assert channel.wait_resume_calls == 1
    narrations = [e.get("text", "") for e in result.trace if e.get("type") == "narrate"]
    assert any("Paused" in t for t in narrations)
    assert any("Resumed" in t for t in narrations)


def test_pause_takes_effect_after_the_current_call_not_mid_call():
    """KTD9: no mid-call interruption — the in-flight tool finishes first."""
    channel = PausableChannel()

    def pause_during_first_call(messages, tools, images):  # noqa: ANN001
        return tool_turn(("scan_pause", {"ms": 1}))

    provider = MockProvider(script=[
        pause_during_first_call,
        tool_turn(("answer", {"text": "done"})),
    ])
    loop = _loop(provider, channel)

    async def scenario():
        async def pause_then_release():
            channel._paused = True
            await asyncio.sleep(0.05)
            channel._paused = False
            channel._resume.set()

        task = asyncio.create_task(pause_then_release())
        result = await loop.run("go")
        await task
        return result

    result = asyncio.run(scenario())
    assert result.status == "answered"
    # the first tool call completed (its result is in the trace) BEFORE the pause held
    tool_results = [e for e in result.trace if e.get("type") == "tool_result"]
    assert tool_results and tool_results[0]["name"] == "scan_pause"


def test_interrupt_during_pause_aborts_the_run():
    channel = PausableChannel()
    provider = MockProvider(script=[
        tool_turn(("scan_pause", {"ms": 1})),
        tool_turn(("scan_pause", {"ms": 1})),
    ])
    loop = _loop(provider, channel)

    async def scenario():
        channel._paused = True

        async def stop():
            await asyncio.sleep(0.05)
            channel._interrupted = True
            channel._paused = False
            channel._resume.set()

        stopper = asyncio.create_task(stop())
        result = await loop.run("go")
        await stopper
        return result

    result = asyncio.run(scenario())
    assert result.status == "interrupted"


def test_channels_without_pause_support_run_unchanged():
    channel = MockFrontendChannel()
    provider = MockProvider(script=[tool_turn(("answer", {"text": "done"}))])
    loop = _loop(provider, channel)
    result = asyncio.run(loop.run("go"))
    assert result.status == "answered"
