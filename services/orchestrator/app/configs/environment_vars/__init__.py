"""
Environment Variables Configuration Package

This package contains all environment-based configuration modules for the application.
Each module loads and validates specific categories of settings from environment variables.

Available Settings Modules:
- a2a_settings: A2A protocol and agent skill configuration
- agent_settings: Core agent configuration (name, system prompt)
- general_settings: General deployment settings (port, host, streaming)
- model_settings: Model tuning parameters (temperature, max tokens)
- aiplatform_settings: AI Platform API configuration (API key, base URL, timeout)

Usage:
    from app.configs.environment_vars import a2a_settings, agent_settings

    print(a2a_settings.AGENT_VERSION)
    print(agent_settings.AGENT_NAME)
"""

from __future__ import annotations

from .a2a_settings import A2ASettings, a2a_settings, load_a2a_settings
from .agent_settings import AgentSettings, agent_settings, load_agent_settings
from .aiplatform_settings import (
    AIPlatformSettings,
    aiplatform_settings,
    load_aiplatform_settings,
)
from .general_settings import GeneralSettings, general_settings, load_general_settings
from .model_settings import ModelSettingsConfig, load_model_settings, model_settings

__all__ = [
    # A2A Settings
    "A2ASettings",
    "a2a_settings",
    "load_a2a_settings",
    # Agent Settings
    "AgentSettings",
    "agent_settings",
    "load_agent_settings",
    # General Settings
    "GeneralSettings",
    "general_settings",
    "load_general_settings",
    # Model Settings
    "ModelSettingsConfig",
    "model_settings",
    "load_model_settings",
    # AI Platform Settings
    "AIPlatformSettings",
    "aiplatform_settings",
    "load_aiplatform_settings",
]
