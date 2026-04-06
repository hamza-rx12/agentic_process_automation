import json
import os
import uuid
from datetime import UTC, datetime


class SessionLogger:
    """Writes structured JSON-lines logs for an agent session."""

    def __init__(self, session_id: str | None = None):
        self.session_id = session_id or uuid.uuid4().hex[:8]
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
        os.makedirs("logs", exist_ok=True)
        self._path = f"logs/{ts}_{self.session_id}.jsonl"
        self._file = None

    def log(self, level: str, event: str, **data) -> None:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": level,
            "event": event,
            **data,
        }
        if self._file is None:
            self._file = open(self._path, "a")
        self._file.write(json.dumps(entry, default=str) + "\n")
        self._file.flush()

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
