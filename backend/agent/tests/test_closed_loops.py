"""Tier-4 closed-loop tests: detect->fix->verify->keep/undo + flagship (§7)."""

from __future__ import annotations

import asyncio

from backend.agent import ToolDispatcher, run_fix_verify
from backend.agent.closed_loops import flagship_floater_cleanup
from backend.agent.mocks import MockBackendExecutor, MockFrontendChannel


def _run(coro):
    return asyncio.run(coro)


def _dispatcher(worsen=False):
    return ToolDispatcher(MockBackendExecutor(worsen=worsen), MockFrontendChannel())


def test_run_fix_verify_keeps_on_improvement():
    d = _dispatcher()
    outcome = _run(run_fix_verify(d, "floaters"))
    assert outcome.kept is True
    assert outcome.after < outcome.before
    assert outcome.attempts == 1


def test_run_fix_verify_reverts_when_no_improvement():
    d = _dispatcher(worsen=True)
    outcome = _run(run_fix_verify(d, "outliers", max_retries=2))
    assert outcome.kept is False
    assert outcome.attempts == 3  # baseline + 2 retries, all reverted


def test_flagship_floater_cleanup_reports_before_after():
    d = _dispatcher()
    summary = _run(flagship_floater_cleanup(d))
    assert summary["kept_any"] is True
    assert summary["after"]["outlierFraction"] < summary["before"]["outlierFraction"]
    assert summary["after"]["nearTransparentFraction"] < summary["before"]["nearTransparentFraction"]
    assert summary["captured_before"] >= 1 and summary["captured_after"] >= 1
    assert summary["regions"] >= 1


def test_flagship_emits_narration_and_marker():
    channel = MockFrontendChannel()
    d = ToolDispatcher(MockBackendExecutor(), channel)
    _run(flagship_floater_cleanup(d))
    assert any(e["type"] == "narrate" for e in channel.events)
    assert "drop_marker" in channel.command_tools()
    assert "look_at" in channel.command_tools()
