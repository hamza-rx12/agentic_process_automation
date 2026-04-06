# Agentic Process Automation

Email-triggered process automation powered by Claude and Playwright.

## How it works

```
Email → listener → RabbitMQ → orchestrator → agent (A2A) → Browser
```

1. **listener** — polls for new emails, publishes to RabbitMQ
2. **orchestrator** — consumes tasks, dispatches to agents via A2A
3. **agents** — execute tasks (browser agent uses Playwright)

## Structure

```
apa/
├── config.py              # shared settings
├── log.py                 # session logger
├── orchestrator.py        # RabbitMQ → agent dispatcher
├── listener.py            # email → RabbitMQ
├── a2a/                   # agent-to-agent protocol
│   ├── types.py           # A2A dataclasses
│   └── client.py          # A2AClient
├── mail/                  # email backends
│   ├── base.py            # MailConnection ABC
│   ├── imap.py            # standard IMAP
│   └── protonmail.py      # ProtonMail Bridge
└── agents/                # one directory per agent
    └── browser/
        ├── agent.py       # run(instruction) → AgentResult
        └── server.py      # A2A HTTP server
docker/
├── agent.Dockerfile
└── orchestrator.Dockerfile
```

## Adding a new agent

1. Create `apa/agents/myagent/`
2. Add `agent.py` — implement `async def run(instruction: str) -> AgentResult`
3. Add `server.py` — A2A HTTP server (copy from `browser/server.py`)
4. Add a Dockerfile + wire into `docker-compose.yml`

## Quick start

```bash
cp .env.example .env     # fill in your keys
uv sync
python -m apa "go to google.com and search for weather"
```

## Docker

```bash
docker compose up
```
