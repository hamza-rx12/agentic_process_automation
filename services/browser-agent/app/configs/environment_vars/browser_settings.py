"""Browser/Playwright settings loaded from environment."""
from __future__ import annotations

import os
from dataclasses import dataclass

from ._env import env_bool


@dataclass(frozen=True)
class BrowserSettings:
    HEADLESS: bool
    VIEWPORT: str
    EXECUTABLE: str


def load_browser_settings() -> BrowserSettings:
    return BrowserSettings(
        HEADLESS=env_bool("BROWSER_HEADLESS", default=True),
        VIEWPORT=os.getenv("BROWSER_VIEWPORT", "1280x720"),
        EXECUTABLE=os.getenv("BROWSER_EXECUTABLE", "/usr/bin/chromium"),
    )


browser_settings: BrowserSettings = load_browser_settings()
