"""
AgentCard builder for the A2A server.
"""

from __future__ import annotations
from typing import Sequence

from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from app.common.utils import get_default_skill

def build_agent_card(
    agent_name: str,
    public_url: str,
    streaming: bool = True,
    *,
    description: str = "A2A-compliant agent powered by the Claude Agent SDK for chat.",
    version: str = "1.0.0",
    default_input_modes: Sequence[str] | None = None,
    default_output_modes: Sequence[str] | None = None,
    skills: Sequence[AgentSkill] | None = None,
) -> AgentCard:
    input_modes = list(default_input_modes) if default_input_modes is not None else ["text/plain"]
    output_modes = list(default_output_modes) if default_output_modes is not None else ["text/plain"]

    capabilities = AgentCapabilities(streaming=streaming)

    if not skills:
        skills_list = [get_default_skill()]
    else:
        skills_list = list(skills)

    return AgentCard(
        name=agent_name,
        description=description,
        version=version,
        default_input_modes=input_modes,
        default_output_modes=output_modes,
        capabilities=capabilities,
        supported_interfaces=[AgentInterface(url=public_url, protocol_binding='JSONRPC')],
        skills=skills_list,
    )
