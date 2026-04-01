import email
import email.message
import email.utils
from email.header import decode_header
from datetime import datetime, timezone

import imapclient

from config import EMAIL, APP_PASSWORD, IMAP_HOST, IMAP_PORT
from mail.base import AbstractMailConnection, EmailMessage


def _decode_header_value(value: str) -> str:
    parts = decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


def _extract_body(msg: email.message.Message) -> str:
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


class IMAPConnection(AbstractMailConnection):
    def __init__(self) -> None:
        self._client: imapclient.IMAPClient | None = None

    def connect(self) -> None:
        client = imapclient.IMAPClient(IMAP_HOST, port=IMAP_PORT, ssl=True)
        client.login(EMAIL, APP_PASSWORD)
        client.select_folder("INBOX")
        self._client = client

    def idle_check(self) -> list[EmailMessage]:
        if self._client is None:
            raise RuntimeError("Not connected — call connect() first")

        uids = self._client.search("UNSEEN")
        if not uids:
            return []

        messages: list[EmailMessage] = []
        raw_messages = self._client.fetch(uids, ["RFC822"])

        for uid, data in raw_messages.items():
            raw = data[b"RFC822"]
            if not isinstance(raw, bytes):
                continue
            msg = email.message_from_bytes(raw)

            message_id = msg.get("Message-ID", str(uid)).strip()
            sender = _decode_header_value(msg.get("From", ""))
            subject = _decode_header_value(msg.get("Subject", ""))
            date_str = msg.get("Date", "")
            try:
                received_at = email.utils.parsedate_to_datetime(date_str).isoformat()
            except Exception:
                received_at = datetime.now(timezone.utc).isoformat()

            body = _extract_body(msg)

            self._client.set_flags([uid], [imapclient.SEEN])

            messages.append(EmailMessage(
                message_id=message_id,
                sender=sender,
                subject=subject,
                body=body,
                received_at=received_at,
            ))

        return messages

    def disconnect(self) -> None:
        if self._client is None:
            return
        try:
            self._client.logout()
        except Exception:
            pass
        self._client = None
