"""IMAP listener: watches mailbox via IDLE and publishes new tasks to Postgres.

The IMAP IDLE protocol (RFC 2177) lets the server push a notification the
instant a new message arrives, so we never poll on a fixed timer.

Also runs a minimal HTTP server in a background thread that receives
Alertmanager webhooks on POST /alerts and writes them to the tasks table.

Loop:
    1. mail.idle_check() — enters IDLE, blocks until the server sends EXISTS
       (= new mail) or the 29-min keep-alive timeout fires.
    2. On EXISTS: fetch every UNSEEN message and INSERT each into tasks.
    3. On timeout: nothing to do, loop back and re-enter IDLE immediately.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import sys
import threading
import time
import uuid

from app.config import ALERTS_HTTP_PORT
from app.db import enqueue
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

            # Loop guard: drop anything from the monitor-agent itself.
            if labels.get("service") == "monitor-agent":
                log.info("Dropping loop-guard alert: %s", labels.get("alertname"))
                continue

            try:
                task_id = await enqueue(
                    source="alert",
                    subject=labels.get("alertname"),
                    payload={
                        "alert": alert,
                        "fingerprint": alert.get("fingerprint") or str(uuid.uuid4()),
                    },
                )
                published += 1
                log.info("Queued alert: %s task_id=%s", labels.get("alertname", "?"), task_id)
            except Exception as e:
                log.error("Failed to enqueue alert: %s", e)

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
    log.info("Starting — IMAP IDLE mode, alerts port=%d", ALERTS_HTTP_PORT)

    mail: MailConnection | None = None
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
                task_id = asyncio.run(
                    enqueue(
                        source="email",
                        subject=msg.subject,
                        payload=payload,
                    )
                )
                log.info("Queued: %r / %r task_id=%s", msg.sender, msg.subject, task_id)
            except Exception as e:
                log.error("Enqueue failed: %s", e)


def main() -> None:
    threading.Thread(target=_run_alerts_server, daemon=True, name="alerts-server").start()

    try:
        _run()
    except KeyboardInterrupt:
        log.info("Shutting down.")


if __name__ == "__main__":
    main()
