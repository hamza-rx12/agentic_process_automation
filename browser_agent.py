import json
from claude_agent_sdk import (
    query,
    ClaudeSDKClient,
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    RateLimitEvent,
    TextBlock,
    ToolUseBlock,
    CLINotFoundError,
    CLIConnectionError,
    ProcessError,
)
from config import get_agent_options
from logger import SessionLogger


def summarize_tool_input(tool_name: str, tool_input: dict) -> str:
    """Create a human-readable one-line summary of a tool call."""
    if "url" in tool_input:
        return f"{tool_name}: {tool_input['url']}"
    if "text" in tool_input:
        text = tool_input["text"]
        if len(text) > 60:
            text = text[:57] + "..."
        return f"{tool_name}: \"{text}\""
    if "key" in tool_input:
        return f"{tool_name}: {tool_input['key']}"
    if "ref" in tool_input:
        detail = f"ref={tool_input['ref']}"
        if "value" in tool_input:
            detail += f" value=\"{tool_input['value'][:40]}\""
        return f"{tool_name}: {detail}"
    if tool_input:
        compact = json.dumps(tool_input, default=str)
        if len(compact) > 80:
            compact = compact[:77] + "..."
        return f"{tool_name}: {compact}"
    return tool_name


def handle_message(message, logger: SessionLogger | None = None) -> None:
    """Print agent messages in a human-readable format and log to file."""
    if isinstance(message, RateLimitEvent):
        if logger:
            logger.log(
                "warning", "rate_limit",
                rate_limit_type=getattr(message, "type", None),
                resets_at=getattr(message, "resets_at", None),
            )
        return

    if isinstance(message, SystemMessage):
        if message.subtype == "init":
            print("[system] Agent session started")
            if logger:
                logger.log("info", "session_start", session_id=logger.session_id)
        return

    if isinstance(message, AssistantMessage):
        if hasattr(message, "error") and message.error:
            if logger:
                logger.log("error", "agent_error", error=message.error)
        for block in message.content:
            if isinstance(block, TextBlock):
                print(f"\n{block.text}")
                if logger:
                    logger.log("info", "agent_text", text=block.text)
            elif isinstance(block, ToolUseBlock):
                tool_name = block.name.removeprefix("mcp__playwright__")
                summary = summarize_tool_input(tool_name, block.input)
                print(f"  -> {summary}")
                if logger:
                    logger.log("info", "tool_call", tool_name=tool_name, tool_input_summary=summary)
        return

    if isinstance(message, ResultMessage):
        info_parts = []
        log_data: dict = {}
        if hasattr(message, "usage") and message.usage:
            usage = message.usage
            cost = getattr(usage, "cost_usd", None)
            turns = getattr(usage, "turns", None)
            duration_ms = getattr(usage, "duration_ms", None)
            duration_api_ms = getattr(usage, "duration_api_ms", None)
            if turns is not None:
                info_parts.append(f"turns={turns}")
                log_data["num_turns"] = turns
            if cost is not None:
                info_parts.append(f"cost=${cost:.4f}")
                log_data["total_cost_usd"] = cost
            if duration_ms is not None:
                log_data["duration_ms"] = duration_ms
            if duration_api_ms is not None:
                log_data["duration_api_ms"] = duration_api_ms
        stop = getattr(message, "stop_reason", None)
        if stop:
            info_parts.append(f"stop={stop}")
            log_data["stop_reason"] = stop
        print(f"\n[done] {', '.join(info_parts) if info_parts else 'finished'}")
        if logger:
            logger.log("info", "session_end", **log_data)
        return


async def run_single_task(instruction: str) -> None:
    """Run a single browser task using query()."""
    options = get_agent_options()
    logger = SessionLogger()
    logger.log("info", "session_start", session_id=logger.session_id, instruction=instruction, mode="single")
    print(f"[task] {instruction}\n")

    try:
        async for message in query(prompt=instruction, options=options):
            handle_message(message, logger)
    except CLINotFoundError:
        print("[error] Claude Code CLI not found. Install with: pip install claude-agent-sdk")
        logger.log("error", "error", error_type="CLINotFoundError", message="Claude Code CLI not found")
    except CLIConnectionError as e:
        print(f"[error] Connection error: {e}")
        logger.log("error", "error", error_type="CLIConnectionError", message=str(e))
    except ProcessError as e:
        print(f"[error] Process error: {e}")
        logger.log("error", "error", error_type="ProcessError", message=str(e))
    finally:
        logger.close()


async def run_conversational() -> None:
    """Run an interactive conversational browser session."""
    options = get_agent_options()
    logger = SessionLogger()
    logger.log("info", "session_start", session_id=logger.session_id, mode="conversational")
    print("Browser Agent - Interactive Mode")
    print("Type your instructions. Press Ctrl+C to exit.\n")

    try:
        async with ClaudeSDKClient(options=options) as client:
            while True:
                try:
                    instruction = input("you> ").strip()
                except EOFError:
                    break

                if not instruction:
                    continue
                if instruction.lower() in ("exit", "quit", "q"):
                    break

                logger.log("info", "user_instruction", instruction=instruction)
                await client.query(instruction)
                async for message in client.receive_response():
                    handle_message(message, logger)
                print()
    except KeyboardInterrupt:
        print("\n[exit] Session ended.")
    except CLINotFoundError:
        print("[error] Claude Code CLI not found. Install with: pip install claude-agent-sdk")
        logger.log("error", "error", error_type="CLINotFoundError", message="Claude Code CLI not found")
    except CLIConnectionError as e:
        print(f"[error] Connection error: {e}")
        logger.log("error", "error", error_type="CLIConnectionError", message=str(e))
    except ProcessError as e:
        print(f"[error] Process error: {e}")
        logger.log("error", "error", error_type="ProcessError", message=str(e))
    finally:
        logger.close()
