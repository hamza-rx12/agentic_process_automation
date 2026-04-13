"""
Bootstrap the A2A HTTP server for this Claude Agent SDK agent.
"""

import logging
import sys

import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore

from app.a2a_core.agent_card import build_agent_card
from app.a2a_core.agent_executor import ClaudeAIAgentExecutor
from app.config import AppConfig
from app.common.utils import build_skills_list, get_logger

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = get_logger(__name__)


def main():
    general = AppConfig.get_general_config()
    a2a = AppConfig.get_a2a_config()
    agent = AppConfig.get_agent_config()

    bind_host = "0.0.0.0"
    port = general.PORT
    streaming = general.STREAMING

    # HOST_OVERRIDE controls only the public URL advertised in the AgentCard;
    # the server still binds to 0.0.0.0 so docker networking works.
    public_host = general.HOST_OVERRIDE or bind_host
    public_url = f"http://{public_host}:{port}"

    skills = build_skills_list(a2a.AGENT_SKILLS)

    agent_card = build_agent_card(
        agent_name=agent.AGENT_NAME,
        public_url=public_url,
        streaming=streaming,
        description=a2a.AGENT_DESCRIPTION,
        version=a2a.AGENT_VERSION,
        default_input_modes=a2a.AGENT_DEFAULT_INPUT_MODES,
        default_output_modes=a2a.AGENT_DEFAULT_OUTPUT_MODES,
        push_notifications=a2a.AGENT_PUSH_NOTIFICATIONS,
        skills=skills or None,
    )

    executor = ClaudeAIAgentExecutor(streaming=streaming)
    handler = DefaultRequestHandler(agent_executor=executor, task_store=InMemoryTaskStore())
    app = A2AStarletteApplication(agent_card=agent_card, http_handler=handler)

    starlette_app = app.build()

    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def health(_request):
        return JSONResponse({"status": "ok"})

    starlette_app.router.routes.append(Route("/health", health, methods=["GET"]))

    logger.info("Starting A2A HTTP server on %s:%s (advertised %s)", bind_host, port, public_url)
    uvicorn.run(starlette_app, host=bind_host, port=port)


if __name__ == "__main__":
    main()
