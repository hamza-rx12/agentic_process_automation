"""Listens for new email via IMAP IDLE and publishes messages to RabbitMQ.

The IMAP IDLE protocol (RFC 2177) lets the server push a notification the
instant a new message arrives, so we never poll on a fixed timer.  The flow
inside the main loop is:

    1. mail.idle_check() — enters IDLE, blocks until the server sends an
       EXISTS response (= new mail) or the 29-min keep-alive timeout fires.
    2. On EXISTS: fetch every UNSEEN message and publish each to RabbitMQ.
    3. On timeout: nothing to do, loop back and re-enter IDLE immediately.
"""

import dataclasses
import json
import threading
import time

import pika

from apa.config import RABBITMQ_QUEUE, RABBITMQ_URL
from apa.mail import MailConnection, get_connection

_BACKOFF_INITIAL = 5
_BACKOFF_MAX = 300
_HEARTBEAT = 60  # seconds — must be less than RabbitMQ's timeout


def _connect_rabbitmq():
    params = pika.URLParameters(RABBITMQ_URL)
    params.heartbeat = _HEARTBEAT
    conn = pika.BlockingConnection(params)
    ch = conn.channel()
    ch.queue_declare(queue=RABBITMQ_QUEUE, durable=True)

    # Keep heartbeats alive in a background thread while the main
    # thread blocks on IMAP polling.
    def _heartbeat_loop():
        while conn.is_open:
            try:
                conn.process_data_events()
            except Exception:
                break
            time.sleep(_HEARTBEAT / 2)

    t = threading.Thread(target=_heartbeat_loop, daemon=True)
    t.start()
    return conn, ch


def _run() -> None:
    print(f"[listener] Starting — IMAP IDLE mode, queue={RABBITMQ_QUEUE!r}")

    mail: MailConnection | None = None
    rmq_conn = None
    channel = None
    backoff = _BACKOFF_INITIAL

    while True:
        if mail is None:
            try:
                mail = get_connection()
                mail.connect()
                print("[listener] Mail connected.")
                backoff = _BACKOFF_INITIAL
            except Exception as e:
                print(f"[listener] Mail failed: {e} — retry in {backoff}s")
                time.sleep(backoff)
                backoff = min(backoff * 2, _BACKOFF_MAX)
                continue

        if channel is None or not rmq_conn or rmq_conn.is_closed:
            try:
                rmq_conn, channel = _connect_rabbitmq()
                print("[listener] RabbitMQ connected.")
                backoff = _BACKOFF_INITIAL
            except Exception as e:
                print(f"[listener] RabbitMQ failed: {e} — retry in {backoff}s")
                time.sleep(backoff)
                backoff = min(backoff * 2, _BACKOFF_MAX)
                continue

        try:
            messages = mail.idle_check()
        except Exception as e:
            print(f"[listener] Poll failed: {e} — reconnecting")
            try:
                mail.disconnect()
            except Exception:
                pass
            mail = None
            continue

        for msg in messages:
            try:
                channel.basic_publish(
                    exchange="",
                    routing_key=RABBITMQ_QUEUE,
                    body=json.dumps(dataclasses.asdict(msg)),
                    properties=pika.BasicProperties(delivery_mode=2),
                )
                print(f"[listener] Queued: {msg.sender!r} / {msg.subject!r}")
            except Exception as e:
                print(f"[listener] Publish failed: {e}")
                try:
                    rmq_conn.close()
                except Exception:
                    pass
                channel = None
                rmq_conn = None
                break

        # No sleep needed — idle_check() already blocks until
        # the server pushes a notification or the 29-min timeout fires.


def main() -> None:
    try:
        _run()
    except KeyboardInterrupt:
        print("\n[listener] Shutting down.")


if __name__ == "__main__":
    main()
