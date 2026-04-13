"""ProtonMail backend (via ProtonMail Bridge — STARTTLS)."""

import email
import imaplib

from app.config import APP_PASSWORD, EMAIL, IMAP_HOST, IMAP_PORT
from app.mail.base import (
    EmailMessage,
    MailConnection,
    decode_header_value,
    extract_body,
    parse_date,
)


class ProtonMailConnection(MailConnection):
    def __init__(self) -> None:
        self._mail: imaplib.IMAP4 | None = None

    def connect(self) -> None:
        mail = imaplib.IMAP4(IMAP_HOST, IMAP_PORT)
        mail.starttls()
        mail.login(EMAIL, APP_PASSWORD)
        self._mail = mail

    def idle_check(self) -> list[EmailMessage]:
        if self._mail is None:
            raise RuntimeError("Not connected")

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
            self._mail.store(num, "+FLAGS", "\\Seen")
            messages.append(
                EmailMessage(
                    message_id=(msg.get("Message-ID") or num.decode()).strip(),
                    sender=decode_header_value(msg.get("From", "")),
                    subject=decode_header_value(msg.get("Subject", "")),
                    body=extract_body(msg),
                    received_at=parse_date(msg.get("Date", "")),
                )
            )
        return messages

    def disconnect(self) -> None:
        if self._mail:
            try:
                self._mail.close()
            except Exception:
                pass
            try:
                self._mail.logout()
            except Exception:
                pass
            self._mail = None
