"""IMAP listener: watches mailbox via IDLE and publishes new mail to RabbitMQ.

The IMAP IDLE protocol (RFC 2177) lets the server push a notification the
instant a new message arrives, so we never poll on a fixed timer.

Also runs a minimal HTTP server in a background thread that receives
Alertmanager webhooks on POST /alerts and publishes them to the same
RabbitMQ queue with source="alert".

Loop:
    1. mail.idle_check() — enters IDLE, blocks until the server sends EXISTS
       (= new mail) or the 29-min keep-alive timeout fires.
    2. On EXISTS: fetch every UNSEEN message and publish each to RabbitMQ.
    3. On timeout: nothing to do, loop back and re-enter IDLE immediately.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import sys
import threading
import time
import uuid

import pika

from app.config import ALERTS_HTTP_PORT, RABBITMQ_QUEUE, RABBITMQ_URL
from app.mail import MailConnection, get_connection


class _JSONFormatter(logging.Formatter):
    """One log record per line, exceptions included as a single JSON field."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = record.stack_info
        return json.dumps(payload, default=str)


_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(_JSONFormatter())
logging.basicConfig(level=logging.INFO, handlers=[_handler], force=True)
log = logging.getLogger("listener")

_BACKOFF_INITIAL = 5
_BACKOFF_MAX = 300
_HEARTBEAT = 60  # seconds — must be less than RabbitMQ's timeout

# Module-level RabbitMQ channel shared between the IMAP loop and the alerts
# webhook. Protected by _rmq_lock.
_channel = None
_rmq_lock = threading.Lock()


def _connect_rabbitmq():
    params = pika.URLParameters(RABBITMQ_URL)
    params.heartbeat = _HEARTBEAT
    conn = pika.BlockingConnection(params)
    ch = conn.channel()
    ch.queue_declare(queue=RABBITMQ_QUEUE, durable=True)

    def _heartbeat_loop():
        while conn.is_open:
            try:
                conn.process_data_events()
            except Exception:
                break
            time.sleep(_HEARTBEAT / 2)

    threading.Thread(target=_heartbeat_loop, daemon=True).start()
    return conn, ch


def _publish(channel, payload: dict) -> None:
    channel.basic_publish(
        exchange="",
        routing_key=RABBITMQ_QUEUE,
        body=json.dumps(payload),
        properties=pika.BasicProperties(delivery_mode=2),
    )


# ── Alertmanager webhook ─────────────────────────────────────────────────────

def _build_alerts_app():
    """Return a Starlette ASGI app with POST /alerts and GET /health."""
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    async def receive_alerts(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON"}, status_code=400)

        alerts = body.get("alerts", [])
        published = 0
        for alert in alerts:
            labels = alert.get("labels", {})

            # Loop guard #2: drop anything from the monitor-agent itself.
            if labels.get("service") == "monitor-agent":
                log.info("Dropping loop-guard alert: %s", labels.get("alertname"))
                continue

            payload = {
                "source": "alert",
                "message_id": alert.get("fingerprint") or str(uuid.uuid4()),
                "alert": alert,
            }
            with _rmq_lock:
                if _channel and _channel.is_open:
                    try:
                        _publish(_channel, payload)
                        published += 1
                        log.info("Queued alert: %s", labels.get("alertname", "?"))
                    except Exception as e:
                        log.error("Failed to publish alert: %s", e)
                else:
                    log.warning("RabbitMQ channel not ready — alert dropped: %s", labels.get("alertname"))

        return JSONResponse({"published": published})

    return Starlette(routes=[
        Route("/health", health, methods=["GET"]),
        Route("/alerts", receive_alerts, methods=["POST"]),
    ])


def _run_alerts_server() -> None:
    import uvicorn
    app = _build_alerts_app()
    log.info("Starting alerts HTTP server on port %d", ALERTS_HTTP_PORT)
    uvicorn.run(app, host="0.0.0.0", port=ALERTS_HTTP_PORT, log_level="warning")


# ── IMAP loop ────────────────────────────────────────────────────────────────

def _run() -> None:
    global _channel

    log.info("Starting — IMAP IDLE mode, queue=%r, alerts port=%d", RABBITMQ_QUEUE, ALERTS_HTTP_PORT)

    mail: MailConnection | None = None
    rmq_conn = None
    channel = None
    backoff = _BACKOFF_INITIAL

    while True:
        if mail is None:
            try:
                mail = get_connection()
                mail.connect()
                log.info("Mail connected.")
                backoff = _BACKOFF_INITIAL
            except Exception as e:
                log.error("Mail failed: %s — retry in %ds", e, backoff)
                time.sleep(backoff)
                backoff = min(backoff * 2, _BACKOFF_MAX)
                continue

        if channel is None or not rmq_conn or rmq_conn.is_closed:
            try:
                rmq_conn, channel = _connect_rabbitmq()
                with _rmq_lock:
                    _channel = channel
                log.info("RabbitMQ connected.")
                backoff = _BACKOFF_INITIAL
            except Exception as e:
                log.error("RabbitMQ failed: %s — retry in %ds", e, backoff)
                time.sleep(backoff)
                backoff = min(backoff * 2, _BACKOFF_MAX)
                continue

        try:
            messages = mail.idle_check()
        except Exception as e:
            log.error("Poll failed: %s — reconnecting", e)
            try:
                mail.disconnect()
            except Exception:
                pass
            mail = None
            continue

        for msg in messages:
            try:
                payload = dataclasses.asdict(msg)
                payload["source"] = "email"
                with _rmq_lock:
                    _publish(channel, payload)
                log.info("Queued: %r / %r", msg.sender, msg.subject)
            except Exception as e:
                log.error("Publish failed: %s", e)
                try:
                    rmq_conn.close()
                except Exception:
                    pass
                channel = None
                rmq_conn = None
                with _rmq_lock:
                    _channel = None
                break


def main() -> None:
    # Start the alerts webhook server in a daemon thread.
    threading.Thread(target=_run_alerts_server, daemon=True, name="alerts-server").start()

    try:
        _run()
    except KeyboardInterrupt:
        log.info("Shutting down.")


if __name__ == "__main__":
    main()
