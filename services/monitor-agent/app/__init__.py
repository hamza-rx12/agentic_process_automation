"""
A2A-Claude-Agent package (standalone).

This package contains a self-contained, A2A-protocol-compliant server agent scaffold
built on the Claude Agent SDK. The code is intentionally skeletal and includes TODO
comments showing exactly where to integrate your Claude client, agent/assistant,
tools, and message conversion logic.

Key modules:
- app/__main__.py
  - A2A server bootstrap (build AgentCard, wire DefaultRequestHandler, start Uvicorn)
  - Reads environment variables (AIPLATFORM_API_KEY, AIPLATFORM_BASE_URL, AIPLATFORM_TIMEOUT, AGENT_NAME, PORT, HOST_OVERRIDE, STREAMING)
- app/agent.py
  - Your Claude Agent SDK runtime (create/load agent/assistant, optional tools)
  - Public methods for invoke(...) and stream(...)
- app/agent_executor.py
  - Bridges A2A RequestContext <-> your Claude runtime
  - Implements conversion utilities between A2A Parts and Claude message payloads/results
  - Drives A2A Task lifecycle (submit/start_work/working/add_artifact/complete)

Docs:
- Claude Agent SDK: https://docs.anthropic.com/claude/docs/claude-sdks
- A2A protocol endpoints are provided by a2a-sdk (AgentCard discovery + sendMessage handling).
"""

# Expose symbols when users import from app
# NOTE: These imports will work after you implement the stubs.
# They are optional; remove if you prefer explicit imports by path.
try:
    from .agent import ClaudeAIAgent  # noqa: F401
    from .a2a_core.agent_executor import ClaudeAIAgentExecutor  # noqa: F401
except Exception:
    # During initial scaffolding or partial implementations these may fail to import.
    # It's fine; importing the package shouldn't break the environment.
    pass