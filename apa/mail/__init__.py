from apa.config import MAIL_BACKEND
from apa.mail.base import EmailMessage, MailConnection


def get_connection() -> MailConnection:
    if MAIL_BACKEND == "protonmail":
        from apa.mail.protonmail import ProtonMailConnection

        return ProtonMailConnection()
    if MAIL_BACKEND == "imap":
        from apa.mail.imap import IMAPConnection

        return IMAPConnection()
    raise ValueError(f"Unknown MAIL_BACKEND: {MAIL_BACKEND!r}")


__all__ = ["get_connection", "EmailMessage", "MailConnection"]
