# Postgres-as-queue-and-state migration plan

**Status:** In progress. Mark items `[x]` as they complete.
**Author:** Drafted by Opus 4.7, to be executed by Sonnet 4.6.
**Goal:** Replace RabbitMQ with a single `tasks` table in Postgres that serves
as both the work queue and the task-state store. Expose MCP tools so each
agent can read/write its own task row.

---

## Decisions (locked in)

1. **DB driver:** `asyncpg>=0.29` (native async, matches orchestrator + agents).
2. **Queue primitive:** hand-rolled `SELECT ... FOR UPDATE SKIP LOCKED` on the
   `tasks` table. **No pgmq.**
3. **DB operator:** CloudNativePG (CNPG) in-cluster. `Cluster` CR, 1 replica,
   2Gi PVC. Flip to external RDS/Neon later (out of scope for this plan).
4. **Schema migrations:** Alembic, packaged as its own image
   (`ghcr.io/hamza-rx12/apa-migrate`), run as a Helm `pre-upgrade` Job.
5. **Secret:** use CNPG-generated `<cluster>-app` secret (key: `uri`) — no
   manual secret authoring. Mount via `envFrom`.
6. **Shared DB helper:** copy-paste a small `db.py` into each service under
   `app/db.py`. No monorepo tooling. Four copies ≈ 80 lines each.
7. **A2A task propagation:** orchestrator sends `context_id = task.id`. Agent
   executors extract it and stash in a `contextvars.ContextVar` so MCP tools
   can see the active task id.
8. **Near-realtime dequeue:** use `LISTEN tasks_new` + `NOTIFY` on INSERT.
   Fall back to 2s poll when LISTEN connection drops.
9. **Reaper:** Kubernetes `CronJob`, every 60s, flips `running` rows with
   `started_at < now() - 15 min` back to `queued` (or `dead` if attempts
   maxed).
10. **RabbitMQ removal:** hard cut. No dual-write period, no feature flag.
    We delete RabbitMQ in the same change set.

---

## Current-state reference (what's being replaced)

| File | What it does today | What it becomes |
|---|---|---|
| `services/listener/app/__main__.py` | IMAP IDLE + /alerts webhook → `_publish()` to RabbitMQ via shared `_channel` + `_rmq_lock` | IMAP IDLE + /alerts webhook → `tasks.enqueue()` INSERT |
| `services/listener/app/config.py` | Has `RABBITMQ_URL`, `RABBITMQ_QUEUE` | Replace with `DATABASE_URL` |
| `services/listener/requirements.txt` | Has `pika` | Drop `pika`, add `asyncpg` |
| `services/orchestrator/app/__main__.py` | `pika.BlockingConnection` consumer + `anyio.run(_process_task, ...)` per message | Async main: pool + LISTEN/NOTIFY loop + `tasks.dequeue()` + agent call + `tasks.complete()`/`fail()` |
| `services/orchestrator/app/configs/environment_vars/rabbitmq_settings.py` | `RABBITMQ_*` dataclass | DELETE, replace with `database_settings.py` |
| `services/orchestrator/app/config.py` | Exposes `get_rabbitmq_config()` | Expose `get_database_config()` instead |
| `services/orchestrator/requirements.txt` | Has `pika` | Drop `pika`, add `asyncpg` |
| `services/{browser-agent,monitor-agent}/requirements.txt` | No DB client | Add `asyncpg` |
| `services/{browser-agent,monitor-agent}/app/a2a_core/agent_executor.py` | Does not extract `context_id` into contextvar | Sets contextvar `active_task_id` on each incoming message |
| `k8s/infra/rabbitmq/` | `RabbitmqCluster` CR | DELETE |
| `k8s/argocd/apps/rabbitmq.yaml` | ArgoCD app | DELETE |
| `k8s/argocd/apps/cnpg-operator.yaml` | — | NEW |
| `k8s/argocd/apps/postgres.yaml` | — | NEW |
| `k8s/infra/cnpg/` | — | NEW (Cluster CR) |
| `k8s/charts/apa/values.yaml` | `RABBITMQ_URL` env per service | Replace with `DATABASE_URL` from CNPG secret; add `migrate:` and `reaper:` blocks |
| `k8s/charts/apa/templates/migrate-job.yaml` | — | NEW (Helm `pre-upgrade` hook) |
| `k8s/charts/apa/templates/reaper-cronjob.yaml` | — | NEW |

---

## Implementation steps

Order matters. Each step is a standalone commit. Do **not** skip ahead — the
transition relies on Postgres being up before the consumers switch.

### Step 0 — Prep & layout

- [x] Read this whole file before starting. If anything is ambiguous, stop
      and ask the user; do not guess.
- [x] Confirm you are on branch `master` with a clean tree (aside from this
      plan file and `docs/TODO.md`).
- [x] Create working directories:
      - `services/migrate/`
      - `services/migrate/alembic/versions/`
      - `k8s/infra/cnpg/`

### Step 1 — CNPG operator + cluster (infra only)

- [x] Write `k8s/argocd/apps/cnpg-operator.yaml`:
      - ArgoCD Application pointing at the upstream CNPG Helm chart.
      - Repo: `https://cloudnative-pg.github.io/charts`
      - Chart: `cloudnative-pg`, version `0.23.x` (pick latest minor at
        install time).
      - Target namespace: `cnpg-system`.
      - `syncPolicy.automated: {prune: true, selfHeal: true}` and
        `CreateNamespace=true`, `ServerSideApply=true` (CRDs are large).
- [x] Write `k8s/infra/cnpg/cluster.yaml`:
      ```yaml
      apiVersion: postgresql.cnpg.io/v1
      kind: Cluster
      metadata:
        name: apa-pg
        namespace: apa
      spec:
        instances: 1
        storage:
          size: 2Gi
        bootstrap:
          initdb:
            database: apa
            owner: apa
        # no backups configured yet — see TODO
      ```
- [x] Write `k8s/infra/cnpg/kustomization.yaml`:
      ```yaml
      apiVersion: kustomize.config.k8s.io/v1beta1
      kind: Kustomization
      resources:
        - cluster.yaml
      ```
- [x] Write `k8s/argocd/apps/postgres.yaml` (Application pointing at
      `k8s/infra/cnpg`, namespace `apa`, `ServerSideApply=true`).
- [x] **Commit:** `feat(db): deploy CNPG operator + apa-pg cluster`.
- [x] **Verification (user runs):** `make up && make argocd-up`, then
      `kubectl -n apa get cluster apa-pg` shows `Cluster in healthy state`.
      `kubectl -n apa get secret apa-pg-app -o yaml` has `uri` key.
- [x] Mark Step 1 `[x]` in this file and commit `docs(plan): step 1 done`.

### Step 2 — Schema + Alembic migration image

- [x] Create `services/migrate/alembic.ini` (standard template, `script_location
      = alembic`, `sqlalchemy.url` from env).
- [x] Create `services/migrate/alembic/env.py`:
      - Read `DATABASE_URL` from env.
      - Synchronous engine (Alembic expects sync). Use `psycopg[binary]` here
        — **only** for migrations; runtime stays on asyncpg.
      - No autogenerate needed; migrations are handwritten.
- [x] Create `services/migrate/alembic/versions/0001_tasks.py`:
      - `revision = "0001"`, `down_revision = None`.
      - `upgrade()`:
        ```sql
        CREATE EXTENSION IF NOT EXISTS pgcrypto;

        CREATE TABLE tasks (
          id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          source            text NOT NULL,                       -- 'email' | 'alert'
          subject           text,
          payload           jsonb NOT NULL DEFAULT '{}'::jsonb,
          status            text NOT NULL DEFAULT 'queued'
                            CHECK (status IN ('queued','running','succeeded','failed','dead')),
          agent             text,                                -- which sub-agent handled it last
          claude_session_id text,
          attempts          int  NOT NULL DEFAULT 0,
          max_attempts      int  NOT NULL DEFAULT 3,
          scheduled_for     timestamptz,
          last_error        text,
          result_text       text,
          created_at        timestamptz NOT NULL DEFAULT now(),
          started_at        timestamptz,
          finished_at       timestamptz
        );

        CREATE INDEX tasks_ready
          ON tasks (scheduled_for NULLS FIRST, created_at)
          WHERE status = 'queued';

        CREATE INDEX tasks_recent ON tasks (created_at DESC);

        -- NOTIFY on new queued rows
        CREATE FUNCTION tasks_notify() RETURNS trigger AS $$
        BEGIN
          IF NEW.status = 'queued' THEN
            PERFORM pg_notify('tasks_new', NEW.id::text);
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER tasks_notify_ins
          AFTER INSERT ON tasks
          FOR EACH ROW EXECUTE FUNCTION tasks_notify();

        CREATE TRIGGER tasks_notify_upd
          AFTER UPDATE OF status ON tasks
          FOR EACH ROW
          WHEN (NEW.status = 'queued' AND OLD.status IS DISTINCT FROM 'queued')
          EXECUTE FUNCTION tasks_notify();
        ```
      - `downgrade()`: `DROP TABLE tasks CASCADE; DROP FUNCTION tasks_notify();`.
- [x] Create `services/migrate/requirements.txt`:
      ```
      alembic>=1.13
      psycopg[binary]>=3.2
      sqlalchemy>=2.0
      ```
- [x] Create `services/migrate/Dockerfile`:
      - Base `python:3.12-slim`.
      - Install requirements.
      - Entry point: `alembic upgrade head`.
- [x] Create `services/migrate/entrypoint.sh` **only if needed** (otherwise
      just `CMD ["alembic", "upgrade", "head"]`).
- [x] Extend `.github/workflows/build-push.yml` to build+push `apa-migrate`
      image (same pattern as other services).
- [x] Write `k8s/charts/apa/templates/migrate-job.yaml`:
      - `kind: Job` with `annotations: {"helm.sh/hook": "pre-upgrade,pre-install", "helm.sh/hook-delete-policy": "before-hook-creation"}`.
      - Single container running the migrate image.
      - `envFrom: [{secretRef: {name: apa-pg-app}}]` → gives `uri`, `host`,
        `dbname`, `user`, `password`. Map `DATABASE_URL` from `uri` via `env:`.
- [x] **Commit:** `feat(db): add tasks schema + alembic migrate job`.
- [x] **Verification (user runs):** after ArgoCD sync, `kubectl -n apa get
      job` shows migrate Job succeeded; `kubectl -n apa exec apa-pg-1 -- psql
      -U apa -d apa -c '\d tasks'` lists the columns.
- [x] Mark Step 2 `[x]`, commit.

### Step 3 — Shared DB helper per service

For **each** of `services/listener`, `services/orchestrator`,
`services/browser-agent`, `services/monitor-agent`:

- [x] Create `app/db.py` with this content (copy verbatim, adjust only if
      asyncpg API changes):

      ```python
      """Thin asyncpg helpers for the tasks table. Copy-pasted across services."""
      from __future__ import annotations

      import json
      import os
      import uuid
      from typing import Any, Optional

      import asyncpg

      _pool: Optional[asyncpg.Pool] = None


      async def get_pool() -> asyncpg.Pool:
          global _pool
          if _pool is None:
              dsn = os.environ["DATABASE_URL"]
              _pool = await asyncpg.create_pool(
                  dsn,
                  min_size=1,
                  max_size=5,
                  command_timeout=30,
              )
          return _pool


      async def close_pool() -> None:
          global _pool
          if _pool is not None:
              await _pool.close()
              _pool = None


      async def enqueue(
          *,
          source: str,
          subject: Optional[str],
          payload: dict[str, Any],
      ) -> uuid.UUID:
          pool = await get_pool()
          async with pool.acquire() as conn:
              row = await conn.fetchrow(
                  """
                  INSERT INTO tasks (source, subject, payload)
                  VALUES ($1, $2, $3::jsonb)
                  RETURNING id
                  """,
                  source,
                  subject,
                  json.dumps(payload),
              )
              return row["id"]


      async def dequeue() -> Optional[dict[str, Any]]:
          """Atomically claim one ready task. Returns None if queue is empty."""
          pool = await get_pool()
          async with pool.acquire() as conn:
              row = await conn.fetchrow(
                  """
                  UPDATE tasks
                  SET status = 'running',
                      started_at = now(),
                      attempts = attempts + 1
                  WHERE id = (
                      SELECT id FROM tasks
                      WHERE status = 'queued'
                        AND (scheduled_for IS NULL OR scheduled_for <= now())
                      ORDER BY created_at
                      LIMIT 1
                      FOR UPDATE SKIP LOCKED
                  )
                  RETURNING *
                  """
              )
              return dict(row) if row else None


      async def complete(task_id: uuid.UUID, result_text: str, session_id: Optional[str]) -> None:
          pool = await get_pool()
          async with pool.acquire() as conn:
              await conn.execute(
                  """
                  UPDATE tasks
                  SET status = 'succeeded',
                      finished_at = now(),
                      result_text = $2,
                      claude_session_id = COALESCE($3, claude_session_id)
                  WHERE id = $1
                  """,
                  task_id, result_text, session_id,
              )


      async def fail(task_id: uuid.UUID, error: str) -> None:
          """On failure, either reschedule with backoff or mark dead."""
          pool = await get_pool()
          async with pool.acquire() as conn:
              await conn.execute(
                  """
                  UPDATE tasks
                  SET status = CASE
                                 WHEN attempts >= max_attempts THEN 'dead'
                                 ELSE 'queued'
                               END,
                      scheduled_for = CASE
                                        WHEN attempts >= max_attempts THEN NULL
                                        ELSE now() + (interval '1 minute' * power(2, attempts))
                                      END,
                      last_error = $2,
                      finished_at = CASE
                                      WHEN attempts >= max_attempts THEN now()
                                      ELSE finished_at
                                    END
                  WHERE id = $1
                  """,
                  task_id, error,
              )


      async def get_task(task_id: uuid.UUID) -> Optional[dict[str, Any]]:
          pool = await get_pool()
          async with pool.acquire() as conn:
              row = await conn.fetchrow("SELECT * FROM tasks WHERE id = $1", task_id)
              return dict(row) if row else None


      async def append_progress(task_id: uuid.UUID, note: str) -> None:
          """Append a timestamped note to payload.progress[]."""
          pool = await get_pool()
          async with pool.acquire() as conn:
              await conn.execute(
                  """
                  UPDATE tasks
                  SET payload = jsonb_set(
                      COALESCE(payload, '{}'::jsonb),
                      '{progress}',
                      COALESCE(payload->'progress', '[]'::jsonb) ||
                        jsonb_build_array(jsonb_build_object(
                          'ts', to_char(now(), 'YYYY-MM-DD"T"HH24:MI:SSZ'),
                          'note', $2::text
                        ))
                  )
                  WHERE id = $1
                  """,
                  task_id, note,
              )


      async def set_artifact(task_id: uuid.UUID, key: str, value: Any) -> None:
          pool = await get_pool()
          async with pool.acquire() as conn:
              await conn.execute(
                  """
                  UPDATE tasks
                  SET payload = jsonb_set(
                      COALESCE(payload, '{}'::jsonb),
                      ARRAY['artifacts', $2],
                      $3::jsonb,
                      true
                  )
                  WHERE id = $1
                  """,
                  task_id, key, json.dumps(value),
              )
      ```

- [x] Add `asyncpg>=0.29` to each service's `requirements.txt` if missing.
      Remove `pika` from listener and orchestrator.
- [x] **Commit:** `feat(db): add shared asyncpg helpers`.
- [x] Mark Step 3 `[x]`, commit.

### Step 4 — Listener: Postgres INSERT replaces RabbitMQ publish

- [x] Edit `services/listener/app/config.py`:
      - Remove `RABBITMQ_URL`, `RABBITMQ_QUEUE`.
      - Add `DATABASE_URL = os.environ["DATABASE_URL"]` (fail fast if unset
        in prod — the listener is pointless without a DB).
      - Keep `ALERTS_HTTP_PORT`.
- [x] Edit `services/listener/app/__main__.py`:
      - Remove `pika` import, `_connect_rabbitmq`, `_heartbeat_loop`,
        `_publish`, `_channel`, `_rmq_lock`, `_BACKOFF_*` constants for
        RabbitMQ retries.
      - Keep the `_JSONFormatter` block and logger setup as-is.
      - `/alerts` webhook handler becomes (pseudo):
        ```python
        from app.db import enqueue
        ...
        for alert in alerts:
            labels = alert.get("labels", {})
            if labels.get("service") == "monitor-agent":
                continue  # loop guard
            await enqueue(
                source="alert",
                subject=labels.get("alertname"),
                payload={"alert": alert, "fingerprint": alert.get("fingerprint")},
            )
            published += 1
        ```
      - IMAP loop becomes sync-on-outside, async-on-DB: easiest path is to
        wrap each publish in `asyncio.run(enqueue(...))` (there's no ongoing
        event loop in that thread), **OR** refactor the IMAP loop to run
        inside `asyncio` as a thread-run task. Prefer: keep IMAP on its own
        thread (blocking IDLE), use `asyncio.run(enqueue(...))` per message.
        Note: this creates/destroys a loop per message — fine at email rate.
      - Alerts HTTP server is already Starlette/uvicorn — already async, just
        `await enqueue(...)` in the handler.
      - The shared-channel dance (`_channel`, `_rmq_lock`) goes away entirely
        — asyncpg has its own pool.
- [x] Ensure `app.db` is importable (add it in Step 3). Verify `import app.db`
      works locally.
- [x] Remove `pika` from `services/listener/requirements.txt`; keep
      `imapclient`, add `asyncpg`.
- [x] Update `k8s/charts/apa/values.yaml` listener block: remove
      `RABBITMQ_URL`, add nothing (DATABASE_URL comes via the shared secret,
      see Step 7).
- [x] **Commit:** `feat(listener): INSERT tasks into Postgres instead of RabbitMQ`.
- [x] Mark Step 4 `[x]`, commit.

### Step 5 — Orchestrator: LISTEN/NOTIFY dequeue loop

- [x] Delete `services/orchestrator/app/configs/environment_vars/rabbitmq_settings.py`.
- [x] Create `services/orchestrator/app/configs/environment_vars/database_settings.py`:
      ```python
      from __future__ import annotations
      import os
      from dataclasses import dataclass

      @dataclass(frozen=True)
      class DatabaseSettings:
          URL: str
          POLL_INTERVAL_S: float  # fallback poll when LISTEN not triggering

      def load_database_settings() -> DatabaseSettings:
          return DatabaseSettings(
              URL=os.environ["DATABASE_URL"],
              POLL_INTERVAL_S=float(os.getenv("DB_POLL_INTERVAL_S", "2")),
          )

      database_settings: DatabaseSettings = load_database_settings()
      ```
- [x] Edit `services/orchestrator/app/configs/environment_vars/__init__.py`
      to export the new module in place of rabbitmq.
- [x] Edit `services/orchestrator/app/config.py`:
      - Remove `from ... import rabbitmq_settings` and `get_rabbitmq_config`.
      - Add `from ... import database_settings` and `get_database_config()`.
- [x] Rewrite `services/orchestrator/app/__main__.py`:
      - Fully async with `asyncio.run(main())`.
      - Sketch:
        ```python
        import asyncio, json, logging, uuid
        import asyncpg
        from app.agent.claude_agent import ClaudeAIAgent
        from app.common.utils import get_logger
        from app.config import AppConfig
        from app.db import dequeue, complete, fail, get_pool

        log = get_logger(__name__)

        async def _process(agent, task):
            task_id = task["id"]
            prompt = _format_task_prompt(task)
            try:
                result = await agent.invoke(prompt, context_id=str(task_id))
                await complete(task_id, result.get("text", ""),
                               result.get("metadata", {}).get("session_id"))
            except Exception as e:
                log.exception("task failed")
                await fail(task_id, str(e)[:2000])

        async def _drain(agent):
            while True:
                task = await dequeue()
                if task is None:
                    return
                await _process(agent, task)

        async def _run(agent):
            db_cfg = AppConfig.get_database_config()
            pool = await get_pool()
            # Dedicated connection for LISTEN (asyncpg pool conns can't
            # hold LISTEN across releases).
            listen_conn = await asyncpg.connect(db_cfg.URL)
            new_event = asyncio.Event()

            def _on_notify(_conn, _pid, _chan, _payload):
                new_event.set()

            await listen_conn.add_listener("tasks_new", _on_notify)
            try:
                # Drain anything already queued at startup.
                await _drain(agent)
                while True:
                    try:
                        await asyncio.wait_for(new_event.wait(), timeout=db_cfg.POLL_INTERVAL_S)
                    except asyncio.TimeoutError:
                        pass  # poll fallback
                    new_event.clear()
                    await _drain(agent)
            finally:
                await listen_conn.remove_listener("tasks_new", _on_notify)
                await listen_conn.close()

        async def main():
            agent = ClaudeAIAgent()
            await _run(agent)

        if __name__ == "__main__":
            asyncio.run(main())
        ```
      - Remove pika, `anyio`, the `_run_consumer` function, and the
        `callback` wrapper that wraps `anyio.run()`.
- [x] Remove `pika` and `anyio` from `services/orchestrator/requirements.txt`;
      add `asyncpg>=0.29`. (`anyio` is likely transitively needed by httpx —
      leave it if so; otherwise drop.)
- [x] Update `k8s/charts/apa/values.yaml` orchestrator block: remove
      `RABBITMQ_URL`.
- [x] **Commit:** `feat(orchestrator): Postgres LISTEN/NOTIFY dequeue loop`.
- [x] Mark Step 5 `[x]`, commit.

### Step 6 — A2A task-id propagation + agent MCP tools

- [x] Create `services/browser-agent/app/common/task_context.py` (and identical
      in monitor-agent):
      ```python
      """ContextVar carrying the active task id, set by the A2A executor."""
      from __future__ import annotations
      import uuid
      from contextvars import ContextVar
      from typing import Optional

      active_task_id: ContextVar[Optional[uuid.UUID]] = ContextVar(
          "active_task_id", default=None
      )
      ```
- [x] Edit `services/browser-agent/app/a2a_core/agent_executor.py`
      (and monitor-agent equivalent):
      - On each incoming A2A message, read the `context_id` (string UUID),
        parse to `uuid.UUID`, and set `active_task_id` in the contextvar
        **within the same task** (use `active_task_id.set(...)` at the top
        of the per-message coroutine).
      - If parsing fails (non-UUID context_id), leave as None — tools will
        return "no active task" to the agent.
- [x] Create `services/browser-agent/app/tools/tool_task_state.py` (copy in
      monitor-agent too, identical):
      ```python
      """MCP tools for reading and updating the current task row."""
      from __future__ import annotations
      from typing import Any
      from claude_agent_sdk import tool
      from app.common.task_context import active_task_id
      from app.common.utils import get_logger
      from app.db import get_task, append_progress, set_artifact

      log = get_logger(__name__)


      def _err(msg: str) -> dict[str, Any]:
          return {"content": [{"type": "text", "text": msg}], "is_error": True}


      @tool(
          name="task_get",
          description="Fetch the current task row (status, payload, attempts).",
          input_schema={"type": "object", "properties": {}, "required": []},
      )
      async def task_get_mcp(_args: dict[str, Any]) -> dict[str, Any]:
          tid = active_task_id.get()
          if tid is None:
              return _err("No active task in this context.")
          row = await get_task(tid)
          if row is None:
              return _err(f"Task {tid} not found.")
          return {"content": [{"type": "text", "text": str(row)}]}


      @tool(
          name="task_append_note",
          description="Append a progress note to the current task.",
          input_schema={
              "type": "object",
              "properties": {"note": {"type": "string"}},
              "required": ["note"],
          },
      )
      async def task_append_note_mcp(args: dict[str, Any]) -> dict[str, Any]:
          tid = active_task_id.get()
          if tid is None:
              return _err("No active task in this context.")
          await append_progress(tid, args["note"])
          return {"content": [{"type": "text", "text": "ok"}]}


      @tool(
          name="task_set_artifact",
          description="Write a named artifact into payload.artifacts.",
          input_schema={
              "type": "object",
              "properties": {
                  "key": {"type": "string"},
                  "value": {}  # any JSON-serialisable
              },
              "required": ["key", "value"],
          },
      )
      async def task_set_artifact_mcp(args: dict[str, Any]) -> dict[str, Any]:
          tid = active_task_id.get()
          if tid is None:
              return _err("No active task in this context.")
          await set_artifact(tid, args["key"], args["value"])
          return {"content": [{"type": "text", "text": "ok"}]}


      __all__ = [
          "task_get_mcp",
          "task_append_note_mcp",
          "task_set_artifact_mcp",
      ]
      ```
- [x] No change needed to `tools/__init__.py` — auto-discovery picks the new
      module up because the filename starts with `tool_` and handlers end in
      `_mcp`.
- [x] Verify agent config still routes these through `create_local_mcp_server`
      and that `get_allowed_tools()` returns them.
- [x] **Commit:** `feat(agents): MCP tools for task state + context propagation`.
- [x] Mark Step 6 `[x]`, commit.

### Step 7 — Wire DATABASE_URL into Helm chart

- [x] Edit `k8s/charts/apa/values.yaml`:
      - Remove `RABBITMQ_URL` from listener and orchestrator env.
      - Do **not** add `DATABASE_URL` literally. Instead:
        - Add a top-level:
          ```yaml
          postgres:
            secretName: apa-pg-app   # CNPG auto-generated
          migrate:
            image: ghcr.io/hamza-rx12/apa-migrate:latest
          reaper:
            schedule: "*/1 * * * *"  # every minute
            stuckAfter: "15 minutes"
          ```
- [x] Edit `k8s/charts/apa/templates/deployment.yaml`:
      - Add `envFrom: [{secretRef: {name: {{ .Values.postgres.secretName }}}}]`
        to each container alongside the existing `apa-secrets` ref.
      - The CNPG secret exposes `uri` — map it to `DATABASE_URL` via an
        explicit `env` entry:
        ```yaml
        env:
          - name: DATABASE_URL
            valueFrom:
              secretKeyRef:
                name: {{ $.Values.postgres.secretName }}
                key: uri
          # existing per-service static envs...
        ```
- [x] Write `k8s/charts/apa/templates/migrate-job.yaml` (referenced in Step 2,
      finalize here if not already done):
      - `helm.sh/hook: pre-upgrade,pre-install`
      - `helm.sh/hook-delete-policy: before-hook-creation`
      - Container image `{{ .Values.migrate.image }}`.
      - `DATABASE_URL` env from `{{ .Values.postgres.secretName }}.uri`.
- [x] **Commit:** `feat(chart): inject DATABASE_URL into services, add migrate job`.
- [x] Mark Step 7 `[x]`, commit.

### Step 8 — Reaper CronJob

- [x] Write `k8s/charts/apa/templates/reaper-cronjob.yaml`:
      - `apiVersion: batch/v1`, `kind: CronJob`.
      - `schedule: {{ .Values.reaper.schedule }}`.
      - Container uses the same `apa-migrate` image (has `psycopg`).
      - Command: `python -c "..."` or a small `services/migrate/reap.py`
        script that runs:
        ```sql
        UPDATE tasks
        SET status = CASE
                       WHEN attempts >= max_attempts THEN 'dead'
                       ELSE 'queued'
                     END,
            last_error = COALESCE(last_error, '') || ' [reaped: stuck > {{ .Values.reaper.stuckAfter }}]',
            started_at = CASE
                           WHEN attempts >= max_attempts THEN started_at
                           ELSE NULL
                         END
        WHERE status = 'running'
          AND started_at < now() - interval '{{ .Values.reaper.stuckAfter }}';
        ```
      - Prefer a dedicated Python script over inline `-c` for legibility:
        create `services/migrate/reap.py`.
- [x] **Commit:** `feat(chart): add reaper CronJob for stuck tasks`.
- [x] Mark Step 8 `[x]`, commit.

### Step 9 — Delete RabbitMQ

- [x] Delete `k8s/argocd/apps/rabbitmq.yaml`.
- [x] Delete `k8s/infra/rabbitmq/` (entire directory).
- [x] Grep the whole repo for `rabbitmq`, `RABBITMQ`, `pika`, `amqp` —
      resolve any remaining hits (comments in README, env examples, etc.).
- [x] Update `README.md` pipeline diagram: replace `RabbitMQ` with
      `Postgres (tasks)`.
- [x] Update `docs/target-architecture.md` if it references RabbitMQ.
- [x] **Commit:** `chore(infra): remove RabbitMQ, superseded by Postgres`.
- [x] Mark Step 9 `[x]`, commit.

### Step 10 — Observability: Grafana tasks panel

- [x] Add Postgres datasource to `k8s/charts/apa/templates/grafana-datasources.yaml`
      (datasource type: `grafana-postgresql-datasource`, uid `postgres`,
      pointing at the CNPG read-write service).
- [x] Extend `k8s/charts/apa/dashboards/apa-logs.json` (or create a new
      dashboard `apa-tasks.json`) with:
      - A table panel showing recent tasks (`SELECT id, source, subject,
        status, attempts, created_at, finished_at FROM tasks ORDER BY
        created_at DESC LIMIT 100`).
      - A stat panel per status (`SELECT status, count(*) FROM tasks GROUP BY
        status`).
- [x] Register the new dashboard in `grafana-dashboards.yaml` ConfigMap.
- [x] **Commit:** `feat(observability): Grafana tasks dashboard`.
- [x] Mark Step 10 `[x]`, commit.

### Step 11 — Final cleanup & verification

- [x] Run each service's container build locally (or trigger CI) and confirm
      there are no pip resolver errors after removing `pika`.
- [x] `make reset && make up && make argocd-up` end-to-end:
      - CNPG operator ready.
      - `apa-pg` cluster healthy.
      - `apa-pg-app` secret exists.
      - migrate Job ran successfully.
      - All four service pods running, no CrashLoopBackOff.
      - `kubectl -n apa exec apa-pg-1 -- psql -U apa -d apa -c 'SELECT
        count(*) FROM tasks;'` returns 0.
      - Trigger a test alert (or send a real email) → row appears in `tasks`
        → orchestrator picks it up → status moves `queued → running →
        succeeded`.
- [x] Update `docs/TODO.md`: remove this migration from wherever it was
      referenced; add "CNPG → RDS/Neon at EKS time" as a new deferred item.
- [x] **Commit:** `docs: close postgres migration; add CNPG→RDS deferral`.
- [x] Mark Step 11 `[x]`.

---

## Pitfalls to watch for

- **asyncpg + LISTEN:** pool connections can't hold LISTEN subscriptions
  safely. Use a dedicated `asyncpg.connect()` for the listener conn. The
  sketch in Step 5 does this correctly — do not "simplify" by reusing the
  pool.
- **Session ID column:** `claude_session_id` is for resume semantics later.
  For now, just record it on completion; don't wire fork/resume yet.
- **CNPG secret key:** CNPG names it `uri`, not `url`. Double-check before
  writing the secretKeyRef.
- **Migrate Job image tag:** don't use `:latest` in prod — pin by SHA once
  the first build succeeds.
- **Backoff math:** `power(2, attempts)` where attempts is post-increment
  after dequeue. First retry is 2 min, second 4 min, third 8 min → dead at
  attempt 3.
- **`anyio.run`** in the old orchestrator was a workaround to call async
  code from pika's sync callback. The new orchestrator is fully async; don't
  carry that pattern forward.
- **Alertmanager loop-guard:** the check `labels.get("service") ==
  "monitor-agent"` must survive the rewrite. Keep it in the new
  `/alerts` handler.
- **IMAP loop threading:** `get_connection()` is sync/blocking (IMAP IDLE).
  Don't try to make it async. Keep it on its own thread and use
  `asyncio.run(enqueue(...))` per message — works because there's no other
  loop in that thread.

## Questions to raise (don't guess, ask)

- If the CNPG chart version resolves differently than `0.23.x`, confirm with
  the user before bumping.
- If the Alembic env template produces >100 lines of boilerplate, ask whether
  to keep or trim — the intent is "minimal, readable".
- If asyncpg connection errors bubble up at listener startup (DB not ready),
  decide with the user: should listener crash-loop until DB is up, or have
  its own retry loop? Default: crash-loop (k8s handles it).

## Out of scope

- External-secrets operator (still deferred, see `docs/TODO.md` #5).
- RDS/Neon migration (deferred; single-line config swap when needed).
- Backups for CNPG (configure `.spec.backup` when moving past local dev).
- Task priorities, separate queues, fan-out — single queue with `source`
  field is enough for now.
