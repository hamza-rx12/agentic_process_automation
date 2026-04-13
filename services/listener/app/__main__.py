"""IMAP listener: watches mailbox via IDLE and publishes new mail to RabbitMQ.

The IMAP IDLE protocol (RFC 2177) lets the server push a notification the
instant a new message arrives, so we never poll on a fixed timer.

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
import threading
import time

import pika

from app.config import RABBITMQ_QUEUE, RABBITMQ_URL
from app.mail import MailConnection, get_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("listener")

_BACKOFF_INITIAL = 5
_BACKOFF_MAX = 300
_HEARTBEAT = 60  # seconds — must be less than RabbitMQ's timeout


def _connect_rabbitmq():
    params = pika.URLParameters(RABBITMQ_URL)
    params.heartbeat = _HEARTBEAT
    conn = pika.BlockingConnection(params)
    ch = conn.channel()
    ch.queue_declare(queue=RABBITMQ_QUEUE, durable=True)

    # Keep heartbeats alive in a background thread while the main thread
    # blocks on IMAP IDLE.
    def _heartbeat_loop():
        while conn.is_open:
            try:
                conn.process_data_events()
            except Exception:
                break
            time.sleep(_HEARTBEAT / 2)

    threading.Thread(target=_heartbeat_loop, daemon=True).start()
    return conn, ch


def _run() -> None:
    log.info("Starting — IMAP IDLE mode, queue=%r", RABBITMQ_QUEUE)

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
                channel.basic_publish(
                    exchange="",
                    routing_key=RABBITMQ_QUEUE,
                    body=json.dumps(payload),
                    properties=pika.BasicProperties(delivery_mode=2),
                )
                log.info("Queued: %r / %r", msg.sender, msg.subject)
            except Exception as e:
                log.error("Publish failed: %s", e)
                try:
                    rmq_conn.close()
                except Exception:
                    pass
                channel = None
                rmq_conn = None
                break


def main() -> None:
    try:
        _run()
    except KeyboardInterrupt:
        log.info("Shutting down.")


if __name__ == "__main__":
    main()
