"""
A2A executor bridging the server runtime and an Claude-backed agent.
"""

from __future__ import annotations

import json

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    InternalError,
    Part,
    Task,
    TaskState,
    TaskStatus,
    UnsupportedOperationError,
)

from app.a2a_core.a2a_conversions import (
    extract_text_from_a2a_parts,
    extract_claude_session_id_from_parts,
    extract_fork_session_flag_from_parts,
    validate_fork_session_request_from_parts
)
from app.agent.claude_agent import ClaudeAIAgent
from app.common.task_context import active_task_id

from app.common.utils import get_logger

logger = get_logger(__name__)


class ClaudeAIAgentExecutor(AgentExecutor):
    """
    A2A AgentExecutor backed by ClaudeAIAgent.
    """

    def __init__(self, streaming: bool = True):
        self.streaming = streaming
        self.agent = ClaudeAIAgent()

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        if not context.task_id or not context.context_id:
            raise ValueError("RequestContext must have task_id and context_id")
        if not context.message:
            raise ValueError("RequestContext must have a message")

        # Enqueue a Task object first — the A2A consumer requires a Task
        # event before it will accept any TaskStatusUpdateEvent.
        if not context.current_task:
            initial_task = Task(
                id=context.task_id,
                context_id=context.context_id,
                status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
            )
            await event_queue.enqueue_event(initial_task)

        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.start_work()

        import uuid as _uuid
        try:
            active_task_id.set(_uuid.UUID(context.context_id))
        except (ValueError, AttributeError):
            active_task_id.set(None)

        try:
            user_query = context.get_user_input()
        except Exception as e:
            logger.debug("Falling back to parts extraction for user input: %s", e)
            user_query = extract_text_from_a2a_parts(context.message.parts)

        session_id = extract_claude_session_id_from_parts(context.message.parts)
        fork_session = extract_fork_session_flag_from_parts(context.message.parts)

        is_valid, validation_error = validate_fork_session_request_from_parts(context.message.parts)
        if not is_valid:
            logger.error("Fork session validation failed: %s", validation_error)
            raise ValueError(validation_error)

        if session_id:
            action = "fork" if fork_session else "resume"
            logger.debug("Found session_id: %s, action: %s", session_id, action)

        try:
            await self._process_request(
                user_query=user_query,
                context_id=context.context_id,
                task_id=context.task_id,
                updater=updater,
                session_id=session_id,
                fork_session=fork_session
            )
        except NotImplementedError as e:
            logger.error("Unimplemented method in ClaudeAIAgent: %s", e)
            raise RuntimeError(str(e)) from e
        except Exception as e:
            logger.error("Error while executing ClaudeAIAgent: %s", e)
            raise RuntimeError(str(e)) from e

    async def _process_request(self, user_query: str, context_id: str, task_id: str | None, updater: TaskUpdater, session_id: str | None = None, fork_session: bool = False) -> None:
        if self.streaming:
            intermittent_errors = []
            final_metadata = None

            async for item in self.agent.stream(user_query, context_id=context_id, task_id=task_id, session_id=session_id, fork_session=fork_session):
                kind = item.get("type")
                text = item.get("text", "")
                metadata = item.get("metadata", {})

                if kind == "progress":
                    await updater.update_status(
                        TaskState.TASK_STATE_WORKING,
                        message=updater.new_agent_message([Part(text=text)]),
                    )

                elif kind == "error":
                    logger.warning("Intermittent streaming error: %s", text)
                    error_info = {"error_text": text, "error_metadata": metadata}
                    intermittent_errors.append(error_info)

                    await self._handle_error_response(
                        error_text=text,
                        error_metadata=metadata,
                        context_id=context_id,
                        task_id=task_id,
                        user_query=user_query,
                        updater=updater,
                        is_intermittent=True
                    )

                elif kind == "final":
                    final_metadata = metadata

                    if metadata.get("is_error"):
                        logger.error("Final streaming response indicates error: %s", text)
                        await self._handle_error_response(
                            error_text=text,
                            error_metadata=metadata,
                            context_id=context_id,
                            task_id=task_id,
                            user_query=user_query,
                            updater=updater,
                            is_intermittent=False,
                            intermittent_errors=intermittent_errors
                        )
                        return
                    else:
                        await updater.add_artifact(
                            parts=[Part(text=text)],
                            name="agent_response"
                        )

                        if final_metadata:
                            final_metadata["intermittent_errors"] = intermittent_errors
                            final_metadata["num_errors"] = len(intermittent_errors)
                            final_metadata["context_id"] = context_id
                            final_metadata["task_id"] = task_id

                            await updater.add_artifact(
                                parts=[Part(text=json.dumps(final_metadata), media_type="application/json")],
                                name="agent_metadata"
                            )

                        await updater.complete()
                        break
                else:
                    logger.info("Unknown stream item type: %s", kind)
        else:
            claude_response = await self.agent.invoke(user_query, context_id=context_id, task_id=task_id, session_id=session_id, fork_session=fork_session)

            if claude_response.get("metadata", {}).get("is_error"):
                error_message = claude_response.get("text", "Agent processing failed")
                await self._handle_error_response(
                    error_text=error_message,
                    error_metadata=claude_response.get("metadata", {}),
                    context_id=context_id,
                    task_id=task_id,
                    user_query=user_query,
                    updater=updater,
                    is_intermittent=False
                )
                return

            parts = [Part(text=claude_response["text"])]
            await updater.add_artifact(parts, name="agent_response")

            metadata = claude_response.get("metadata", {})
            if metadata:
                metadata["context_id"] = context_id
                metadata["task_id"] = task_id
                await updater.add_artifact(
                    [Part(text=json.dumps(metadata), media_type="application/json")],
                    name="agent_metadata"
                )

            await updater.complete()

    def _build_error_details(self, context_id: str, task_id: str | None, error_text: str,
                             error_metadata: dict, user_query: str, is_intermittent: bool = False,
                             intermittent_errors: list | None = None) -> dict:
        error_details = {
            "error": True,
            "is_intermittent": is_intermittent,
            "context_id": context_id,
            "task_id": task_id,
            "error_metadata": {
                "error_text": error_text,
                "claude_metadata": error_metadata,
            },
            "request_context": {
                "user_query": user_query[:100] + "..." if len(user_query) > 100 else user_query,
            },
        }

        if not is_intermittent and intermittent_errors:
            error_details["intermittent_errors"] = intermittent_errors
            error_details["total_errors"] = len(intermittent_errors) + 1

        return error_details

    async def _handle_error_response(self, error_text: str, error_metadata: dict,
                                    context_id: str, task_id: str | None, user_query: str,
                                    updater: TaskUpdater, is_intermittent: bool = False,
                                    intermittent_errors: list | None = None) -> None:
        await updater.add_artifact(
            parts=[Part(text=error_text)],
            name="error"
        )

        error_details = self._build_error_details(
            context_id=context_id,
            task_id=task_id,
            error_text=error_text,
            error_metadata=error_metadata,
            user_query=user_query,
            is_intermittent=is_intermittent,
            intermittent_errors=intermittent_errors
        )
        await updater.add_artifact(
            parts=[Part(text=json.dumps(error_details), media_type="application/json")],
            name="error_details"
        )

        if not is_intermittent:
            await updater.failed()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("cancel not supported")
