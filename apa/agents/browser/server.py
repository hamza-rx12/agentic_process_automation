"""A2A HTTP server for the browser agent (using a2a-sdk)."""

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
from apa.config import A2A_PORT

# ---------------------------------------------------------------------------
# AgentExecutor implementation
# ---------------------------------------------------------------------------


class BrowserAgentExecutor(AgentExecutor):
    """Bridges the browser agent into the A2A server framework."""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        instruction = context.get_user_input()
        task_id = context.task_id or ""
        context_id = context.context_id or ""

        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.working),
                final=False,
            )
        )

        result = await run_browser(instruction)

        if result.success:
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
    url=f"http://localhost:{A2A_PORT}",
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
    uvicorn.run(app, host="0.0.0.0", port=A2A_PORT)
