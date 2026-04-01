import config
from mail.base import AbstractMailConnection, EmailMessage


def get_mail_connection() -> AbstractMailConnection:
    if config.MAIL_BACKEND == "protonmail":
        from mail.protonmail import ProtonMailConnection
        return ProtonMailConnection()
    if config.MAIL_BACKEND == "imap":
        from mail.imap import IMAPConnection
        return IMAPConnection()
    raise ValueError(f"Unknown MAIL_BACKEND: {config.MAIL_BACKEND!r}. Expected 'protonmail' or 'imap'.")


__all__ = ["get_mail_connection", "AbstractMailConnection", "EmailMessage"]
