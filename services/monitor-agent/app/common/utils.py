"""
Common utilities for the A2A LambdaReady Agent.
"""

import json
import logging
import sys
from a2a.types import AgentSkill


class _JSONFormatter(logging.Formatter):
    """One log record per line, exceptions included as a single JSON field.

    Keeps Loki/Alloy from splitting Python tracebacks across multiple lines.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = record.stack_info
        return json.dumps(payload, default=str)


_LOG_INITIALIZED = False


def _init_logging() -> None:
    """Install the JSON formatter on the root logger. Idempotent."""
    global _LOG_INITIALIZED
    if _LOG_INITIALIZED:
        return
    from app.configs.environment_vars.general_settings import general_settings

    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JSONFormatter())
    root.addHandler(handler)
    root.setLevel(general_settings.LOG_LEVEL)
    _LOG_INITIALIZED = True


def get_logger(name: str) -> logging.Logger:
    """Return a logger routed through the root JSON handler."""
    _init_logging()
    return logging.getLogger(name)

def build_skills_list(skills_config) -> list[AgentSkill]:
    """
    Build a list of AgentSkill objects from a skills config.
    Accepts dicts or AgentSkill instances.
    """
    out: list[AgentSkill] = []
    for s in (skills_config or []):
        if isinstance(s, AgentSkill):
            out.append(s)
        elif isinstance(s, dict):
            out.append(
                AgentSkill(
                    id=s.get("id", ""),
                    name=s.get("name", ""),
                    description=s.get("description", ""),
                    tags=list(s.get("tags") or []),
                    examples=list(s.get("examples") or []),
                )
            )
    return out
      
def get_default_skill():
    """
    Returns the default AgentSkill used as a fallback.
    """
    return AgentSkill(
        id="chat_skill",
        name="Chat Skill",
        description="Answers any user questions.",
        tags=["chat", "claude"],
        examples=["Hello, how are you?", "What is the weather in Tokyo?"],
    )
    

def dict_to_compact_json(data: dict) -> str:
    """
    Convert a dictionary to a compact JSON string with no whitespace.
    
    This is the most efficient approach for this use case as it:
    - Uses built-in json library (no additional dependencies)
    - Handles all JSON types and edge cases correctly
    - Is maintainable and follows Python best practices
    - Performance is adequate for typical use cases
    
    Args:
        data: Dictionary containing key/value pairs to convert to JSON
        
    Returns:
        Compact JSON string with no spaces, tabs, or indentation
        
    Raises:
        TypeError: If data contains non-serializable objects
        ValueError: If data is not a dictionary
    """
    if not isinstance(data, dict):
        raise ValueError("Input must be a dictionary")
    
    try:
        return json.dumps(data, separators=(',', ':'))
    except (TypeError, ValueError) as e:
        raise TypeError(f"Unable to serialize data to JSON: {e}")
