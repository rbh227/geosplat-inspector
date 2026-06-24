"""GeoSplat Inspector agent: perceive->act->verify loop, dispatch, closed loops.

Public surface used by Agent 4 (API server) at integration:

    from backend.agent import AgentLoop, ToolDispatcher, AgentConfig
    from backend.providers import get_provider

    dispatcher = ToolDispatcher(engine, channel)        # engine: BackendExecutor
    loop = AgentLoop(get_provider(system_instruction=SYSTEM_PROMPT), dispatcher, channel)
    result = await loop.run(prompt)

Everything imports from the frozen `/backend/contracts`; nothing here edits it.
"""

from .capabilities import CAPABILITIES, capability_index
from .closed_loops import flagship_floater_cleanup, run_fix_verify
from .config import AgentConfig
from .dispatch import BackendExecutor, ToolDispatcher
from .grounding import GroundingError, GroundingLedger
from .loop import AgentLoop
from .system_prompt import SYSTEM_PROMPT, build_tool_specs
from .types import LoopResult, ProblemRegion
from .verify import verify_edit

__all__ = [
    "AgentLoop",
    "AgentConfig",
    "ToolDispatcher",
    "BackendExecutor",
    "GroundingLedger",
    "GroundingError",
    "LoopResult",
    "ProblemRegion",
    "SYSTEM_PROMPT",
    "build_tool_specs",
    "verify_edit",
    "run_fix_verify",
    "flagship_floater_cleanup",
    "CAPABILITIES",
    "capability_index",
]
