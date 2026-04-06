"""A2A protocol — thin wrappers around the official a2a-sdk."""

from a2a.client import ClientConfig
from a2a.client.client_factory import ClientFactory
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps.jsonrpc.fastapi_app import A2AFastAPIApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    Artifact,
    Message,
    Part,
    Role,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)

__all__ = [
    # Client
    "ClientConfig",
    "ClientFactory",
    # Server
    "A2AFastAPIApplication",
    "AgentExecutor",
    "DefaultRequestHandler",
    "EventQueue",
    "InMemoryTaskStore",
    "RequestContext",
    # Types
    "AgentCapabilities",
    "AgentCard",
    "AgentSkill",
    "Artifact",
    "Message",
    "Part",
    "Task",
    "TaskArtifactUpdateEvent",
    "TaskState",
    "TaskStatus",
    "TaskStatusUpdateEvent",
    "Role",
    "TextPart",
]
