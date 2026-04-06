"""RabbitMQ consumer — receives email tasks and dispatches to browser agent via A2A."""

import json
import time
import uuid

import anyio
import httpx
import pika
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

from apa.a2a import (
    ClientConfig,
    ClientFactory,
    Part,
    Role,
    Task,
    TextPart,
)
from apa.a2a import (
    Message as A2AMessage,
)
from apa.config import (
    ANTHROPIC_API_KEY,
    BROWSER_AGENT_URL,
    MAX_TURNS,
    RABBITMQ_QUEUE,
    RABBITMQ_URL,
)

_BACKOFF_INITIAL = 5
_BACKOFF_MAX = 300

SYSTEM_PROMPT = """\
You are an APA orchestrator. You receive email requests and execute them by \
dispatching tasks to specialist agents.

When you receive an email:
1. Understand what the user wants
2. Formulate a clear, specific instruction for the browser agent
3. Use the dispatch_browser_task tool to execute it
4. Report the outcome concisely

If the task fails, retry once with a more specific instruction or report why it failed.
"""


def _handle_message(msg: object) -> None:
    if isinstance(msg, SystemMessage) and msg.subtype == "init":
        print("[orchestrator] Claude session started")
    elif isinstance(msg, AssistantMessage):
        for block in msg.content:
            if isinstance(block, TextBlock):
                print(f"\n{block.text}")
            elif isinstance(block, ToolUseBlock):
                inp = block.input or {}
                instr = inp.get("instruction", "")[:80]
                print(f'  -> {block.name}: "{instr}"')
    elif isinstance(msg, ResultMessage):
        parts = []
        if hasattr(msg, "usage") and msg.usage:
            if (t := getattr(msg.usage, "turns", None)) is not None:
                parts.append(f"turns={t}")
            if (c := getattr(msg.usage, "cost_usd", None)) is not None:
                parts.append(f"cost=${c:.4f}")
        if stop := getattr(msg, "stop_reason", None):
            parts.append(f"stop={stop}")
        print(f"\n[orchestrator] done — {', '.join(parts) or 'finished'}")


def _extract_text_from_parts(parts: list[Part]) -> str:
    """Extract text from a list of A2A Parts."""
    for part in parts:
        if isinstance(part.root, TextPart):
            return part.root.text
    return ""


def _extract_text_from_task(task: Task) -> str:
    """Extract output text from a completed task's artifacts."""
    if task.artifacts:
        for artifact in task.artifacts:
            text = _extract_text_from_parts(artifact.parts)
            if text:
                return text
    return "Task completed with no output."


def _extract_error_from_task(task: Task) -> str:
    """Extract error message from a failed task."""
    if task.status.message and task.status.message.parts:
        text = _extract_text_from_parts(task.status.message.parts)
        if text:
            return text
    return "Unknown error"


async def _send_to_browser_agent(instruction: str) -> Task | A2AMessage:
    """Send a task to the browser agent via A2A and return the result."""
    config = ClientConfig(streaming=False)
    factory = ClientFactory(config)

    async with httpx.AsyncClient(timeout=None) as http_client:
        from a2a.client.card_resolver import A2ACardResolver

        resolver = A2ACardResolver(http_client, BROWSER_AGENT_URL)
        card = await resolver.get_agent_card()
        client = factory.create(card)

        msg = A2AMessage(
            role=Role.user,
            message_id=str(uuid.uuid4()),
            parts=[Part(root=TextPart(text=instruction))],
        )

        async for event in client.send_message(msg):
            # event is (Task, UpdateEvent | None) or Message
            if isinstance(event, A2AMessage):
                return event
            # It's a tuple (Task, update)
            task, _update = event
            if task.status.state in ("completed", "failed", "canceled"):
                return task

    raise RuntimeError("No terminal response from browser agent")


async def process_email(email_data: dict) -> None:
    prompt = (
        f"You received this email:\n"
        f"From: {email_data.get('sender', 'unknown')}\n"
        f"Subject: {email_data.get('subject', '(no subject)')}\n\n"
        f"{email_data.get('body', '')}\n\n"
        f"Execute the requested task."
    )

    from claude_agent_sdk import create_sdk_mcp_server, tool

    @tool(
        name="dispatch_browser_task",
        description="Dispatch a web browsing task to the browser agent.",
        input_schema={
            "type": "object",
            "properties": {
                "instruction": {
                    "type": "string",
                    "description": "The browsing task",
                }
            },
            "required": ["instruction"],
        },
    )
    async def dispatch_browser_task(args: dict) -> dict:
        instruction = args.get("instruction", "")
        print(f"[orchestrator] dispatching: {instruction[:80]!r}")
        result = await _send_to_browser_agent(instruction)

        if isinstance(result, Task):
            if result.status.state == "completed":
                text = _extract_text_from_task(result)
                return {"content": [{"type": "text", "text": text}]}
            else:
                err = _extract_error_from_task(result)
                return {
                    "content": [{"type": "text", "text": f"FAILED: {err}"}],
                    "is_error": True,
                }
        else:
            text = _extract_text_from_parts(result.parts)
            return {"content": [{"type": "text", "text": text or "No output"}]}

    options = ClaudeAgentOptions(
        model="claude-haiku-4-5",
        system_prompt=SYSTEM_PROMPT,
        mcp_servers={"dispatch": create_sdk_mcp_server("dispatch", tools=[dispatch_browser_task])},
        allowed_tools=["dispatch_browser_task"],
        permission_mode="bypassPermissions",
        max_turns=MAX_TURNS,
    )

    async for msg in query(prompt=prompt, options=options):
        _handle_message(msg)


def _run_consumer() -> None:
    print(f"[orchestrator] Starting — queue={RABBITMQ_QUEUE!r}, agent={BROWSER_AGENT_URL!r}")
    backoff = _BACKOFF_INITIAL

    while True:
        try:
            conn = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
            ch = conn.channel()
            ch.queue_declare(queue=RABBITMQ_QUEUE, durable=True)
            ch.basic_qos(prefetch_count=1)
            print("[orchestrator] Connected — waiting for messages...")
            backoff = _BACKOFF_INITIAL

            def callback(
                ch: object,
                method: object,
                properties: object,
                body: bytes,
            ) -> None:
                try:
                    data = json.loads(body)
                    print(f"[orchestrator] Processing: {data.get('subject', '?')!r}")
                    anyio.run(process_email, data)
                except Exception as e:
                    print(f"[orchestrator] Error: {e}")
                finally:
                    ch.basic_ack(delivery_tag=method.delivery_tag)  # type: ignore[union-attr]

            ch.basic_consume(queue=RABBITMQ_QUEUE, on_message_callback=callback)
            ch.start_consuming()
        except KeyboardInterrupt:
            print("\n[orchestrator] Shutting down.")
            break
        except Exception as e:
            print(f"[orchestrator] Connection error: {e} — retrying in {backoff}s")
            time.sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX)


def main() -> None:
    if not ANTHROPIC_API_KEY:
        raise SystemExit("[orchestrator] ERROR: ANTHROPIC_API_KEY not set.")
    _run_consumer()


if __name__ == "__main__":
    main()
