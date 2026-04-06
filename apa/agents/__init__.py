"""
Agent contract.

Every agent directory should contain:
  agent.py  — implements run(instruction: str) -> AgentResult
  server.py — A2A HTTP server exposing the agent
"""

from dataclasses import dataclass


@dataclass
class AgentResult:
    success: bool
    session_id: str
    output: str
    error: str | None = None
