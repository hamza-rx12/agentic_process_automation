"""
GeneralSettings: General/misc deployment settings loaded from environment.

Use this module for settings that don't belong in other settings files.

Env vars like:
- PORT (int; default: 10005)
- HOST_OVERRIDE (optional public URL override)
- STREAMING (bool; default: true)
- LOG_LEVEL (str; default: WARNING; values: DEBUG, INFO, WARNING, ERROR, CRITICAL)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from ._env import env_bool, env_int, env_log_level


@dataclass(frozen=True)
class GeneralSettings:
    PORT: int
    HOST_OVERRIDE: Optional[str]
    STREAMING: bool
    LOG_LEVEL: int


def load_general_settings() -> GeneralSettings:
    return GeneralSettings(
        PORT=env_int("PORT", 10005),
        HOST_OVERRIDE=os.getenv("HOST_OVERRIDE"),
        STREAMING=env_bool("STREAMING", False),
        LOG_LEVEL=env_log_level("LOG_LEVEL", "INFO"),
    )


# Singleton general settings object used across the app
general_settings: GeneralSettings = load_general_settings()