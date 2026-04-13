"""
Claude-backed agent runtime wrapper for the Claude Agent SDK.

- Initializes the Claude client and options
- Optional tool registration
- Provides invoke() and stream() for non-streaming and streaming flows
- A2A protocol handling lives in app/a2a_core/agent_executor.py
"""

from __future__ import annotations

from typing import Any, AsyncIterable, Optional

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)

# Configuration imports (domain-specific, well-structured)

# Unified configuration access
from app.config import AppConfig

# Helper imports (internal to agent layer)
from app.agent.agent_support import (
    log_mcp_server_state,
    extract_final_text,
    extract_stream_text_piece,
    build_claude_options,
)

# Centralized logging
from app.common.utils import (
    get_logger,
    dict_to_compact_json)

logger = get_logger(__name__)


class ClaudeAIAgent:
    """
    Thin wrapper around the Claude Agent SDK exposed to the A2A executor.

    Dependencies are injected via constructor, eliminating cross-layer imports.
    """

    # Choose content types your Agent supports. Keep aligned with AgentCard in __main__.py
    SUPPORTED_CONTENT_TYPES = ["text/plain"]

    def __init__(self):
        """
        Construct the Claude Agent SDK runtime with unified configuration access.

        Simplified constructor that uses AppConfig for all configuration needs,
        eliminating the complexity of dependency injection while maintaining modularity.
        """
        # Get configuration through unified access
        self.agent_config = AppConfig.get_agent_config()
        self.model_config = AppConfig.get_model_config()
        self.platform_config = AppConfig.get_platform_config()

        # Get API key
        self.api_key = AppConfig.get_api_key()

        # Get system prompt
        self.system_prompt = AppConfig.get_system_prompt()

        # Load MCP servers
        self.local_mcp_server = AppConfig.create_local_mcp_server()
        self.external_mcp_servers = AppConfig.create_external_mcp_servers()
        self.allowed_tools = AppConfig.get_allowed_tools()

        # Build Claude Agent Options using unified helper function
        # Extract configuration values
        base_url = getattr(self.platform_config, 'AIPLATFORM_BASE_URL', None)
        temperature = getattr(self.model_config, 'TEMPERATURE', None)
        max_tokens = getattr(self.model_config, 'MAX_TOKENS', None)
        top_p = getattr(self.model_config, 'TOP_P', None)
        top_k = getattr(self.model_config, 'TOP_K', None)

        # Extract agent-specific settings from agent_config
        permission_mode = getattr(self.agent_config, 'AGENT_PERMISSION_MODE', None)
        setting_sources = getattr(self.agent_config, 'AGENT_SETTING_SOURCES', None)
        disallowed_tools = getattr(self.agent_config, 'AGENT_DISALLOWED_TOOLS', None)
        cwd = getattr(self.agent_config, 'AGENT_CWD', None)
        max_turns = getattr(self.agent_config, 'AGENT_MAX_TURNS', None)

        # Use the unified helper function
        self.options = build_claude_options(
            api_key=self.api_key,
            system_prompt=self.system_prompt,
            model=self.model_config.MODEL_NAME,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            top_k=top_k,
            permission_mode=permission_mode,
            setting_sources=setting_sources,
            disallowed_tools=disallowed_tools,
            cwd=cwd,
            max_turns=max_turns,
            local_mcp_server=self.local_mcp_server,
            external_mcp_servers=self.external_mcp_servers,
            allowed_tools=self.allowed_tools,
        )

        # Stable identifier(s)
        self.agent_id: str = f"local-claude-agent::{self.model_config.MODEL_NAME}"

    def _ensure_agent(self) -> str:
        """
        Ensure agent exists; return a stable agent_id.
        """
        # Options are built in __init__, so just return the agent_id
        return self.agent_id

    async def invoke(self, question: str, context_id: str, task_id: Optional[str] = None, session_id: Optional[str] = None, fork_session: bool = False) -> dict[str, Any]:
        """
        Single-shot call using ClaudeSDKClient. Returns response with metadata.

        Stateless: does not create or persist any session/memory.

        Returns:
            dict with 'text' and 'metadata' keys
        """
        _ = self._ensure_agent()

        # Generate custom headers for this request
        custom_headers_dict = {}

        modelParams = dict_to_compact_json({
            "max_tokens": self.model_config.MAX_TOKENS,
            "temperature": self.model_config.TEMPERATURE,
            "top_p": self.model_config.TOP_P,
            "top_k": self.model_config.TOP_K
            })

        traceParams = dict_to_compact_json({
            "a2a-context-id": context_id,
            "a2a-task-id": task_id,
            "claude-session-id": session_id
        })

        custom_headers_dict["modelParams"] = modelParams
        custom_headers_dict["traceParams"] = traceParams

        # Create new options with custom headers and session management for this request
        options_with_headers = build_claude_options(
            base_options=self.options,
            custom_headers=custom_headers_dict,
            resume=session_id if session_id else None,
            fork_session=fork_session if (session_id and fork_session) else False
        )

        # Connect MCP servers if needed
        if self.local_mcp_server and hasattr(self.local_mcp_server, "connect"):
            await self.local_mcp_server.connect()

        # Initialize response accumulators (must be bound for finally/ post-try usage)
        response_parts: list[str] = []
        tools_used: list[dict[str, Any]] = []
        metadata: dict[str, Any] = {}
        final_result_text: str | None = None

        try:
            logger.debug("invoke(): ClaudeSDKClient with context_id=%r agent_id=%r header=%r", context_id, self.agent_id, custom_headers_dict)

            # Use ClaudeSDKClient with updated options
            async with ClaudeSDKClient(options=options_with_headers) as client:
                await client.query(question)

                async for message in client.receive_response():
                                        
                    # Handle Assistant messages (text chunks + tool usage)
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                response_parts.append(block.text)
                            elif isinstance(block, ToolUseBlock):
                                tool_info = {
                                    "id": block.id,
                                    "name": block.name,
                                    "input": block.input
                                }
                                tools_used.append(tool_info)

                    # Handle ResultMessage (final metadata + FinalResult text)
                    elif isinstance(message, ResultMessage):
                        # Get final result text from ResultMessage using the correct field name
                        final_result_text = getattr(message, 'result', None)

                        metadata = {
                            "session_id": message.session_id,
                            "duration_ms": message.duration_ms,
                            "duration_api_ms": message.duration_api_ms,
                            "is_error": message.is_error,
                            "num_turns": message.num_turns,
                            "total_cost_usd": message.total_cost_usd,
                            "usage": message.usage,
                            "tools_used": tools_used,  # Track tools used during conversation
                        }
                        break

        except Exception as e:
            logger.exception("ClaudeSDKClient invoke failed: %s", e)
            raise
        finally:
            # Clean up MCP servers
            if self.local_mcp_server and hasattr(self.local_mcp_server, "cleanup"):
                await self.local_mcp_server.cleanup()

        # Use FinalResult text if available, otherwise fallback to accumulated AssistantMessage chunks
        if final_result_text:
            final_text = final_result_text
        else:
            final_text = "".join(response_parts).strip()

        return {
            "text": final_text,
            "metadata": metadata
        }

    async def stream(self, question: str, context_id: str, task_id: str | None, session_id: Optional[str] = None, fork_session: bool = False) -> AsyncIterable[dict[str, Any]]:
        """
        Streaming run using ClaudeSDKClient like your working example.
        Yields {"type": "progress" | "error" | "final", "text": "...", "metadata": "..."}.

        Stateless: does not create or persist any session/memory.
        """
        _ = self._ensure_agent()

        # Generate custom headers for this request
        custom_headers_dict = {}

        modelParams = dict_to_compact_json({
            "max_tokens": self.model_config.MAX_TOKENS,
            "temperature": self.model_config.TEMPERATURE,
            "top_p": self.model_config.TOP_P,
            "top_k": self.model_config.TOP_K
            })

        traceParams = dict_to_compact_json({
            "a2a-context-id": context_id,
            "a2a-task-id": task_id,
            "claude-session-id": session_id
        })

        custom_headers_dict["modelParams"] = modelParams
        custom_headers_dict["traceParams"] = traceParams

        # Create new options with custom headers and session management for this request
        options_with_header = build_claude_options(
            base_options=self.options,
            custom_headers=custom_headers_dict,
            resume=session_id if session_id else None,
            fork_session=fork_session if (session_id and fork_session) else False
        )

        # Connect MCP servers if needed
        if self.local_mcp_server and hasattr(self.local_mcp_server, "connect"):
            await self.local_mcp_server.connect()

        # Initialize response accumulators (must be bound for finally/post-try usage)
        final_result_text: str | None = None
        final_metadata: dict[str, Any] | None = None
        tools_used: list[dict[str, Any]] = []

        try:
            logger.debug("stream(): ClaudeSDKClient streaming with context_id=%r agent_id=%r header=%r", context_id, self.agent_id, custom_headers_dict)

            # Use ClaudeSDKClient with updated options
            async with ClaudeSDKClient(options=options_with_header) as client:
                await client.query(question)

                async for message in client.receive_response():
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                text_piece = block.text
                                if text_piece:
                                    yield {"type": "progress", "text": text_piece}
                            elif isinstance(block, ToolUseBlock):
                                tool_info = {
                                    "id": block.id,
                                    "name": block.name,
                                    "input": block.input
                                }
                                tools_used.append(tool_info)

                    elif isinstance(message, ResultMessage):
                        # Extract final result and metadata
                        final_result_text = getattr(message, 'result', None)

                        # Build metadata following the same pattern as invoke()
                        final_metadata = {
                            "session_id": message.session_id,
                            "duration_ms": message.duration_ms,
                            "duration_api_ms": message.duration_api_ms,
                            "is_error": message.is_error,
                            "num_turns": message.num_turns,
                            "total_cost_usd": message.total_cost_usd,
                            "usage": message.usage,
                            "tools_used": tools_used,
                        }
                        break

        except Exception as e:
            logger.exception("ClaudeSDKClient stream failed: %s", e)

            # Create error metadata for intermittent errors
            error_metadata = {
                "is_error": True,
                "error_type": "streaming_error",
                "error_message": str(e),
                "context_id": context_id,
                "task_id": task_id,
                "session_id": session_id,
            }

            # Yield error item but don't return - allow continuation
            yield {"type": "error", "text": f"Streaming error: {e}", "metadata": error_metadata}

            # Don't return here - allow natural continuation or retry
        finally:
            # Clean up MCP servers
            if self.local_mcp_server and hasattr(self.local_mcp_server, "cleanup"):
                await self.local_mcp_server.cleanup()

        # Yield final result with metadata
        final_text = final_result_text if final_result_text is not None else ""

        if final_metadata:
            yield {"type": "final", "text": final_text, "metadata": final_metadata}
        else:
            yield {"type": "final", "text": final_text}