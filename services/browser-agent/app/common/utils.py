"""
Common utilities for the A2A LambdaReady Agent.
"""

import json
import logging
from a2a.types import AgentSkill

def get_logger(name: str) -> logging.Logger:
    """
    Standardized logger initialization with configured log level.
    """
    from app.configs.environment_vars.general_settings import general_settings

    logger = logging.getLogger(name)

    # Configure logging to ensure messages are displayed at configured level
    if not logger.handlers:
        # Add console handler if none exists
        handler = logging.StreamHandler()
        handler.setLevel(general_settings.LOG_LEVEL)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(general_settings.LOG_LEVEL)

        # Disable propagation to root logger to prevent duplicate logs
        logger.propagate = False

        # Configure root logger to ensure all loggers propagate
        root_logger = logging.getLogger()
        if not root_logger.handlers:
            root_handler = logging.StreamHandler()
            root_handler.setLevel(general_settings.LOG_LEVEL)
            root_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')
            root_handler.setFormatter(root_formatter)
            root_logger.addHandler(root_handler)
            root_logger.setLevel(general_settings.LOG_LEVEL)
    else:
        # Ensure existing handlers are at configured level
        for handler in logger.handlers:
            if handler.level > general_settings.LOG_LEVEL:
                handler.setLevel(general_settings.LOG_LEVEL)
        logger.setLevel(general_settings.LOG_LEVEL)

    return logger

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
