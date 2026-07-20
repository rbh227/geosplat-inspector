"""Agent 4 — transport layer: FastAPI REST + WebSocket over the frozen contracts.

This package owns the HTTP/WS surface and scene state. It imports the engines
(Agents 1/2) and the agent loop (Agent 3) only through the Protocols in
`engine.py`; concrete wiring happens at integration. Stub implementations live
in `stub_engine.py` / `stub_agent.py` and are swapped for the real engines
without touching routes.
"""
