"""
Simplified configuration module that consolidates all environment access.

This replaces the over-engineered interfaces/providers/factories pattern
with direct, well-organized configuration access.
"""

from __future__ import annotations

import logging
from typing import Any

# Configuration imports (domain-specific, well-structured)
from app.configs.environment_vars.agent_settings import agent_settings
from app.configs.environment_vars.model_settings import model_settings
from app.configs.environment_vars.aiplatform_settings import aiplatform_settings
from app.configs.environment_vars.general_settings import general_settings
from app.configs.environment_vars.a2a_settings import a2a_settings
from app.configs.environment_vars.database_settings import database_settings
from app.configs.environment_vars.dispatch_settings import dispatch_settings
import os


# MCP support
from app.tools import discover_local_mcp_tools

logger = logging.getLogger(__name__)


class AppConfig:
    """
    Simplified configuration access that replaces the dependency injection pattern.

    All configuration access goes through this single class, maintaining modularity
    without the overhead of interfaces, providers, and factories.
    """

    @staticmethod
    def get_api_key() -> str:
        """Get the API key from environment variables."""
        api_key = os.getenv("AIPLATFORM_API_KEY")
        if not api_key:
            raise ValueError("AIPLATFORM_API_KEY is not set")
        return api_key

    
    @staticmethod
    def get_system_prompt() -> str:
        """Get the system prompt from file or .env environment variable."""
        
        # First try to load from file
        try:
            prompt_file = os.getenv("AGENT_SYSTEM_PROMPT_FILE", "app/prompts/agent_system_prompt.txt")
            if os.path.exists(prompt_file):
                with open(prompt_file, "r", encoding="utf-8") as f:
                    file_content = f.read()
                
                # Normalize the content for agent consumption
                normalized_prompt = AppConfig._normalize_prompt_string(file_content)
                
                if normalized_prompt.strip():
                    logger.info(f"Using system prompt from file: {prompt_file}")
                    return normalized_prompt.strip()
        except Exception as e:
            logger.warning(f"Failed to load prompt file: {e}")
        
        # Fall back to .env environment variable
        env_prompt = os.getenv("AGENT_SYSTEM_PROMPT")
        if env_prompt and env_prompt.strip():
            logger.info("Using system prompt from .env file")
            return env_prompt.strip()
        
        # Final fallback to default
        logger.info("No prompt found in file or .env, using default")
        return "You are a helpful AI assistant."

    @staticmethod
    def _normalize_prompt_string(prompt_content: str) -> str:
        """Normalize prompt content to single-line format for agent consumption."""
        
        # Remove BOM if present
        if prompt_content.startswith('\ufeff'):
            prompt_content = prompt_content[1:]
        
        # Replace arrow characters with text equivalents for better compatibility
        prompt_content = prompt_content.replace('→', '->')
        
        # Replace all newlines with spaces to create single-line format
        # This converts the multi-line file to the same format as .env
        prompt_content = prompt_content.replace('\r\n', ' ').replace('\r', ' ').replace('\n', ' ')
        
        # Clean up multiple spaces and tabs
        import re
        prompt_content = re.sub(r'\s+', ' ', prompt_content)
        
        # Remove any markdown formatting that might interfere
        # Keep the content but remove headers, bold, etc.
        prompt_content = re.sub(r'#{1,6}\s*', '', prompt_content)  # Remove headers
        prompt_content = re.sub(r'\*\*(.*?)\*\*', r'\1', prompt_content)  # Remove bold
        prompt_content = re.sub(r'\*(.*?)\*', r'\1', prompt_content)  # Remove italic
        prompt_content = re.sub(r'-(.*?)\s*', r'\1', prompt_content)  # Convert bullet points to text
        
        # Clean up any remaining multiple spaces
        prompt_content = re.sub(r'\s+', ' ', prompt_content)
        
        # Strip leading/trailing spaces
        return prompt_content.strip()

    @staticmethod
    def get_agent_config():
        """Get agent configuration."""
        return agent_settings

    @staticmethod
    def get_model_config(): #-> model_settings:
        """Get model configuration."""
        return model_settings

    @staticmethod
    def get_platform_config(): #-> aiplatform_settings:
        """Get platform configuration."""
        return aiplatform_settings

    @staticmethod
    def get_general_config():
        """Get general configuration."""
        return general_settings

    @staticmethod
    def get_a2a_config():
        """Get A2A configuration."""
        return a2a_settings

    @staticmethod
    def get_database_config():
        """Get database configuration."""
        return database_settings

    @staticmethod
    def get_dispatch_config():
        """Get dispatch (downstream A2A targets) configuration."""
        return dispatch_settings

    @staticmethod
    def create_external_mcp_servers() -> dict:
        """Return external (stdio) MCP servers. Orchestrator has none."""
        return {}

    @staticmethod
    def get_allowed_tools() -> list[str] | None:
        """Restrict the orchestrator to only its dispatch tool."""
        from app.tools import get_tool_names
        return get_tool_names() or None

    @staticmethod
    def create_local_mcp_server() -> Any:
        """Create local MCP server with auto-discovered tools."""
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


# Export the unified configuration class
__all__ = ["AppConfig"]