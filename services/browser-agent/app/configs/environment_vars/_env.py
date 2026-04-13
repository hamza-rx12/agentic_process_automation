"""
Shared environment helpers for configuration modules.

- Loads .env once on import
- Provides typed helpers for bool, int, float, and CSV list parsing
"""
from __future__ import annotations

import os
from typing import Sequence
from dotenv import load_dotenv

# Load environment from .env once, on import
load_dotenv()


def env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def env_csv(name: str, default: Sequence[str]) -> list[str]:
    raw = os.getenv(name)
    if raw is None:
        return list(default)
    s = raw.strip()
    if not s:
        return list(default)
    # Support comma or semicolon separators
    parts = [p.strip() for p in s.replace(";", ",").split(",")]
    parts = [p for p in parts if p]
    return parts or list(default)


def env_log_level(name: str, default: str = "WARNING") -> int:
    """
    Parse a logging level from environment variable.
    Returns the corresponding logging level constant.
    """
    import logging
    
    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "WARN": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    
    level_str = os.getenv(name, default).upper()
    return level_map.get(level_str, logging.WARNING)

