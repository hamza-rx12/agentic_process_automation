# Migration Plan: Claude SDK → ADO-Agent Framework

## Goal

Restructure `agentic_rpa` into **three independent containerized services** that
communicate via A2A and RabbitMQ. Each LLM-driven service is built on top of the
`ado-agent` framework (used as a per-service template), not embedded as a shared
library.

---

## Target Architecture

```
┌──────────────┐      ┌──────────────┐       ┌────────────────────┐
│  listener    │─────▶│   RabbitMQ   │──────▶│   orchestrator     │
│  (IMAP IDLE) │ AMQP │              │ AMQP  │   (ado-agent)      │
└──────────────┘      └──────────────┘       └─────────┬──────────┘
                                                       │ A2A (HTTP)
                                                       ▼
                                            ┌────────────────────┐
                                            │   browser-agent    │
                                            │   (ado-agent)      │
                                            │   + Playwright MCP │
                                            └────────────────────┘
```

| Service | Role | Type | Inbound | Outbound |
|---|---|---|---|---|
| `listener` | Watches mailbox via IMAP IDLE, pushes envelopes to RabbitMQ | Plain Python service (no LLM) | IMAP | RabbitMQ |
| `orchestrator` | Reads email task, plans, dispatches subtasks | ADO-agent (RabbitMQ consumer + A2A client) | RabbitMQ | A2A → browser-agent |
| `browser-agent` | Executes browser automation via Playwright MCP | ADO-agent (A2A server) | A2A | Playwright (stdio MCP) |

---

## Repository Layout

Monorepo with three self-contained service directories. Each ado-agent service
mirrors the upstream `ado-agent` template structure exactly so future framework
updates can be merged with minimal friction.

```
agentic_rpa/
├── services/
│   │
│   ├── listener/
│   │   ├── app/
│   │   │   ├── __main__.py          # current apa/listener.py logic
│   │   │   ├── config.py            # IMAP + RabbitMQ env vars
│   │   │   └── mail/                # moved from apa/mail/
│   │   │       ├── base.py
│   │   │       ├── imap.py
│   │   │       └── protonmail.py
│   │   ├── requirements.txt         # pika, imapclient, python-dotenv
│   │   └── Dockerfile
│   │
│   ├── orchestrator/                # ado-agent template
│   │   ├── app/
│   │   │   ├── __main__.py          # RabbitMQ consumer → ClaudeAIAgent.invoke()
│   │   │   ├── config.py            # AppConfig
│   │   │   ├── agent/
│   │   │   │   ├── claude_agent.py
│   │   │   │   ├── agent_support.py
│   │   │   │   ├── tool_callbacks.py
│   │   │   │   └── agent_skills.json
│   │   │   ├── tools/
│   │   │   │   ├── __init__.py      # auto-discovery
│   │   │   │   └── tool_browser_dispatch.py
│   │   │   ├── configs/environment_vars/
│   │   │   │   ├── agent_settings.py
│   │   │   │   ├── model_settings.py
│   │   │   │   ├── aiplatform_settings.py
│   │   │   │   ├── general_settings.py
│   │   │   │   ├── rabbitmq_settings.py     # NEW vs upstream
│   │   │   │   └── a2a_settings.py          # BROWSER_AGENT_URL
│   │   │   ├── prompts/
│   │   │   │   └── agent_system_prompt.txt
│   │   │   └── common/
│   │   │       └── utils.py
│   │   ├── requirements.txt
│   │   └── Dockerfile
│   │
│   └── browser-agent/               # ado-agent template
│       ├── app/
│       │   ├── __main__.py          # Starlette/A2A HTTP server
│       │   ├── config.py            # AppConfig (extended for stdio MCP)
│       │   ├── agent/
│       │   │   ├── claude_agent.py
│       │   │   ├── agent_support.py # extended to register Playwright MCP
│       │   │   ├── tool_callbacks.py
│       │   │   └── agent_skills.json
│       │   ├── a2a_core/
│       │   │   ├── agent_executor.py
│       │   │   ├── agent_card.py
│       │   │   └── a2a_conversions.py
│       │   ├── tools/
│       │   │   └── __init__.py      # empty — Playwright is external
│       │   ├── configs/environment_vars/
│       │   │   ├── agent_settings.py
│       │   │   ├── model_settings.py
│       │   │   ├── aiplatform_settings.py
│       │   │   ├── general_settings.py
│       │   │   ├── browser_settings.py      # NEW (headless, viewport, exec path)
│       │   │   └── a2a_settings.py
│       │   ├── prompts/
│       │   │   └── agent_system_prompt.txt  # current browser SYSTEM_PROMPT
│       │   └── common/
│       │       └── utils.py
│       ├── requirements.txt
│       └── Dockerfile
│
├── docker-compose.yml               # 4 services: rabbitmq + the 3 above
├── .env                             # shared secrets
├── .env.example
└── docs/
    └── migration_report_claude_sdk_to_ado_agent.md  (this file)
```

---

## Service-by-Service Plan

### 1. `services/listener/`

**Purpose:** unchanged from current `apa/listener.py`. Just lifted out of the `apa`
package into its own deployable.

**Steps:**
1. Copy `apa/listener.py` → `services/listener/app/__main__.py`
2. Copy `apa/mail/` → `services/listener/app/mail/`
3. Extract the subset of `apa/config.py` it needs (EMAIL, APP_PASSWORD, IMAP_*,
   MAIL_BACKEND, RABBITMQ_URL, RABBITMQ_QUEUE) into `services/listener/app/config.py`
4. Update imports (`from apa.*` → `from app.*`)
5. Write minimal `requirements.txt` (`pika`, `imapclient`, `python-dotenv`)
6. Write `Dockerfile` based on `python:3.11-slim`

**Risk:** low. No logic changes.

---

### 2. `services/orchestrator/`

**Purpose:** consume RabbitMQ messages, run a Claude agent that decides what to
do, and dispatch browser subtasks via A2A.

**Steps:**

1. **Bootstrap from `ado-agent` template**
   Copy the entire `~/Downloads/ado-agent/app/` tree to `services/orchestrator/app/`.
   This is the starting point — we then prune and extend.

2. **Prune what we don't need**
   - Delete `app/tools/tool_ado_user.py` (azure devops tool)
   - Delete any ADO-specific settings file
   - Delete `app/a2a_core/` entirely — orchestrator is **not** an A2A server,
     it's an A2A *client*. It uses `ClaudeAIAgent.invoke()` directly from a
     RabbitMQ consumer loop.

3. **Add RabbitMQ settings module**
   Create `app/configs/environment_vars/rabbitmq_settings.py` exposing
   `RABBITMQ_URL` and `RABBITMQ_QUEUE`. Register it in `AppConfig`.

4. **Add A2A settings module**
   Create `app/configs/environment_vars/a2a_settings.py` exposing
   `BROWSER_AGENT_URL`. Register it in `AppConfig`.

5. **Port the dispatch tool**
   Create `app/tools/tool_browser_dispatch.py` containing the inline
   `dispatch_browser_task` from the current `apa/orchestrator.py`, refactored
   into the framework's auto-discovery pattern:

   ```python
   # app/tools/tool_browser_dispatch.py
   from claude_agent_sdk import tool
   from app.config import AppConfig

   async def _send_to_browser_agent(instruction: str) -> str:
       # existing _send_to_browser_agent logic, but read URL from AppConfig
       ...

   @tool(
       name="dispatch_browser_task",
       description="Dispatch a web browsing task to the browser agent.",
       input_schema={...},
   )
   async def dispatch_browser_task_mcp(args: dict) -> dict:
       instruction = args.get("instruction", "")
       text = await _send_to_browser_agent(instruction)
       return {"content": [{"type": "text", "text": text}]}

   __all__ = ["dispatch_browser_task_mcp"]
   ```

   Auto-discovery in `app/tools/__init__.py` will pick it up. No manual
   registration needed.

6. **Write the entry point**
   Replace `app/__main__.py` with a RabbitMQ consumer loop. Pseudocode:

   ```python
   # app/__main__.py
   from app.agent.claude_agent import ClaudeAIAgent
   from app.config import AppConfig
   import pika, json, anyio

   agent = ClaudeAIAgent()  # built once, reused

   async def handle(email_data: dict):
       prompt = format_email_prompt(email_data)
       result = await agent.invoke(prompt, context_id=email_data["message_id"])
       log.info("done: %s", result["text"])

   def main():
       rmq = AppConfig.get_rabbitmq_config()
       conn = pika.BlockingConnection(pika.URLParameters(rmq.URL))
       ch = conn.channel()
       ch.queue_declare(queue=rmq.QUEUE, durable=True)
       ch.basic_qos(prefetch_count=1)
       ch.basic_consume(rmq.QUEUE, on_message_callback=callback)
       ch.start_consuming()
   ```

7. **Port the system prompt**
   Move the current orchestrator `SYSTEM_PROMPT` string into
   `app/prompts/agent_system_prompt.txt`. `AppConfig.get_system_prompt()`
   will load it automatically.

8. **`requirements.txt`**
   `claude-agent-sdk`, `a2a-sdk`, `httpx`, `pika`, `python-dotenv`

9. **`Dockerfile`**
   Copy from upstream `ado-agent/Dockerfile`, no changes needed.

**Risk:** medium. The dispatch tool's A2A client logic must be ported carefully;
the current implementation uses `ClientFactory` with a shared `httpx.AsyncClient`
and `timeout=None` — that nuance must be preserved (this was an explicit fix in
commit `dfedc22`).

---

### 3. `services/browser-agent/`

**Purpose:** A2A HTTP server that executes browser tasks. The Playwright MCP
server is wired in as an **external stdio MCP**, not via the framework's
`tools/` auto-discovery.

**Steps:**

1. **Bootstrap from `ado-agent` template**
   Copy `~/Downloads/ado-agent/app/` to `services/browser-agent/app/`.

2. **Prune**
   - Delete `app/tools/tool_ado_user.py`
   - Leave `app/tools/__init__.py` and the auto-discovery wiring in place
     (we may add local tools later)

3. **Add browser settings module**
   Create `app/configs/environment_vars/browser_settings.py`:

   ```python
   class BrowserSettings:
       HEADLESS = os.getenv("BROWSER_HEADLESS", "false").lower() == "true"
       VIEWPORT = os.getenv("BROWSER_VIEWPORT", "1280x720")
       EXECUTABLE = os.getenv("BROWSER_EXECUTABLE", "/usr/bin/chromium")
   browser_settings = BrowserSettings()
   ```

   Register it in `AppConfig`.

4. **Extend `AppConfig` to expose Playwright MCP**
   Add a method `create_playwright_mcp_server()` that returns the
   `McpStdioServerConfig` (logic lifted from current `apa/config.py:get_playwright_mcp`).

5. **Extend `agent_support.build_claude_options`**
   The upstream version only attaches one MCP server (the local SDK MCP server).
   We need it to also accept and attach an external stdio MCP. Two options:

   - **Option A (preferred):** add a new parameter `external_mcp_servers: dict`
     and merge it into `mcp_servers` alongside `local_tools`.
   - **Option B:** override in `claude_agent.py` — build `options.mcp_servers`
     manually before passing to `ClaudeSDKClient`.

   Option A is cleaner and keeps the diff against upstream small.

6. **Wire Playwright into `ClaudeAIAgent.__init__`**
   In `app/agent/claude_agent.py`, after creating the local MCP server, also
   create the Playwright stdio MCP and pass both to `build_claude_options`:

   ```python
   self.playwright_mcp = AppConfig.create_playwright_mcp_server()
   self.options = build_claude_options(
       ...,
       local_mcp_server=self.local_mcp_server,
       external_mcp_servers={"playwright": self.playwright_mcp},
   )
   ```

   Also set `allowed_tools=["mcp__playwright__*"]` and the existing
   `disallowed_tools` list from the current `get_agent_options()`.

7. **Port the system prompt**
   Copy the current browser `SYSTEM_PROMPT` into
   `app/prompts/agent_system_prompt.txt`.

8. **Port the agent card**
   Replace the upstream agent skills with a single `browse` skill (mirrors
   the current `apa/agents/browser/server.py:agent_card`).

9. **Entry point**
   Use the upstream `app/__main__.py` largely as-is — it already starts the
   A2A HTTP server with `ClaudeAIAgentExecutor`. Read port from `general_settings.PORT`.

10. **Health endpoint**
    Add `GET /health` returning `{"status": "ok"}` so docker-compose health
    checks keep working.

11. **`Dockerfile`**
    Must include Node.js + `npx` (Playwright MCP is an npm package) **and**
    Chromium. Base on the current `docker/agent.Dockerfile` — keep its system
    package list, layer in Python deps from upstream `ado-agent/Dockerfile`.

**Risk:** medium-high. The Playwright stdio MCP integration is the main
deviation from the upstream framework. `build_claude_options` needs careful
extension and testing.

---

### 4. Root `docker-compose.yml`

Replace the current compose file with one that builds from the new locations:

```yaml
services:
  rabbitmq:
    image: rabbitmq:3-management-alpine
    # ... unchanged ...

  listener:
    build: ./services/listener
    env_file: .env
    environment:
      RABBITMQ_URL: amqp://guest:guest@rabbitmq/
    depends_on:
      rabbitmq: { condition: service_healthy }
    networks: [rpa]

  browser-agent:
    build: ./services/browser-agent
    env_file: .env
    environment:
      PORT: "8080"
      BROWSER_HEADLESS: "true"
    ports: ["8080:8080"]
    healthcheck:
      test: ["CMD-SHELL", "python3 -c \"import urllib.request; urllib.request.urlopen('http://localhost:8080/health')\""]
      interval: 15s
    networks: [rpa]

  orchestrator:
    build: ./services/orchestrator
    env_file: .env
    environment:
      RABBITMQ_URL: amqp://guest:guest@rabbitmq/
      BROWSER_AGENT_URL: http://browser-agent:8080
    depends_on:
      rabbitmq: { condition: service_healthy }
      browser-agent: { condition: service_healthy }
    networks: [rpa]

networks:
  rpa: { driver: bridge }
```

---

## Migration Order

Bottom-up — each phase is independently testable.

| Phase | Service | Goal | Verification |
|---|---|---|---|
| 1 | `listener` | Lift-and-shift, no LLM | Send a test email → see message in RabbitMQ management UI |
| 2 | `browser-agent` | Standalone A2A server | `curl POST /` with a simple browse task, get a result |
| 3 | `orchestrator` | RabbitMQ → A2A bridge | End-to-end: email → listener → orchestrator → browser-agent |
| 4 | Decommission `apa/` | Delete old package, update root files | `docker-compose up` works from fresh clone |

Each phase should be a separate commit (or PR) so we can roll back cleanly.

---

## Things That Disappear

After migration, these are deleted entirely:

- `apa/` package (everything)
- `docker/agent.Dockerfile` (replaced by per-service Dockerfiles)
- `docker/orchestrator.Dockerfile` (same)
- `apa/a2a/` custom A2A wrappers (replaced by direct `a2a-sdk` usage in
  the orchestrator's dispatch tool and in `browser-agent`'s `a2a_core/`)

---

## Open Questions

1. **Logging:** the current `apa/log.py` writes JSONL session logs to
   `logs/`. Should each service keep its own `logs/` mount, or do we move to
   centralized logging (e.g. stdout only, scraped by docker)? The `ado-agent`
   template uses centralized stdout via `app/common/utils.py` — recommend
   adopting that and dropping `logs/` mounts.

2. **Shared code:** do we keep a shared `python` library for things like the
   email envelope dataclass that listener and orchestrator both need? Or
   duplicate the small dataclass in both services? Recommend duplicating —
   it's ~10 lines and keeps services truly independent.

3. **Future agents:** if we add more specialist agents (e.g. a code-execution
   agent), each one becomes another `services/<name>/` directory built from
   the same `ado-agent` template. The orchestrator gains a new
   `tool_<name>_dispatch.py` and a new env var for the URL. No structural
   changes elsewhere.

---

*Plan revised after reviewing current `apa/` codebase and the `ado-agent`
template at `~/Downloads/ado-agent/`.*
