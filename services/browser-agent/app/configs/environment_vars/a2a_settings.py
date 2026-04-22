"""
A2ASettings: Agent-related configuration loaded from environment.

Env vars:
- AGENT_NAME (default: Claude Scheduling Agent)
- AGENT_DESCRIPTION (default: A2A-compliant agent powered by the Claude Agent SDK for chat.)
- AGENT_VERSION (default: 1.0.0)
- AGENT_DEFAULT_INPUT_MODES (CSV; default: text/plain)
- AGENT_DEFAULT_OUTPUT_MODES (CSV; default: text/plain)
- AGENT_PUSH_NOTIFICATIONS (bool; default: false)
- AGENT_SKILLS (JSON array):
  [
    {
      "id": "claude_chat_skill",
      "name": "Claude Chat Skill",
      "description": "Answers user questions using Claude Agent SDK.",
      "tags": ["chat", "claude"],
      "examples": ["Hello, how are you?", "What is the weather in Tokyo?"]
    }
  ]
  If not provided or invalid, a hardcoded default skill will be used.
"""
from __future__ import annotations

import os 
import json
from dataclasses import dataclass
from typing import Any

from ._env import env_bool, env_csv
from app.common.utils import get_default_skill


@dataclass(frozen=True)
class A2ASettings:
    AGENT_DESCRIPTION: str
    AGENT_VERSION: str
    AGENT_DEFAULT_INPUT_MODES: list[str]
    AGENT_DEFAULT_OUTPUT_MODES: list[str]
    AGENT_PUSH_NOTIFICATIONS: bool
    # Multi-skill configuration (normalized list of dicts)
    AGENT_SKILLS: list[dict[str, Any]]


def _parse_agent_skills_from_file(file_path: str) -> list[dict[str, Any]]:
    """
    Parse agent skills from a JSON file into a normalized list of dicts.
    Each skill dict has keys: id, name, description, tags (list[str]), examples (list[str]).
    Falls back to empty list if file not found or parsing fails.
    """
    skills: list[dict[str, Any]] = []
    if not file_path or not os.path.exists(file_path):
        return skills
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if isinstance(data, list):
            for i, item in enumerate(data):
                if not isinstance(item, dict):
                    continue
                sid = str(item.get("id", "")).strip() or f"skill_{i+1}"
                sname = str(item.get("name", "")).strip() or "Skill"
                sdesc = str(item.get("description", "")).strip()
                tags = item.get("tags", [])
                examples = item.get("examples", [])

                if isinstance(tags, str):
                    tags = [t.strip() for t in tags.replace(";", ",").split(",") if t.strip()]
                if not isinstance(tags, list):
                    tags = []

                if isinstance(examples, str):
                    examples = [e.strip() for e in examples.replace(";", ",").split(",") if e.strip()]
                if not isinstance(examples, list):
                    examples = []

                skills.append(
                    {
                        "id": sid,
                        "name": sname,
                        "description": sdesc,
                        "tags": tags,
                        "examples": examples,
                    }
                )
    except Exception:
        # Ignore parse errors; fall back to empty list
        return []
    return skills


def load_a2a_settings() -> A2ASettings:
    # Load skills from file if specified
    skills_file_path = os.getenv("AGENT_SKILLS_FILE")
    parsed_skills = _parse_agent_skills_from_file(skills_file_path) if skills_file_path else []
    
    # If no skills from file, provide a hardcoded default skill
    if not parsed_skills:
        skill = get_default_skill()
        parsed_skills = [{
            "id": skill.id,
            "name": skill.name,
            "description": skill.description,
            "tags": list(skill.tags),
            "examples": list(skill.examples),
        }]

    return A2ASettings(
        AGENT_DESCRIPTION=os.getenv("AGENT_DESCRIPTION", "A2A-compliant agent powered by the Claude Agent SDK for chat."),
        AGENT_VERSION=os.getenv("AGENT_VERSION", "1.0.0"),
        AGENT_DEFAULT_INPUT_MODES=env_csv("AGENT_DEFAULT_INPUT_MODES", ["text/plain"]),
        AGENT_DEFAULT_OUTPUT_MODES=env_csv("AGENT_DEFAULT_OUTPUT_MODES", ["text/plain"]),
        AGENT_PUSH_NOTIFICATIONS=env_bool("AGENT_PUSH_NOTIFICATIONS", False),
        AGENT_SKILLS=parsed_skills,
    )


# Singleton settings object used across the app
a2a_settings: A2ASettings = load_a2a_settings()