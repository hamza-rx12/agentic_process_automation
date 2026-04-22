"""Postgres connection settings loaded from environment."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class DatabaseSettings:
    URL: str
    POLL_INTERVAL_S: float


def load_database_settings() -> DatabaseSettings:
    return DatabaseSettings(
        URL=os.environ["DATABASE_URL"],
        POLL_INTERVAL_S=float(os.getenv("DB_POLL_INTERVAL_S", "2")),
    )


database_settings: DatabaseSettings = load_database_settings()
