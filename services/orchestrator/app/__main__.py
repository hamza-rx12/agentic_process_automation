"""Orchestrator entry point: consume RabbitMQ tasks and run them through ClaudeAIAgent."""
from __future__ import annotations

import json
import logging
import time

import anyio
import pika

from app.agent.claude_agent import ClaudeAIAgent
from app.common.utils import get_logger
from app.config import AppConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = get_logger(__name__)

_BACKOFF_INITIAL = 5
_BACKOFF_MAX = 300


def _format_task_prompt(data: dict) -> str:
    source = data.get("source", "email")
    if source == "alert":
        alert = data.get("alert", {})
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
    # Default: email
    return (
        "You received this email:\n"
        f"From: {data.get('sender', 'unknown')}\n"
        f"Subject: {data.get('subject', '(no subject)')}\n\n"
        f"{data.get('body', '')}\n\n"
        "Execute the requested task."
    )


async def _process_task(agent: ClaudeAIAgent, task_data: dict) -> None:
    prompt = _format_task_prompt(task_data)
    context_id = str(task_data.get("message_id") or task_data.get("subject", "task"))
    result = await agent.invoke(prompt, context_id=context_id)
    text = result.get("text", "")
    meta = result.get("metadata", {})
    logger.info(
        "task done — turns=%s cost=%s text=%s",
        meta.get("num_turns"),
        meta.get("total_cost_usd"),
        (text[:200] + "...") if len(text) > 200 else text,
    )


def _run_consumer(agent: ClaudeAIAgent) -> None:
    rmq = AppConfig.get_rabbitmq_config()
    logger.info("Starting orchestrator — queue=%r", rmq.QUEUE)
    backoff = _BACKOFF_INITIAL

    while True:
        try:
            conn = pika.BlockingConnection(pika.URLParameters(rmq.URL))
            ch = conn.channel()
            ch.queue_declare(queue=rmq.QUEUE, durable=True)
            ch.basic_qos(prefetch_count=rmq.PREFETCH)
            logger.info("Connected to RabbitMQ — waiting for messages...")
            backoff = _BACKOFF_INITIAL

            def callback(channel, method, _properties, body: bytes) -> None:
                try:
                    data = json.loads(body)
                    logger.info("Processing: %r", data.get("subject", "?"))
                    anyio.run(_process_task, agent, data)
                except Exception as e:
                    logger.exception("Error processing message: %s", e)
                finally:
                    channel.basic_ack(delivery_tag=method.delivery_tag)

            ch.basic_consume(queue=rmq.QUEUE, on_message_callback=callback)
            ch.start_consuming()
        except KeyboardInterrupt:
            logger.info("Shutting down.")
            return
        except Exception as e:
            logger.error("Connection error: %s — retrying in %ds", e, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX)


def main() -> None:
    agent = ClaudeAIAgent()
    _run_consumer(agent)


if __name__ == "__main__":
    main()
