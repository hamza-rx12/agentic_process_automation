"""RabbitMQ connection settings loaded from environment."""
from __future__ import annotations

import os
from dataclasses import dataclass

from ._env import env_int


@dataclass(frozen=True)
class RabbitMQSettings:
    URL: str
    QUEUE: str
    PREFETCH: int


def load_rabbitmq_settings() -> RabbitMQSettings:
    return RabbitMQSettings(
        URL=os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost/"),
        QUEUE=os.getenv("RABBITMQ_QUEUE", "email_tasks"),
        PREFETCH=env_int("RABBITMQ_PREFETCH", 1),
    )


rabbitmq_settings: RabbitMQSettings = load_rabbitmq_settings()
