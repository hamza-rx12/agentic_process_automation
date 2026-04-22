"""MCP tools for reading and updating the current task row."""
from __future__ import annotations

from typing import Any

from claude_agent_sdk import tool

from app.common.task_context import active_task_id
from app.common.utils import get_logger
from app.db import append_progress, get_task, set_artifact

log = get_logger(__name__)


def _err(msg: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": msg}], "is_error": True}


@tool(
    name="task_get",
    description="Fetch the current task row (status, payload, attempts, progress notes).",
    input_schema={"type": "object", "properties": {}, "required": []},
)
async def task_get_mcp(_args: dict[str, Any]) -> dict[str, Any]:
    tid = active_task_id.get()
    if tid is None:
        return _err("No active task in this context.")
    row = await get_task(tid)
    if row is None:
        return _err(f"Task {tid} not found.")
    return {"content": [{"type": "text", "text": str(row)}]}


@tool(
    name="task_append_note",
    description="Append a timestamped progress note to the current task.",
    input_schema={
        "type": "object",
        "properties": {"note": {"type": "string", "description": "Progress note to record."}},
        "required": ["note"],
    },
)
async def task_append_note_mcp(args: dict[str, Any]) -> dict[str, Any]:
    tid = active_task_id.get()
    if tid is None:
        return _err("No active task in this context.")
    await append_progress(tid, args["note"])
    return {"content": [{"type": "text", "text": "ok"}]}


@tool(
    name="task_set_artifact",
    description="Write a named artifact into the current task's payload.artifacts.",
    input_schema={
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Artifact name."},
            "value": {"description": "Any JSON-serialisable value."},
        },
        "required": ["key", "value"],
    },
)
async def task_set_artifact_mcp(args: dict[str, Any]) -> dict[str, Any]:
    tid = active_task_id.get()
    if tid is None:
        return _err("No active task in this context.")
    await set_artifact(tid, args["key"], args["value"])
    return {"content": [{"type": "text", "text": "ok"}]}


__all__ = [
    "task_get_mcp",
    "task_append_note_mcp",
    "task_set_artifact_mcp",
]
