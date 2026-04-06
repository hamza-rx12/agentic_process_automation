"""A2A HTTP server for the browser agent (using a2a-sdk)."""

import logging
import uuid

import uvicorn

from apa.a2a import (
    A2AFastAPIApplication,
    AgentCapabilities,
    AgentCard,
    AgentExecutor,
    AgentSkill,
    Artifact,
    DefaultRequestHandler,
    EventQueue,
    InMemoryTaskStore,
    Message,
    Part,
    RequestContext,
    Role,
    Task,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)
from apa.agents.browser.agent import run as run_browser
from apa.config import A2A_PORT, BROWSER_AGENT_URL

log = logging.getLogger("browser-agent")


# ---------------------------------------------------------------------------
# Suppress noisy health-check lines from uvicorn's access log
# ---------------------------------------------------------------------------

class _NoHealthCheck(logging.Filter):
    """Drop GET /health access-log entries so they don't flood the output."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        return "GET /health" not in record.getMessage()


class _RenameUvicornError(logging.Filter):
    """uvicorn uses 'uvicorn.error' for all lifecycle messages, not just errors.
    Rename it to plain 'uvicorn' so the logs don't look alarming.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        if record.name == "uvicorn.error":
            record.name = "uvicorn"
        return True


logging.getLogger("uvicorn.access").addFilter(_NoHealthCheck())
logging.getLogger("uvicorn.error").addFilter(_RenameUvicornError())

# ---------------------------------------------------------------------------
# AgentExecutor implementation
# ---------------------------------------------------------------------------


class BrowserAgentExecutor(AgentExecutor):
    """Bridges the browser agent into the A2A server framework."""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        instruction = context.get_user_input()
        task_id = context.task_id or ""
        context_id = context.context_id or ""

        short = (instruction[:80] + "...") if len(instruction) > 80 else instruction
        log.info("[task:%s] received — %s", task_id[:8], short)

        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.working),
                final=False,
            )
        )

        log.info("[task:%s] working ...", task_id[:8])
        result = await run_browser(instruction)

        if result.success:
            log.info("[task:%s] completed (session=%s)", task_id[:8], result.session_id)
            await event_queue.enqueue_event(
                Task(
                    id=task_id,
                    context_id=context_id,
                    status=TaskStatus(state=TaskState.completed),
                    artifacts=[
                        Artifact(
                            artifact_id=str(uuid.uuid4()),
                            parts=[Part(root=TextPart(text=result.output))],
                        )
                    ],
                )
            )
        else:
            log.error("[task:%s] failed — %s", task_id[:8], result.error)
            await event_queue.enqueue_event(
                Task(
                    id=task_id,
                    context_id=context_id,
                    status=TaskStatus(
                        state=TaskState.failed,
                        message=Message(
                            role=Role.agent,
                            message_id=str(uuid.uuid4()),
                            parts=[Part(root=TextPart(text=result.error or "unknown"))],
                        ),
                    ),
                )
            )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id or "",
                context_id=context.context_id or "",
                status=TaskStatus(state=TaskState.canceled),
                final=True,
            )
        )


# ---------------------------------------------------------------------------
# Agent card
# ---------------------------------------------------------------------------

agent_card = AgentCard(
    name="browser-agent",
    description="Executes web browsing tasks using Playwright",
    url=BROWSER_AGENT_URL,
    version="1.0.0",
    capabilities=AgentCapabilities(streaming=True),
    default_input_modes=["text"],
    default_output_modes=["text"],
    skills=[
        AgentSkill(
            id="browse",
            name="Web browsing",
            description="Navigate the web, extract info, perform actions",
            tags=["browser", "web"],
            examples=["Go to youtube.com and search for cats"],
        )
    ],
)


# ---------------------------------------------------------------------------
# Build app
# ---------------------------------------------------------------------------

task_store = InMemoryTaskStore()
executor = BrowserAgentExecutor()
handler = DefaultRequestHandler(
    agent_executor=executor,
    task_store=task_store,
)

a2a_app = A2AFastAPIApplication(
    agent_card=agent_card,
    http_handler=handler,
)

app = a2a_app.build(title="browser-agent-a2a")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    log.info("Starting browser-agent on port %d", A2A_PORT)
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=A2A_PORT,
        log_config={
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s %(levelname)-8s %(name)s — %(message)s",
                    "datefmt": "%H:%M:%S",
                }
            },
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "stream": "ext://sys.stdout",
                }
            },
            "loggers": {
                "uvicorn": {"handlers": ["default"], "level": "INFO"},
                "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
                "uvicorn.access": {"handlers": ["default"], "level": "INFO", "propagate": False},
                "browser-agent": {"handlers": ["default"], "level": "INFO", "propagate": False},
            },
        },
    )
