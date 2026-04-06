"""Standard IMAP (SSL) backend — uses IMAP IDLE for push-based delivery."""

import email

import imapclient

from apa.config import APP_PASSWORD, EMAIL, IMAP_HOST, IMAP_PORT
from apa.mail.base import (
    EmailMessage,
    MailConnection,
    decode_header_value,
    extract_body,
    parse_date,
)

# RFC 2177 says servers may drop the IDLE connection after 30 min.
# Re-issue IDLE every 29 minutes to stay safely inside that window.
_IDLE_TIMEOUT_SECS = 29 * 60


class IMAPConnection(MailConnection):
    def __init__(self) -> None:
        self._client: imapclient.IMAPClient | None = None

    def connect(self) -> None:
        client = imapclient.IMAPClient(IMAP_HOST, port=IMAP_PORT, ssl=True)
        client.login(EMAIL, APP_PASSWORD)
        client.select_folder("INBOX")
        self._client = client

    def idle_check(self) -> list[EmailMessage]:
        """Block via IMAP IDLE until the server pushes a notification, then
        fetch every UNSEEN message and return them.  Returns an empty list
        on a timeout (29-min keep-alive cycle) — the caller should just
        loop back immediately.
        """
        if self._client is None:
            raise RuntimeError("Not connected")

        # --- Enter IDLE mode (server will push changes instead of us polling) ---
        self._client.idle()
        try:
            responses = self._client.idle_check(timeout=_IDLE_TIMEOUT_SECS)
        finally:
            self._client.idle_done()  # always exit IDLE before issuing commands

        # responses look like [(3, b'EXISTS'), (1, b'RECENT'), ...]
        # b'EXISTS' means the mailbox size changed → new mail arrived.
        # Ignore EXPUNGE, FETCH flag-change notifications, and plain timeouts.
        new_mail = any(
            isinstance(resp, tuple) and len(resp) == 2 and resp[1] == b"EXISTS"
            for resp in responses
        )
        if not new_mail:
            return []

        return self._fetch_unseen()

    def _fetch_unseen(self) -> list[EmailMessage]:
        """Fetch all UNSEEN messages, mark them SEEN, and return them."""
        if self._client is None:
            raise RuntimeError("Not connected")

        uids = self._client.search("UNSEEN")
        if not uids:
            return []

        messages: list[EmailMessage] = []
        for uid, data in self._client.fetch(uids, ["RFC822"]).items():
            raw = data[b"RFC822"]
            if not isinstance(raw, bytes):
                continue
            msg = email.message_from_bytes(raw)
            self._client.set_flags([uid], [imapclient.SEEN])
            messages.append(
                EmailMessage(
                    message_id=msg.get("Message-ID", str(uid)).strip(),
                    sender=decode_header_value(msg.get("From", "")),
                    subject=decode_header_value(msg.get("Subject", "")),
                    body=extract_body(msg),
                    received_at=parse_date(msg.get("Date", "")),
                )
            )
        return messages

    def disconnect(self) -> None:
        if self._client:
            try:
                self._client.logout()
            except Exception:
                pass
            self._client = None
