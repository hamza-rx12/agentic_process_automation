"""
Configuration package exports.

Singletons like:
- agent_settings: AgentSettings (agent identity: name, system prompt)
- a2a_settings: A2ASettings (A2A/agent metadata: description, skills, etc.)
- aiplatform_settings: AIPlatformSettings (AI Platform API config: key, base URL, timeout)
- model_settings: ModelSettingsConfig (model tuning: temperature, max_tokens, model name)
- general_settings: GeneralSettings (server-level config: PORT, HOST_OVERRIDE, STREAMING, DB path)

"""

from __future__ import annotations

from .environment_vars import (
    A2ASettings,
    AgentSettings,
    AIPlatformSettings,
    GeneralSettings,
    ModelSettingsConfig,
    a2a_settings,
    agent_settings,
    aiplatform_settings,
    general_settings,
    model_settings,
)


__all__ = [
    "AgentSettings",
    "agent_settings",
    "A2ASettings",
    "a2a_settings",
    "AIPlatformSettings",
    "aiplatform_settings",
    "ModelSettingsConfig",
    "model_settings",
    "GeneralSettings",
    "general_settings",
]
