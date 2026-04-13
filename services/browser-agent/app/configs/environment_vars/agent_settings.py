"""
AgentSettings: Agent-related configuration loaded from environment.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional
from ._env import env_bool, env_csv, env_int

@dataclass(frozen=True)
class AgentSettings:
    AGENT_NAME: str
    AGENT_SYSTEM_PROMPT: str
    AGENT_SYSTEM_PROMPT_NAME: str

    # Claude Agent SDK permission and settings options
    AGENT_PERMISSION_MODE: Optional[str] = None
    AGENT_SETTING_SOURCES: Optional[list] = None
    AGENT_DISALLOWED_TOOLS: Optional[list] = None
    AGENT_CWD: Optional[str] = None
    AGENT_MAX_TURNS: Optional[int] = None

    # Tool callback configuration
    USE_TOOL_CALLBACK: bool = False
    TOOL_CALLBACK_METHOD: Optional[str] = None

def load_agent_settings() -> AgentSettings:
    return AgentSettings(
        AGENT_NAME=os.getenv("AGENT_NAME", "Assistant Agent"),
        AGENT_SYSTEM_PROMPT=os.getenv("AGENT_SYSTEM_PROMPT", "You are a helpful AI assistant."),
        AGENT_SYSTEM_PROMPT_NAME=os.getenv("AGENT_SYSTEM_PROMPT_NAME", "AGENT_SYSTEM_PROMPT"),
        AGENT_PERMISSION_MODE=os.getenv("AGENT_PERMISSION_MODE"),
        AGENT_SETTING_SOURCES=env_csv("AGENT_SETTING_SOURCES", []) if os.getenv("AGENT_SETTING_SOURCES") else None,
        AGENT_DISALLOWED_TOOLS=env_csv("AGENT_DISALLOWED_TOOLS", []) if os.getenv("AGENT_DISALLOWED_TOOLS") else None,
        AGENT_CWD=os.getenv("AGENT_CWD"),
        AGENT_MAX_TURNS=env_int("AGENT_MAX_TURNS", 0) if os.getenv("AGENT_MAX_TURNS") else None,
        USE_TOOL_CALLBACK=env_bool("USE_TOOL_CALLBACK", default=False),
        TOOL_CALLBACK_METHOD=os.getenv("TOOL_CALLBACK_METHOD"),
    )




# Singleton settings object used across the app
agent_settings: AgentSettings = load_agent_settings()