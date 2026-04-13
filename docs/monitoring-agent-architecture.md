# Monitor Agent Architecture

## Goal

Add a fourth service, `monitor-agent`, built from the same ado-agent template as
`browser-agent`. It queries logs and metrics through Grafana and creates
dashboards / alert rules. The orchestrator dispatches to it over A2A, just like
it already does with the browser agent.

Alongside the agent, stand up a minimal observability stack
(Prometheus, Loki, Promtail, Grafana, Alertmanager) so there is something real
for the agent to query.

---

## 1. High-level architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              docker-compose                                  │
│                                                                              │
│  ┌──────────┐      ┌──────────┐       ┌────────────────┐                     │
│  │ listener │─────▶│ RabbitMQ │──────▶│  orchestrator  │                     │
│  │IMAP IDLE │ AMQP │          │ AMQP  │ (ado-agent)    │                     │
│  │ +/alerts │      └──────────┘       └───────┬────────┘                     │
│  └──────┬───┘                                 │ A2A (HTTP)                   │
│         ▲                          ┌──────────┴───────────┐                  │
│         │ webhook                  │                      │                  │
│  ┌──────┴──────┐             ┌─────▼──────┐      ┌────────▼─────┐            │
│  │Alertmanager │             │browser-agt │      │monitor-agent │            │
│  └─────────────┘             │ :8080      │      │ :8081        │            │
│         ▲                    │ado-agent   │      │ado-agent     │            │
│         │                    └────────────┘      └──────┬───────┘            │
│         │ alerts                                        │ HTTP               │
│         │                                         ┌─────▼────┐               │
│  ┌──────┴────┐                                    │ Grafana  │               │
│  │Prometheus │◄──────── scrape /metrics ──────────┤  :3000   │               │
│  │  :9090    │                                    └─────┬────┘               │
│  └───────────┘                                          │                    │
│        ▲                                         proxy LogQL + PromQL        │
│        │                                                │                    │
│  ┌─────┴────┐        ┌─────────┐        ┌───────────────┴────┐               │
│  │ browser  │        │  Loki   │◄───────┤    Prometheus      │               │
│  │/metrics  │        │ :3100   │        │      :9090         │               │
│  └──────────┘        └────▲────┘        └────────────────────┘               │
│                           │                                                  │
│                     ┌─────┴─────┐                                            │
│                     │ Promtail  │◄── Docker stdout of all services           │
│                     └───────────┘                                            │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Two trigger modes

### Mode A — on-demand (email)

```
 Email ─► Listener ─► RMQ ─► Orchestrator ──A2A──► monitor-agent
                                                         │
                                                         ▼
                                                 Grafana datasource
                                                 proxy → LogQL/PromQL
                                                         │
                                                         ▼
                                                 create dashboard
                                                 return summary
```

### Mode B — reactive (alert)

```
 Prometheus ──fires──► Alertmanager ──webhook──► Listener /alerts
                                                       │
                                              wrap as {"source":"alert"}
                                                       │
                                                       ▼
                                                      RMQ
                                                       │
                                                       ▼
                                                 Orchestrator
                                                       │ (source=alert → monitor dispatch)
                                                       ▼
                                                 monitor-agent
                                                       │
                                                       ▼
                                                 analyze alert,
                                                 query related logs,
                                                 create runbook dashboard
```

Mode B reuses the existing RMQ path. The only new HTTP surface in the whole
system is the listener's `/alerts` endpoint.

---

## 3. Data flow — logs vs metrics

```
                        LOGS                                  METRICS
                        ────                                  ───────

  ┌────────────┐   stdout   ┌──────────┐         ┌────────────┐ /metrics
  │ containers │───────────▶│ Promtail │         │browser-agt │─────────┐
  └────────────┘            └─────┬────┘         └────────────┘         │
                                  │                                     │
                                  ▼                                     ▼
                             ┌─────────┐                          ┌──────────┐
                             │  Loki   │                          │Prometheus│
                             │ LogQL   │                          │  PromQL  │
                             └────┬────┘                          └─────┬────┘
                                  │                                     │
                                  └──────────┬──────────────────────────┘
                                             ▼
                                      ┌─────────────┐
                                      │   Grafana   │
                                      │ (datasource │
                                      │   proxy)    │
                                      └──────┬──────┘
                                             │ HTTP
                                             ▼
                                      ┌─────────────┐
                                      │monitor-agent│
                                      │  Claude     │
                                      │  decides    │
                                      │  what to    │
                                      │  query      │
                                      └─────────────┘
```

The agent never talks to Loki or Prometheus directly — everything goes through
Grafana's datasource proxy. One auth surface (service account token), two tools
instead of four.

---

## 4. Monitor agent internals

```
┌─────────────────────────────────────────────────────────┐
│                    monitor-agent                        │
│                                                         │
│  ┌──────────────┐      ┌──────────────────────────┐     │
│  │ClaudeAIAgent │      │   local SDK MCP server   │     │
│  │ (same as     │─────▶│  (auto-discovered tools) │     │
│  │  browser-    │      │                          │     │
│  │  agent)      │      │  • tool_grafana_query    │     │
│  └──────┬───────┘      │      (LogQL + PromQL)    │     │
│         │              │  • tool_grafana_artifact │     │
│         │              │      (dashboards + rules)│     │
│         ▼              └──────────────────────────┘     │
│  ┌──────────────┐                                       │
│  │ClaudeAIAgent │                                       │
│  │  Executor    │  ──── A2A bridge ────▶  orchestrator  │
│  │ (a2a_core/)  │                                       │
│  └──────────────┘                                       │
│                                                         │
│  allowed_tools = [mcp__local_tools__*]                  │
│  external_mcp_servers = {}                              │
└─────────────────────────────────────────────────────────┘
```

---

## 5. Key decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Framework | ADO-agent template (copy of `browser-agent`) | Symmetry, minimal diff, orchestrator dispatch stays uniform |
| Base image | `python:3.12-slim` + `uv` | No browser needed; uv matches the rest of the repo |
| Observability tools | **Grafana datasource proxy only** | Two tools instead of four, one auth surface |
| Alert webhook target | **Listener** (not orchestrator) | Orchestrator is a pure `pika` blocking consumer; adding HTTP there forces an aio-pika refactor. Listener already translates external events → RMQ |
| Metrics endpoints | **Phase 1: `browser-agent` only** | It already runs Starlette — mount `prometheus_client.make_asgi_app()` next to `/health`. Others defer until logs alone aren't enough |
| Log collection | Promtail on Docker stdout | Zero app-code changes |
| Tool gating | `get_allowed_tools()` returns only local MCP tools | Agent must not touch `Bash`, `WebFetch`, `Read` — non-negotiable |
| External MCP servers | None | No stdio MCP, just local auto-discovered tools |
| System prompt style | Flat paragraph with inline backticks | `AppConfig._normalize_prompt_string` collapses newlines / strips markdown — don't fight it |
| Artifact persistence | Named volumes for every stack service | The agent's whole job is creating durable dashboards/alerts |
| Alert loop protection | Label + route + listener drop filter (see §6) | Two independent guards |

### 6. Alert loop guards

```
 monitor-agent fails
         │
         ▼
   Prometheus rule fires  ── has label service="monitor-agent"
         │
         ▼
    Alertmanager
         │
    ┌────┴────────────────────────────┐
    │ route match created_by=monitor  │───▶  null receiver  (guard #1)
    └────┬────────────────────────────┘
         │
         ▼
   listener /alerts
         │
    ┌────┴────────────────────────────┐
    │ drop if labels.service ==       │───▶  ignored         (guard #2)
    │       "monitor-agent"           │
    └────┬────────────────────────────┘
         │
         ▼
       RMQ
```

Every rule the agent authors is stamped with `created_by: monitor-agent`.
Alertmanager routes anything with that label to a null receiver. The listener's
`/alerts` handler also drops any payload whose labels contain
`service=monitor-agent`. Belt and suspenders.

---

## 7. Service structure

Copy `services/browser-agent/` → `services/monitor-agent/`, then:

```
services/monitor-agent/
├── Dockerfile                # python:3.12-slim + uv (see §9)
├── requirements.txt          # drop playwright; keep claude-agent-sdk, a2a-sdk, httpx
├── .dockerignore
└── app/
    ├── __main__.py           # identical to browser-agent (A2A HTTP + /health)
    ├── config.py             # add get_observability_config()
    ├── a2a_core/             # unchanged
    ├── agent/                # unchanged
    ├── common/utils.py       # unchanged
    ├── configs/environment_vars/
    │   ├── _env.py                    # unchanged
    │   ├── agent_settings.py          # unchanged
    │   ├── model_settings.py          # unchanged
    │   ├── aiplatform_settings.py     # unchanged
    │   ├── general_settings.py        # unchanged
    │   ├── a2a_settings.py            # agent card: observability skill
    │   └── observability_settings.py  # NEW — GRAFANA_URL, GRAFANA_API_KEY
    ├── prompts/
    │   └── agent_system_prompt.txt    # flat paragraph, inline `backticks`
    └── tools/
        ├── __init__.py                # auto-discovery (unchanged)
        ├── tool_grafana_query.py      # LogQL + PromQL via datasource proxy
        └── tool_grafana_artifact.py   # dashboards + alert rules
```

### The two tools

- `tool_grafana_query` — `{datasource_uid, query, query_type: "logs"|"metrics", time_range}`
  → `POST /api/datasources/proxy/uid/<uid>/...` → parsed results.
- `tool_grafana_artifact` — `{kind: "dashboard"|"alert_rule", spec}`
  → `POST /api/dashboards/db` or `POST /api/v1/provisioning/alert-rules`,
  stamps `created_by: monitor-agent` on everything.

---

## 8. Orchestrator & listener changes

### Orchestrator

1. `configs/environment_vars/dispatch_settings.py` — add `MONITOR_AGENT_URL`.
2. `tools/tool_monitor_dispatch.py` — copy of `tool_browser_dispatch.py`, swap
   URL / name / description.
3. Prompt update — teach it when to pick monitor vs browser (the `source`
   field on the task is the cue).
4. `_format_email_prompt` → `_format_task_prompt(data)`, branching on
   `data["source"]` so alert payloads get a different framing than emails.

### Listener

1. Small Starlette `/alerts` route, served by uvicorn in a background thread
   (the IMAP IDLE loop is blocking, so the HTTP server gets its own thread).
2. Validate Alertmanager payload, drop loop-guard matches, wrap as
   `{"source": "alert", "message_id": <fingerprint>, "alert": <payload>}`,
   publish to the same RMQ queue.
3. New env vars: `ALERTS_HTTP_PORT` (default `9000`).

No change to the IMAP path.

---

## 9. Dockerfile (uv-based, matches existing services)

```dockerfile
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN uv venv /app/.venv

COPY requirements.txt .
RUN uv pip install --python /app/.venv/bin/python -r requirements.txt

COPY app/ app/

ENTRYPOINT ["/app/.venv/bin/python", "-m", "app"]
```

Same pattern as `services/browser-agent/Dockerfile` minus the Playwright base
image and the Chrome-path entrypoint shim.

---

## 10. Full `docker-compose.yml`

This is the *entire* file after the change, not just the additions. New
entries: `prometheus`, `loki`, `promtail`, `grafana`, `alertmanager`,
`monitor-agent`, plus volumes. Existing services pick up
`MONITOR_AGENT_URL` / `ALERTS_HTTP_PORT`.

```yaml
services:

  rabbitmq:
    image: rabbitmq:3-management-alpine
    ports:
      - "5672:5672"
      - "15672:15672"
    environment:
      RABBITMQ_SERVER_ADDITIONAL_ERL_ARGS: "-rabbit vm_memory_high_watermark 0.95"
    healthcheck:
      test: ["CMD", "rabbitmq-diagnostics", "check_port_connectivity"]
      interval: 10s
      timeout: 10s
      retries: 10
      start_period: 30s
    networks: [rpa]

  listener:
    build: ./services/listener
    env_file: .env
    environment:
      RABBITMQ_URL: amqp://guest:guest@rabbitmq/
      ALERTS_HTTP_PORT: "9000"
    ports:
      - "9000:9000"
    depends_on:
      rabbitmq: { condition: service_healthy }
    restart: unless-stopped
    networks: [rpa]

  browser-agent:
    build: ./services/browser-agent
    env_file: .env
    environment:
      PORT: "8080"
      HOST_OVERRIDE: "browser-agent"
      AGENT_NAME: "browser-agent"
      AGENT_DESCRIPTION: "Executes web browsing tasks using Playwright."
      BROWSER_HEADLESS: "true"
      LOG_LEVEL: "INFO"
    ports:
      - "8080:8080"
    healthcheck:
      test: ["CMD-SHELL", "/app/.venv/bin/python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8080/health')\""]
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 10s
    restart: unless-stopped
    networks: [rpa]

  monitor-agent:
    build: ./services/monitor-agent
    env_file: .env
    environment:
      PORT: "8081"
      HOST_OVERRIDE: "monitor-agent"
      AGENT_NAME: "monitor-agent"
      AGENT_DESCRIPTION: "Observability agent: queries logs/metrics and creates dashboards."
      GRAFANA_URL: http://grafana:3000
      GRAFANA_API_KEY: ""    # service account token — set via .env after first Grafana boot
      LOG_LEVEL: "INFO"
    ports:
      - "8081:8081"
    healthcheck:
      test: ["CMD-SHELL", "/app/.venv/bin/python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8081/health')\""]
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 10s
    depends_on:
      grafana: { condition: service_started }
    restart: unless-stopped
    networks: [rpa]

  orchestrator:
    build: ./services/orchestrator
    env_file: .env
    environment:
      RABBITMQ_URL: amqp://guest:guest@rabbitmq/
      BROWSER_AGENT_URL: http://browser-agent:8080
      MONITOR_AGENT_URL: http://monitor-agent:8081
      AGENT_NAME: "orchestrator"
      AGENT_DESCRIPTION: "Email-driven orchestrator that dispatches browser and monitor tasks."
      LOG_LEVEL: "INFO"
    depends_on:
      rabbitmq:     { condition: service_healthy }
      browser-agent:{ condition: service_healthy }
      monitor-agent:{ condition: service_healthy }
    restart: unless-stopped
    networks: [rpa]

  # ── Observability stack ──

  prometheus:
    image: prom/prometheus:v3.3.1
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus-data:/prometheus
    ports: ["9090:9090"]
    networks: [rpa]

  loki:
    image: grafana/loki:3.4
    volumes:
      - ./monitoring/loki.yml:/etc/loki/local-config.yaml:ro
      - loki-data:/loki
    ports: ["3100:3100"]
    networks: [rpa]

  promtail:
    image: grafana/promtail:3.4
    volumes:
      - ./monitoring/promtail.yml:/etc/promtail/config.yml:ro
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
    depends_on: [loki]
    networks: [rpa]

  grafana:
    image: grafana/grafana:11.6
    environment:
      GF_SECURITY_ADMIN_PASSWORD: admin
    volumes:
      - grafana-data:/var/lib/grafana
      - ./monitoring/grafana/provisioning:/etc/grafana/provisioning:ro
    ports: ["3000:3000"]
    depends_on: [loki, prometheus]
    networks: [rpa]

  alertmanager:
    image: prom/alertmanager:v0.28
    volumes:
      - ./monitoring/alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro
      - alertmanager-data:/alertmanager
    ports: ["9093:9093"]
    networks: [rpa]

volumes:
  prometheus-data:
  loki-data:
  grafana-data:
  alertmanager-data:

networks:
  rpa:
    driver: bridge
```

Grafana service account token is a manual first-run step: boot the stack,
create the token in the Grafana UI, drop it in `.env` as `GRAFANA_API_KEY`,
restart `monitor-agent`.

---

## 11. Build order

Each step is independently verifiable and rollback-able.

```
 Phase 1 ─ observability stack up, no agent
           └─ Grafana loads, Loki shows container logs, Prometheus targets green

 Phase 2 ─ /metrics on browser-agent only
           └─ Prometheus scrape returns non-zero series

 Phase 3 ─ monitor-agent service + 2 Grafana tools + orchestrator dispatch
           └─ fake email: "check browser-agent health" → agent queries Grafana,
              returns summary

 Phase 4 ─ listener /alerts webhook + source discriminator in orchestrator
           └─ curl a test alert → listener → RMQ → orchestrator → monitor-agent

 Phase 5 ─ first agent-authored dashboard + alert rule
           └─ rule fires, Alertmanager routes non-monitor alerts to listener,
              agent produces a runbook dashboard
```

If phase 3 reveals the Grafana-proxy-only decision was wrong, only two tools
exist to rewrite — not four.

---

## 12. Out of scope (for now)

- Metrics endpoints on `listener` and `orchestrator` (defer until logs alone
  aren't enough).
- Dashboards-as-code / GitOps for Grafana provisioning.
- Multi-tenant Grafana service account automation.
- Retention tuning for Loki/Prometheus — defaults are fine for a dev rig,
  revisit if disk pressure shows up.
