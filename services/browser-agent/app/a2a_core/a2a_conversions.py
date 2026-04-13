"""
A2A conversion utilities for bridging A2A Parts and Claude message formats.

- extract_text_from_a2a_parts: Extract text from A2A Parts
- a2a_parts_to_claude_messages: Convert A2A Parts to Claude message format
- claude_messages_to_a2a_parts: Convert Claude outputs to A2A Parts
"""

from __future__ import annotations

from typing import Any

from a2a.types import (
    Part,
    TextPart,
    DataPart,
    FilePart,
    FileWithBytes,
    FileWithUri,
)


def extract_text_from_a2a_parts(parts: list[Part]) -> str:
    """
    Join all TextPart texts into a single user_query. File parts are summarized.
    """
    texts: list[str] = []
    for p in parts:
        root = p.root
        if isinstance(root, TextPart):
            if root.text:
                texts.append(root.text)
        elif isinstance(root, FilePart):
            # TODO: Implement file handling if your agent needs it.
            # For now, you can ignore or append placeholders.
            if isinstance(root.file, FileWithUri):
                texts.append(f"[File: {root.file.uri}]")
            elif isinstance(root.file, FileWithBytes):
                texts.append("[File: inline bytes]")
            else:
                texts.append("[File: unsupported]")
        else:
            # Unrecognized part type; ignore or log.
            pass
    return "\n".join(texts).strip()


def a2a_parts_to_claude_messages(parts: list[Part]) -> Any:
    """
    Convert A2A parts to an Claude-friendly payload (simple chat-style).
    """
    return [{"role": "user", "content": extract_text_from_a2a_parts(parts)}]


def claude_messages_to_a2a_parts(output: Any) -> list[Part]:
    """
    Convert Claude outputs to A2A Parts (TextPart by default).
    """
    if isinstance(output, str):
        return [Part(root=TextPart(text=output))]
    if isinstance(output, (list, tuple)):
        text = "\n".join([str(x) for x in output])
        return [Part(root=TextPart(text=text))]
    return [Part(root=TextPart(text=str(output)))]


def extract_claude_session_id_from_parts(parts: list[Part]) -> str | None:
    """
    Extract session_id from A2A message parts.
    
    Looks for DataPart with session information in the data field.
    Expected structure: {"kind": "data", "data": {"session_id": "...", "fork_session": "..."}}
    
    Args:
        parts: List of A2A Parts from the message
        
    Returns:
        Session ID string if found and valid, None otherwise
    """
    for part in parts:
        root = part.root
        if isinstance(root, DataPart):
            # Check if this DataPart contains session information
            data = root.data
            if isinstance(data, dict):
                session_id = data.get("session_id")
                if isinstance(session_id, str) and session_id.strip():
                    return session_id.strip()
    return None


def extract_fork_session_flag_from_parts(parts: list[Part]) -> bool:
    """
    Extract fork_session flag from A2A message parts.
    
    Looks for DataPart with session information in the data field.
    Expected structure: {"kind": "data", "data": {"session_id": "...", "fork_session": "..."}}
    
    Args:
        parts: List of A2A Parts from the message
        
    Returns:
        True if client wants to fork session, False for resume
    """
    for part in parts:
        root = part.root
        if isinstance(root, DataPart):
            # Check if this DataPart contains session information
            data = root.data
            if isinstance(data, dict):
                fork_session = data.get("fork_session", False)
                
                # Handle various boolean representations
                if isinstance(fork_session, bool):
                    return fork_session
                elif isinstance(fork_session, str):
                    return fork_session.lower() in ('true', '1', 'yes', 'on')
                elif isinstance(fork_session, (int, float)):
                    return bool(fork_session)
    return False


def validate_fork_session_request_from_parts(parts: list[Part]) -> tuple[bool, str | None]:
    """
    Validate fork_session request according to business rules.
    
    Args:
        parts: List of A2A Parts from the message
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    session_id = extract_claude_session_id_from_parts(parts)
    fork_session = extract_fork_session_flag_from_parts(parts)
    
    # If fork_session is explicitly requested but no session_id provided
    if fork_session and not session_id:
        return False, "fork_session requires a valid session_id"
    
    # If session_id is provided but invalid type
    if session_id is not None and not isinstance(session_id, str):
        return False, "session_id must be a string"
    
    # If session_id is provided but empty/invalid
    if session_id is not None and isinstance(session_id, str) and not session_id.strip():
        return False, "session_id cannot be empty"
    
    # Additional check: if fork_session is true, session_id must be valid
    if fork_session and (not session_id or not session_id.strip()):
        return False, "fork_session requires a valid session_id"
    
    return True, None


# Deprecated metadata functions removed - use parts-based functions instead