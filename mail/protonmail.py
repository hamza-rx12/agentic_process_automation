import imaplib
import email
import email.message
import email.utils
from email.header import decode_header
from datetime import datetime, timezone

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


class ProtonMailConnection(AbstractMailConnection):
    def __init__(self) -> None:
        self._mail: imaplib.IMAP4 | None = None

    def connect(self) -> None:
        mail = imaplib.IMAP4(IMAP_HOST, IMAP_PORT)
        mail.starttls()
        mail.login(EMAIL, APP_PASSWORD)
        self._mail = mail

    def idle_check(self) -> list[EmailMessage]:
        if self._mail is None:
            raise RuntimeError("Not connected — call connect() first")

        self._mail.select("INBOX")
        status, data = self._mail.search(None, "UNSEEN")
        if status != "OK" or not data[0]:
            return []

        messages: list[EmailMessage] = []
        for num in data[0].split():
            status, msg_data = self._mail.fetch(num, "(RFC822)")
            if status != "OK":
                continue

            entry = msg_data[0]
            if not isinstance(entry, tuple):
                continue
            raw = entry[1]
            if not isinstance(raw, bytes):
                continue
            msg = email.message_from_bytes(raw)

            message_id = (msg.get("Message-ID") or num.decode()).strip()
            sender = _decode_header_value(msg.get("From", ""))
            subject = _decode_header_value(msg.get("Subject", ""))
            date_str = msg.get("Date", "")
            try:
                received_at = email.utils.parsedate_to_datetime(date_str or "").isoformat()
            except Exception:
                received_at = datetime.now(timezone.utc).isoformat()

            body = _extract_body(msg)

            # Mark as seen
            self._mail.store(num, "+FLAGS", "\\Seen")

            messages.append(EmailMessage(
                message_id=message_id,
                sender=sender,
                subject=subject,
                body=body,
                received_at=received_at,
            ))

        return messages

    def disconnect(self) -> None:
        if self._mail is None:
            return
        try:
            self._mail.close()
        except Exception:
            pass
        try:
            self._mail.logout()
        except Exception:
            pass
        self._mail = None
