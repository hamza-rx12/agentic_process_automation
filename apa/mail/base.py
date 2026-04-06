"""Base mail types and helpers."""

import email
import email.message
import email.utils
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from email.header import decode_header


@dataclass
class EmailMessage:
    message_id: str
    sender: str
    subject: str
    body: str
    received_at: str  # ISO 8601


class MailConnection(ABC):
    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def idle_check(self) -> list[EmailMessage]: ...

    @abstractmethod
    def disconnect(self) -> None: ...


# Shared helpers


def decode_header_value(value: str) -> str:
    parts = decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


def extract_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get("Content-Disposition"):
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if isinstance(payload, bytes):
            return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
    return ""


def parse_date(date_str: str) -> str:
    try:
        return email.utils.parsedate_to_datetime(date_str).isoformat()
    except Exception:
        return datetime.now(UTC).isoformat()
