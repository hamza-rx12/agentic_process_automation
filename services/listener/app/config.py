"""Environment-based configuration for the listener service."""
from __future__ import annotations

import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# --- Email / IMAP ---
EMAIL = os.getenv("EMAIL", "")
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
IMAP_HOST = os.getenv("IMAP_HOST", "")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
MAIL_BACKEND = os.getenv("MAIL_BACKEND", "protonmail")

# --- Database ---
DATABASE_URL: str = os.environ["DATABASE_URL"]

# --- Alerts webhook ---
ALERTS_HTTP_PORT = int(os.getenv("ALERTS_HTTP_PORT", "9000"))
