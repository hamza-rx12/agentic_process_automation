# Agentic Process Automation

Alert- and email-triggered process automation powered by Claude, the A2A
protocol, and a local Grafana stack.

## How it works

```
Alertmanager  ─┐
               ├─► listener ─► RabbitMQ ─► orchestrator ─► agent (A2A)
IMAP / Proton ─┘                                            │
                                                            ├─► browser-agent ─► Playwright
                                                            └─► monitor-agent ─► Grafana (Loki + Prometheus)
```

1. **listener** — two ingress paths share one queue:
   - `POST /alerts` receives Alertmanager webhooks
   - IMAP IDLE (Proton Bridge or any IMAP server) watches a mailbox
2. **orchestrator** — consumes the queue and routes each task to the
   right A2A agent via `A2AClient`
3. **agents** — Claude Agent SDK workers exposed over HTTP:
   - `browser-agent` drives a headless browser with Playwright
   - `monitor-agent` queries Loki/Prometheus via Grafana and can write
     dashboards/alert rules back

## Services

| Service         | Port  | Trigger                                    |
| --------------- | ----- | ------------------------------------------ |
| `listener`      | 9000  | Alertmanager `POST /alerts` + IMAP IDLE    |
| `orchestrator`  | –     | RabbitMQ consumer                          |
| `browser-agent` | 8080  | A2A HTTP                                   |
| `monitor-agent` | 8081  | A2A HTTP                                   |

## Repo layout

```
apa/
├── services/            # one directory per service, each with its own Dockerfile
│   ├── listener/
│   ├── orchestrator/
│   ├── browser-agent/
│   └── monitor-agent/
├── k8s/
│   ├── charts/apa/      # mono-chart deploying the four services + dashboards
│   ├── infra/           # cnpg cluster, kube-prometheus, loki, alloy values
│   ├── argocd/          # root + per-app Applications (app-of-apps)
│   └── kind-config.yaml # local kind cluster config + NodePort mappings
├── monitoring/          # legacy compose-native configs (prometheus, alloy, loki)
├── docker-compose.yml   # alternative local stack
├── Makefile             # `make up`, `make argocd-up`, `make down`, …
└── docs/                # architecture notes, migration reports
```

## Quick start — Kubernetes (recommended)

Builds run in CI and publish to `ghcr.io/hamza-rx12/apa-<svc>:latest`;
local kind pulls from there.

```bash
cp .env.example .env     # fill in AIPLATFORM_API_KEY and the rest

# Manual flow
make up                  # kind cluster + infra charts + helm install apa
make forward             # port-forward Grafana / Prom / AM / RabbitMQ / listener

# GitOps flow
make argocd-up           # kind + argocd + root Application → syncs everything
make argocd-forward      # ArgoCD UI on http://localhost:8080
make argocd-password     # initial admin password
```

Host ports exposed by kind (see `k8s/kind-config.yaml`):

| Port  | Target                        |
| ----- | ----------------------------- |
| 3000  | Grafana                       |
| 8080  | ArgoCD UI                     |
| 9000  | listener `/alerts` webhook    |
| 9090  | Prometheus                    |
| 9093  | Alertmanager                  |
| 15672 | RabbitMQ management           |

Tear down with `make down`.

## Quick start — docker compose

```bash
cp .env.example .env
docker compose up --build
```

Same topology, same ports. Useful when you don't need Kubernetes.

## Secrets

Every service pulls its config from `envFrom: apa-secrets`. In the
`make up` flow the secret is created from `.env` with
`kubectl create secret generic apa-secrets --from-env-file=.env`.

In production, swap it for External Secrets Operator pointing at AWS
Secrets Manager (or equivalent) — the deployment template doesn't care
where the secret comes from.

## Adding a new agent

1. `services/myagent/` — add `app/` and a `Dockerfile`
2. Implement the A2A server (copy from `browser-agent`)
3. Add it to `.github/workflows/build-push.yml` `matrix.service`
4. Register it under `.Values.services.myagent` in `k8s/charts/apa/values.yaml`

## Further reading

- `docs/target-architecture.md` — end-state design
- `docs/monitoring-agent-architecture.md` — monitor-agent internals
- `docs/project-report.md` — higher-level project report
- `docs/migration_report_claude_sdk_to_ado_agent.md` — SDK migration notes
