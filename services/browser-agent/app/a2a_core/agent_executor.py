"""
A2A executor bridging the server runtime and an Claude-backed agent.

- Validates RequestContext
- Extracts user text from A2A parts
- Invokes Claude agent (streaming or single-shot)
- Converts outputs back to A2A Parts and drives Task lifecycle
"""

from __future__ import annotations

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    Artifact,
    DataPart,
    InternalError,
    Part,
    TaskState,
    TaskStatus,
    TextPart,
    UnsupportedOperationError,
)
from a2a.utils.errors import ServerError

from app.a2a_core.a2a_conversions import (
    extract_text_from_a2a_parts,
    extract_claude_session_id_from_parts,
    extract_fork_session_flag_from_parts,
    validate_fork_session_request_from_parts
)
from app.agent.claude_agent import ClaudeAIAgent

# Centralized logging
from app.common.utils import get_logger

logger = get_logger(__name__)


class ClaudeAIAgentExecutor(AgentExecutor):
    """
    A2A AgentExecutor backed by ClaudeAIAgent.

    Streaming:
    - True: stream() yields progress; we emit TaskState.working and then a final artifact.
    - False: invoke() once; emit a single final artifact.
    """

    def __init__(self, streaming: bool = True):
        self.streaming = streaming
        self.agent = ClaudeAIAgent()

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """
        Entrypoint. Validates context, starts task, then delegates to _process_request.
        """
        if not context.task_id or not context.context_id:
            raise ValueError("RequestContext must have task_id and context_id")
        if not context.message:
            raise ValueError("RequestContext must have a message")

        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        if not context.current_task:
            await updater.submit()
        await updater.start_work()

        # Extract user text input from A2A message parts
        try:
            user_query = context.get_user_input()
        except Exception as e:
            logger.debug("Falling back to parts extraction for user input: %s", e)
            user_query = extract_text_from_a2a_parts(context.message.parts)

        # Extract session_id and fork_session flag from A2A message parts
        session_id = extract_claude_session_id_from_parts(context.message.parts)
        fork_session = extract_fork_session_flag_from_parts(context.message.parts)
        
        # Validate fork_session request
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
            raise ServerError(error=InternalError()) from e
        except Exception as e:
            logger.error("Error while executing ClaudeAIAgent: %s", e)
            raise ServerError(error=InternalError()) from e

    async def _process_request(self, user_query: str, context_id: str, task_id: str | None, updater: TaskUpdater, session_id: str | None = None, fork_session: bool = False) -> None:
        """
        Internal helper that drives streaming or single-shot execution and task lifecycle updates.
        """
        if self.streaming:
            # Enhanced streaming mode with consistent error handling using unified _handle_error_response()
            # This ensures both intermittent and final errors create standardized "error" and "error_details" artifacts
            # self.agent.stream() should yield dicts:
            #   {"type": "progress", "text": "..."}
            #   {"type": "error", "text": "...", "metadata": {...}}  # Intermittent error - continues processing
            #   {"type": "final", "text": "...", "metadata": {...}}  # Final result or error

            # Error tracking for streaming mode - maintains continuity with non-streaming metadata patterns
            intermittent_errors = []
            final_metadata = None

            async for item in self.agent.stream(user_query, context_id=context_id, task_id=task_id, session_id=session_id, fork_session=fork_session):
                kind = item.get("type")
                text = item.get("text", "")
                metadata = item.get("metadata", {})

                if kind == "progress":
                    # Handle normal progress updates
                    await updater.update_status(
                        TaskState.working,
                        message=updater.new_agent_message([Part(root=TextPart(text=text))]),
                    )

                elif kind == "error":
                    # Handle intermittent errors: Create "error" and "error_details" artifacts but continue streaming
                    # Consistency: Uses _handle_error_response(is_intermittent=True) to standardize artifact creation
                    logger.warning("Intermittent streaming error: %s", text)

                    # Track error for potential inclusion in final metadata (mirrors non-streaming error tracking)
                    error_info = {
                        "error_text": text,
                        "error_metadata": metadata
                    }
                    intermittent_errors.append(error_info)

                    # Use unified error handling helper for consistent artifact structure
                    await self._handle_error_response(
                        error_text=text,
                        error_metadata=metadata,
                        context_id=context_id,
                        task_id=task_id,
                        user_query=user_query,
                        updater=updater,
                        is_intermittent=True
                    )

                    # Continue processing to allow recovery - key difference from final errors

                elif kind == "final":
                    # Handle final result
                    final_metadata = metadata

                    # Check if final response indicates an error (consistent with non-streaming is_error check)
                    if metadata.get("is_error"):
                        logger.error("Final streaming response indicates error: %s", text)

                        # Consistency: Uses _handle_error_response(is_intermittent=False) for final errors,
                        # including any tracked intermittent_errors in error_details
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
                        # Success case - create final response artifact (non-error path, no error artifacts)
                        await updater.add_artifact(
                            parts=[Part(root=TextPart(text=text))],
                            name="agent_response"
                        )

                        # Add metadata with error tracking (includes intermittent_errors count for completeness)
                        if final_metadata:
                            # Add error tracking to metadata - consistent with non-streaming metadata augmentation
                            final_metadata["intermittent_errors"] = intermittent_errors
                            final_metadata["num_errors"] = len(intermittent_errors)
                            final_metadata["context_id"] = context_id
                            final_metadata["task_id"] = task_id

                            await updater.add_artifact(
                                parts=[Part(root=DataPart(data=final_metadata))],
                                name="agent_metadata"
                            )

                        # Complete successfully - no error artifacts in success path
                        await updater.complete()
                        break
                else:
                    logger.info("Unknown stream item type: %s", kind)
        else:
            # SINGLE-SHOT MODE (non-streaming)
            # Consistency: Uses the same error detection and unified _handle_error_response() as streaming final errors
            claude_response = await self.agent.invoke(user_query, context_id=context_id, task_id=task_id, session_id=session_id, fork_session=fork_session)

            # Priority 1: Check for errors - mirrors streaming final error check
            if claude_response.get("metadata", {}).get("is_error"):
                # Extract actual error message from response text
                error_message = claude_response.get("text", "Agent processing failed")

                # Consistency: Uses _handle_error_response(is_intermittent=False) to create standardized
                # "error" (TextPart) and "error_details" (DataPart) artifacts, then fails the task
                await self._handle_error_response(
                    error_text=error_message,
                    error_metadata=claude_response.get("metadata", {}),
                    context_id=context_id,
                    task_id=task_id,
                    user_query=user_query,
                    updater=updater,
                    is_intermittent=False  # Default, but explicit for clarity
                )
                return

            # Success path: No error artifacts created - mirrors streaming success handling
            # Main response artifact
            parts = [Part(root=TextPart(text=claude_response["text"]))]
            await updater.add_artifact(parts, name="agent_response")

            # Metadata artifact with session tracking (consistent with streaming metadata)
            metadata = claude_response.get("metadata", {})
            if metadata:
                # Add session tracking information to metadata - same pattern as streaming
                metadata["context_id"] = context_id
                metadata["task_id"] = task_id

                metadata_parts = [Part(root=DataPart(data=metadata))]
                await updater.add_artifact(metadata_parts, name="agent_metadata")

            await updater.complete()

    def _build_error_details(self, context_id: str, task_id: str | None, error_text: str,
                             error_metadata: dict, user_query: str, is_intermittent: bool = False,
                             intermittent_errors: list | None = None) -> dict:
        """
        Build standardized error_details structure following agent_metadata patterns.

        Maintains nested architecture but ensures consistency with naming patterns.
        Used by both streaming and non-streaming error handling.
        """
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

        # Add intermittent errors tracking if this is a final error
        if not is_intermittent and intermittent_errors:
            error_details["intermittent_errors"] = intermittent_errors
            error_details["total_errors"] = len(intermittent_errors) + 1  # +1 for final error

        return error_details

    async def _handle_error_response(self, error_text: str, error_metadata: dict,
                                    context_id: str, task_id: str | None, user_query: str,
                                    updater: TaskUpdater, is_intermittent: bool = False,
                                    intermittent_errors: list | None = None) -> None:
        """
        Unified error handling for both streaming and non-streaming modes.

        Creates consistent "error" (TextPart with error_text) and "error_details" (DataPart with structured dict)
        artifacts across all error scenarios. Determines task outcome based on is_intermittent flag.
        Used by streaming intermittent/final errors and non-streaming errors for standardization.
        """
        # Create consistent error artifact (TextPart) - same for all modes
        await updater.add_artifact(
            parts=[Part(root=TextPart(text=error_text))],
            name="error"
        )

        # Create standardized error_details artifact (DataPart) using _build_error_details
        # Includes: error=True, is_intermittent, context_id, task_id, error_metadata, request_context (user_query snippet)
        # For final errors, also includes intermittent_errors and total_errors count
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
            parts=[Part(root=DataPart(data=error_details))],
            name="error_details"
        )

        # Consistency: Non-intermittent errors (final or non-streaming) fail the task; intermittent continue
        if not is_intermittent:
            await updater.failed()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """
        A2A cancellation hook. Most simple agents do not support cancellation yet.
        """
        raise ServerError(error=UnsupportedOperationError())
