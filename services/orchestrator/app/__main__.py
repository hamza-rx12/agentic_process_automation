"""Orchestrator: dequeue tasks from Postgres and run them through ClaudeAIAgent."""
from __future__ import annotations

import asyncio
import uuid

import asyncpg

from app.agent.claude_agent import ClaudeAIAgent
from app.common.utils import get_logger
from app.config import AppConfig
from app.db import complete, dequeue, fail, get_pool

logger = get_logger(__name__)


def _format_task_prompt(task: dict) -> str:
    source = task.get("source", "email")
    payload = task.get("payload") or {}
    if source == "alert":
        alert = payload.get("alert", {})
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        return (
            "You received a Prometheus alert:\n"
            f"Alert: {labels.get('alertname', 'unknown')}\n"
            f"Service: {labels.get('service', 'unknown')}\n"
            f"Severity: {labels.get('severity', 'unknown')}\n"
            f"Summary: {annotations.get('summary', '')}\n"
            f"Description: {annotations.get('description', '')}\n\n"
            "Analyze this alert, query the relevant logs and metrics from the time of the alert, "
            "and create a runbook dashboard in Grafana."
        )
    return (
        "You received this email:\n"
        f"From: {payload.get('sender', 'unknown')}\n"
        f"Subject: {task.get('subject', '(no subject)')}\n\n"
        f"{payload.get('body', '')}\n\n"
        "Execute the requested task."
    )


async def _process(agent: ClaudeAIAgent, task: dict) -> None:
    task_id: uuid.UUID = task["id"]
    prompt = _format_task_prompt(task)
    logger.info("processing task_id=%s source=%s subject=%r", task_id, task.get("source"), task.get("subject"))
    try:
        result = await agent.invoke(prompt, context_id=str(task_id))
        text = result.get("text", "")
        meta = result.get("metadata", {})
        await complete(task_id, text, meta.get("session_id"))
        logger.info(
            "task done task_id=%s turns=%s cost=%s",
            task_id,
            meta.get("num_turns"),
            meta.get("total_cost_usd"),
        )
    except Exception as e:
        logger.exception("task failed task_id=%s", task_id)
        await fail(task_id, str(e)[:2000])


async def _drain(agent: ClaudeAIAgent) -> None:
    """Process all currently ready tasks."""
    while True:
        task = await dequeue()
        if task is None:
            return
        await _process(agent, task)


async def _run(agent: ClaudeAIAgent) -> None:
    db_cfg = AppConfig.get_database_config()

    # Dedicated connection for LISTEN — pool connections can't hold LISTEN
    # subscriptions safely across releases.
    listen_conn = await asyncpg.connect(db_cfg.URL)
    new_event = asyncio.Event()

    def _on_notify(_conn, _pid, _channel, _payload):
        new_event.set()

    await listen_conn.add_listener("tasks_new", _on_notify)
    logger.info("Orchestrator started — listening on tasks_new, poll_interval=%.1fs", db_cfg.POLL_INTERVAL_S)

    try:
        await _drain(agent)
        while True:
            try:
                await asyncio.wait_for(new_event.wait(), timeout=db_cfg.POLL_INTERVAL_S)
            except asyncio.TimeoutError:
                pass
            new_event.clear()
            await _drain(agent)
    except asyncio.CancelledError:
        logger.info("Shutting down.")
    finally:
        await listen_conn.remove_listener("tasks_new", _on_notify)
        await listen_conn.close()


async def main() -> None:
    agent = ClaudeAIAgent()
    await _run(agent)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
