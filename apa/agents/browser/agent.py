"""Browser agent: executes web tasks via Claude + Playwright MCP."""

import json

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeSDKClient,
    CLIConnectionError,
    CLINotFoundError,
    ProcessError,
    RateLimitEvent,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

from apa.agents import AgentResult
from apa.config import get_agent_options
from apa.log import SessionLogger

# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------


def _summarize_tool(name: str, inp: dict) -> str:
    name = name.removeprefix("mcp__playwright__")
    if "url" in inp:
        return f"{name}: {inp['url']}"
    if "text" in inp:
        t = inp["text"]
        return f'{name}: "{t[:57]}..."' if len(t) > 60 else f'{name}: "{t}"'
    if "key" in inp:
        return f"{name}: {inp['key']}"
    if "ref" in inp:
        s = f"ref={inp['ref']}"
        if "value" in inp:
            s += f' value="{inp["value"][:40]}"'
        return f"{name}: {s}"
    if inp:
        c = json.dumps(inp, default=str)
        return f"{name}: {c[:77]}..." if len(c) > 80 else f"{name}: {c}"
    return name


def _handle_message(msg, log: SessionLogger | None = None) -> None:
    if isinstance(msg, RateLimitEvent):
        if log:
            log.log(
                "warning",
                "rate_limit",
                rate_limit_type=getattr(msg, "type", None),
                resets_at=getattr(msg, "resets_at", None),
            )
        return

    if isinstance(msg, SystemMessage):
        if msg.subtype == "init":
            print("[system] Agent session started")
            if log:
                log.log("info", "session_start", session_id=log.session_id)
        return

    if isinstance(msg, AssistantMessage):
        if hasattr(msg, "error") and msg.error:
            if log:
                log.log("error", "agent_error", error=msg.error)
        for block in msg.content:
            if isinstance(block, TextBlock):
                print(f"\n{block.text}")
                if log:
                    log.log("info", "text", text=block.text)
            elif isinstance(block, ToolUseBlock):
                summary = _summarize_tool(block.name, block.input)
                print(f"  -> {summary}")
                if log:
                    log.log("info", "tool", summary=summary)
        return

    if isinstance(msg, ResultMessage):
        parts = []
        log_data: dict = {}
        if hasattr(msg, "usage") and msg.usage:
            u = msg.usage
            if (t := getattr(u, "turns", None)) is not None:
                parts.append(f"turns={t}")
                log_data["turns"] = t
            if (c := getattr(u, "cost_usd", None)) is not None:
                parts.append(f"cost=${c:.4f}")
                log_data["cost_usd"] = c
            if (d := getattr(u, "duration_ms", None)) is not None:
                log_data["duration_ms"] = d
        if stop := getattr(msg, "stop_reason", None):
            parts.append(f"stop={stop}")
            log_data["stop_reason"] = stop
        print(f"\n[done] {', '.join(parts) or 'finished'}")
        if log:
            log.log("info", "session_end", **log_data)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def run(instruction: str) -> AgentResult:
    """Run a single browser task. Returns AgentResult."""
    options = get_agent_options()
    log = SessionLogger()
    log.log(
        "info", "session_start", session_id=log.session_id, instruction=instruction, mode="single"
    )
    print(f"[task] {instruction}\n")

    last_output = ""
    try:
        async for msg in query(prompt=instruction, options=options):
            _handle_message(msg, log)
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        last_output = block.text
        return AgentResult(True, log.session_id, last_output)
    except (CLINotFoundError, CLIConnectionError, ProcessError) as e:
        print(f"[error] {e}")
        log.log("error", "error", error_type=type(e).__name__, message=str(e))
        return AgentResult(False, log.session_id, "", str(e))
    finally:
        log.close()


async def run_conversational() -> None:
    """Interactive multi-turn browser session."""
    options = get_agent_options()
    log = SessionLogger()
    log.log("info", "session_start", session_id=log.session_id, mode="conversational")
    print("Browser Agent — Interactive Mode")
    print("Type instructions. Ctrl+C to exit.\n")

    try:
        async with ClaudeSDKClient(options=options) as client:
            while True:
                try:
                    instruction = input("you> ").strip()
                except EOFError:
                    break
                if not instruction or instruction.lower() in ("exit", "quit", "q"):
                    break

                log.log("info", "user_instruction", instruction=instruction)
                await client.query(instruction)
                async for msg in client.receive_response():
                    _handle_message(msg, log)
                print()
    except KeyboardInterrupt:
        print("\n[exit] Session ended.")
    except (CLINotFoundError, CLIConnectionError, ProcessError) as e:
        print(f"[error] {e}")
        log.log("error", "error", error_type=type(e).__name__, message=str(e))
    finally:
        log.close()
