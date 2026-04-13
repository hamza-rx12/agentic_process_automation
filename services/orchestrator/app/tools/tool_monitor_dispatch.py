"""Dispatch an observability task to the monitor-agent via A2A.

Auto-discovered by `app.tools` (matches `tool_*.py`, wrapper ends in `_mcp`).
"""
from __future__ import annotations

import uuid
from typing import Any

import httpx
from a2a.client import ClientConfig
from a2a.client.card_resolver import A2ACardResolver
from a2a.client.client_factory import ClientFactory
from a2a.types import (
    Message as A2AMessage,
    Part,
    Role,
    Task,
    TextPart,
)
from claude_agent_sdk import tool

from app.common.utils import get_logger
from app.config import AppConfig

logger = get_logger(__name__)


def _extract_text_from_parts(parts: list[Part]) -> str:
    for part in parts:
        if isinstance(part.root, TextPart):
            return part.root.text
    return ""


def _extract_text_from_task(task: Task) -> str:
    if task.artifacts:
        for artifact in task.artifacts:
            text = _extract_text_from_parts(artifact.parts)
            if text:
                return text
    return "Task completed with no output."


def _extract_error_from_task(task: Task) -> str:
    if task.status.message and task.status.message.parts:
        text = _extract_text_from_parts(task.status.message.parts)
        if text:
            return text
    return "Unknown error"


async def _send_to_monitor_agent(instruction: str) -> tuple[str, bool]:
    """Send a task to the monitor agent via A2A. Returns (text, is_error)."""
    target_url = AppConfig.get_dispatch_config().MONITOR_AGENT_URL

    async with httpx.AsyncClient(timeout=None) as http_client:
        config = ClientConfig(streaming=False, httpx_client=http_client)
        factory = ClientFactory(config)

        resolver = A2ACardResolver(http_client, target_url)
        card = await resolver.get_agent_card()
        client = factory.create(card)

        msg = A2AMessage(
            role=Role.user,
            message_id=str(uuid.uuid4()),
            parts=[Part(root=TextPart(text=instruction))],
        )

        async for event in client.send_message(msg):
            if isinstance(event, A2AMessage):
                return _extract_text_from_parts(event.parts) or "No output", False
            task, _update = event
            if task.status.state in ("completed", "failed", "canceled"):
                if task.status.state == "completed":
                    return _extract_text_from_task(task), False
                return f"FAILED: {_extract_error_from_task(task)}", True

    return "No terminal response from monitor agent", True


@tool(
    name="dispatch_monitor_task",
    description="Dispatch an observability task to the monitor agent (query logs/metrics, create dashboards or alert rules).",
    input_schema={
        "type": "object",
        "properties": {
            "instruction": {
                "type": "string",
                "description": "The observability task to execute.",
            }
        },
        "required": ["instruction"],
    },
)
async def dispatch_monitor_task_mcp(args: dict[str, Any]) -> dict[str, Any]:
    instruction = args.get("instruction", "")
    logger.info("dispatching monitor task: %s", instruction[:120])
    try:
        text, is_error = await _send_to_monitor_agent(instruction)
    except Exception as e:
        logger.exception("monitor dispatch failed")
        return {
            "content": [{"type": "text", "text": f"FAILED: {e}"}],
            "is_error": True,
        }

    result: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        result["is_error"] = True
    return result


__all__ = ["dispatch_monitor_task_mcp"]
