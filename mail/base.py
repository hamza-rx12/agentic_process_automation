from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class EmailMessage:
    message_id: str
    sender: str
    subject: str
    body: str
    received_at: str  # ISO 8601


class AbstractMailConnection(ABC):
    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def idle_check(self) -> list[EmailMessage]:
        """Return all unseen messages since last call, marking them as seen."""
        ...

    @abstractmethod
    def disconnect(self) -> None: ...
