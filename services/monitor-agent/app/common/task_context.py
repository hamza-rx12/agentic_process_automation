"""ContextVar carrying the active task id, set by the A2A executor."""
from __future__ import annotations

import uuid
from contextvars import ContextVar
from typing import Optional

active_task_id: ContextVar[Optional[uuid.UUID]] = ContextVar(
    "active_task_id", default=None
)
