import json
import time
import dataclasses

import pika

from config import RABBITMQ_URL, RABBITMQ_QUEUE, POLL_INTERVAL_SECS
from mail import get_mail_connection
from mail.base import AbstractMailConnection


_BACKOFF_INITIAL = 5    # seconds
_BACKOFF_MAX     = 300  # 5 minutes


def _publish(channel: pika.adapters.blocking_connection.BlockingChannel, message_body: dict) -> None:
    channel.basic_publish(
        exchange="",
        routing_key=RABBITMQ_QUEUE,
        body=json.dumps(message_body),
        properties=pika.BasicProperties(delivery_mode=2),  # persistent
    )


def _connect_rabbitmq() -> tuple[pika.BlockingConnection, pika.adapters.blocking_connection.BlockingChannel]:
    conn = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
    ch = conn.channel()
    ch.queue_declare(queue=RABBITMQ_QUEUE, durable=True)
    return conn, ch


def _connect_mail() -> AbstractMailConnection:
    mail = get_mail_connection()
    mail.connect()
    return mail


def _run() -> None:
    print(f"[listener] Starting — polling every {POLL_INTERVAL_SECS}s, queue={RABBITMQ_QUEUE!r}")

    mail: AbstractMailConnection | None = None
    rmq_conn = None
    channel = None
    backoff = _BACKOFF_INITIAL

    while True:
        # Ensure mail connection
        if mail is None:
            try:
                print("[listener] Connecting to mail backend...")
                mail = _connect_mail()
                print("[listener] Mail connected.")
                backoff = _BACKOFF_INITIAL
            except Exception as e:
                print(f"[listener] Mail connection failed: {e}  — retrying in {backoff}s")
                time.sleep(backoff)
                backoff = min(backoff * 2, _BACKOFF_MAX)
                continue

        # Ensure RabbitMQ connection
        if channel is None or not rmq_conn or rmq_conn.is_closed:
            try:
                print("[listener] Connecting to RabbitMQ...")
                rmq_conn, channel = _connect_rabbitmq()
                print("[listener] RabbitMQ connected.")
                backoff = _BACKOFF_INITIAL
            except Exception as e:
                print(f"[listener] RabbitMQ connection failed: {e}  — retrying in {backoff}s")
                time.sleep(backoff)
                backoff = min(backoff * 2, _BACKOFF_MAX)
                continue

        # Poll for new emails
        try:
            messages = mail.idle_check()
        except Exception as e:
            print(f"[listener] idle_check() failed: {e}  — reconnecting")
            try:
                mail.disconnect()
            except Exception:
                pass
            mail = None
            continue

        for msg in messages:
            payload = dataclasses.asdict(msg)
            try:
                _publish(channel, payload)
                print(f"[listener] Queued: {msg.sender!r} / {msg.subject!r}")
            except Exception as e:
                print(f"[listener] Publish failed: {e}  — will reconnect RabbitMQ")
                try:
                    rmq_conn.close()
                except Exception:
                    pass
                channel = None
                rmq_conn = None
                break  # re-enter loop to reconnect before processing remaining messages

        time.sleep(POLL_INTERVAL_SECS)


def main() -> None:
    try:
        _run()
    except KeyboardInterrupt:
        print("\n[listener] Shutting down.")


if __name__ == "__main__":
    main()
