"""Settings for downstream A2A agents the orchestrator dispatches tasks to."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class DispatchSettings:
    BROWSER_AGENT_URL: str
    MONITOR_AGENT_URL: str


def load_dispatch_settings() -> DispatchSettings:
    return DispatchSettings(
        BROWSER_AGENT_URL=os.getenv("BROWSER_AGENT_URL", "http://localhost:8080"),
        MONITOR_AGENT_URL=os.getenv("MONITOR_AGENT_URL", "http://localhost:8081"),
    )


dispatch_settings: DispatchSettings = load_dispatch_settings()
