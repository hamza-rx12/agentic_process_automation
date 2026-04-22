"""
A2A conversion utilities for bridging A2A Parts and Claude message formats.
"""

from __future__ import annotations

import json
from typing import Any

from a2a.types import Part


def extract_text_from_a2a_parts(parts: list[Part]) -> str:
    texts: list[str] = []
    for p in parts:
        if p.text:
            texts.append(p.text)
        elif p.url:
            texts.append(f"[File: {p.url}]")
        elif p.raw:
            texts.append("[File: inline bytes]")
    return "\n".join(texts).strip()


def a2a_parts_to_claude_messages(parts: list[Part]) -> Any:
    return [{"role": "user", "content": extract_text_from_a2a_parts(parts)}]


def claude_messages_to_a2a_parts(output: Any) -> list[Part]:
    if isinstance(output, str):
        return [Part(text=output)]
    if isinstance(output, (list, tuple)):
        return [Part(text="\n".join([str(x) for x in output]))]
    return [Part(text=str(output))]


def extract_claude_session_id_from_parts(parts: list[Part]) -> str | None:
    for part in parts:
        if part.media_type == "application/json" and part.text:
            try:
                data = json.loads(part.text)
                if isinstance(data, dict):
                    session_id = data.get("session_id")
                    if isinstance(session_id, str) and session_id.strip():
                        return session_id.strip()
            except Exception:
                pass
    return None


def extract_fork_session_flag_from_parts(parts: list[Part]) -> bool:
    for part in parts:
        if part.media_type == "application/json" and part.text:
            try:
                data = json.loads(part.text)
                if isinstance(data, dict):
                    fork_session = data.get("fork_session", False)
                    if isinstance(fork_session, bool):
                        return fork_session
                    elif isinstance(fork_session, str):
                        return fork_session.lower() in ('true', '1', 'yes', 'on')
                    elif isinstance(fork_session, (int, float)):
                        return bool(fork_session)
            except Exception:
                pass
    return False


def validate_fork_session_request_from_parts(parts: list[Part]) -> tuple[bool, str | None]:
    session_id = extract_claude_session_id_from_parts(parts)
    fork_session = extract_fork_session_flag_from_parts(parts)

    if fork_session and not session_id:
        return False, "fork_session requires a valid session_id"
    if session_id is not None and not isinstance(session_id, str):
        return False, "session_id must be a string"
    if session_id is not None and isinstance(session_id, str) and not session_id.strip():
        return False, "session_id cannot be empty"
    if fork_session and (not session_id or not session_id.strip()):
        return False, "fork_session requires a valid session_id"
    return True, None
