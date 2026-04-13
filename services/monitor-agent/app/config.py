"""
Simplified configuration module for monitor-agent.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.configs.environment_vars.agent_settings import agent_settings
from app.configs.environment_vars.model_settings import model_settings
from app.configs.environment_vars.aiplatform_settings import aiplatform_settings
from app.configs.environment_vars.general_settings import general_settings
from app.configs.environment_vars.a2a_settings import a2a_settings
from app.configs.environment_vars.observability_settings import observability_settings

from app.tools import discover_local_mcp_tools

logger = logging.getLogger(__name__)


class AppConfig:

    @staticmethod
    def get_api_key() -> str:
        api_key = os.getenv("AIPLATFORM_API_KEY")
        if not api_key:
            raise ValueError("AIPLATFORM_API_KEY is not set")
        return api_key

    @staticmethod
    def get_system_prompt() -> str:
        try:
            prompt_file = os.getenv("AGENT_SYSTEM_PROMPT_FILE", "app/prompts/agent_system_prompt.txt")
            if os.path.exists(prompt_file):
                with open(prompt_file, "r", encoding="utf-8") as f:
                    content = f.read()
                if content.strip():
                    logger.info("Using system prompt from file: %s", prompt_file)
                    return content.strip()
        except Exception as e:
            logger.warning("Failed to load prompt file: %s", e)

        env_prompt = os.getenv("AGENT_SYSTEM_PROMPT")
        if env_prompt and env_prompt.strip():
            return env_prompt.strip()

        return "You are a helpful observability assistant."

    @staticmethod
    def get_agent_config():
        return agent_settings

    @staticmethod
    def get_model_config():
        return model_settings

    @staticmethod
    def get_platform_config():
        return aiplatform_settings

    @staticmethod
    def get_general_config():
        return general_settings

    @staticmethod
    def get_a2a_config():
        return a2a_settings

    @staticmethod
    def get_observability_config():
        return observability_settings

    @staticmethod
    def create_external_mcp_servers() -> dict:
        """Monitor-agent has no external stdio MCP servers."""
        return {}

    @staticmethod
    def get_allowed_tools() -> list[str] | None:
        """Restrict to local MCP tools only — no shell, web, or file access."""
        from app.tools import get_tool_names
        names = get_tool_names()
        return names or None

    @staticmethod
    def create_local_mcp_server() -> Any:
        from claude_agent_sdk import create_sdk_mcp_server

        tools = discover_local_mcp_tools()
        if not tools:
            logger.warning("No MCP tools discovered for local server")
            return None

        return create_sdk_mcp_server(
            name="local_tools",
            version="1.0.0",
            tools=tools,
        )


__all__ = ["AppConfig"]
