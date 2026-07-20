"""Agent loop configuration and bounded-step limits (Risks R4, R5)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AgentConfig:
    # Hard stops so a runaway model can't loop forever or burn the free tier.
    max_steps: int = 20            # total model turns per run
    max_vision_calls: int = 8      # total capture_frame/capture_orbit dispatches
    max_retries_per_problem: int = 2  # loosen-and-retry budget for a fix (R4/R5)

    # Behaviour toggles.
    verify_after_edit: bool = True  # inject re-measure + keep/undo after edits
    enforce_grounding: bool = True  # answer must be backed by measurement/sight

    # Default animation pacing (ms) — visible, robot-inspector feel.
    default_move_ms: int = 1200
    default_scan_ms: int = 800


__all__ = ["AgentConfig"]
