"""
AgentCard builder for the A2A server.

Constructs the AgentCard advertised by this server with capabilities,
skills, and supported content types.
"""

from __future__ import annotations
from typing import Sequence

from a2a.types import AgentCapabilities, AgentCard, AgentSkill
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
    push_notifications: bool = False,
    skills: Sequence[AgentSkill] | None = None,
) -> AgentCard:
    """Construct the AgentCard advertised by this server.
    
    All fields can be customized via parameters; sensible defaults are provided.
    If skills is not provided, a hardcoded default skill will be used.
    """
    # Avoid mutable defaults: resolve sequences
    input_modes = list(default_input_modes) if default_input_modes is not None else ["text/plain"]
    output_modes = list(default_output_modes) if default_output_modes is not None else ["text/plain"]

    capabilities = AgentCapabilities(streaming=streaming, push_notifications=push_notifications)

    # Use provided skills or fall back to hardcoded default
    if not skills:
        skills_list = [get_default_skill()]
    else:
        skills_list = list(skills)

    return AgentCard(
        name=agent_name,
        description=description,
        url=public_url,
        version=version,
        default_input_modes=input_modes,
        default_output_modes=output_modes,
        capabilities=capabilities,
        skills=skills_list,
    )
