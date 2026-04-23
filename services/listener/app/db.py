"""Thin asyncpg helpers for the tasks table."""
from __future__ import annotations

import json
import os
import uuid
from typing import Any, Optional

import asyncio

import asyncpg

# One pool per event loop so the IMAP thread and uvicorn never share a pool.
_pools: dict[int, asyncpg.Pool] = {}


async def get_pool() -> asyncpg.Pool:
    loop = asyncio.get_running_loop()
    key = id(loop)
    pool = _pools.get(key)
    if pool is None:
        pool = await asyncpg.create_pool(
            os.environ["DATABASE_URL"],
            min_size=1,
            max_size=5,
            command_timeout=30,
            init=_init_conn,
        )
        _pools[key] = pool
    return pool


async def _init_conn(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
        format="text",
    )


async def close_pool() -> None:
    loop = asyncio.get_running_loop()
    key = id(loop)
    pool = _pools.pop(key, None)
    if pool is not None:
        await pool.close()


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
            payload,
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


async def complete(
    task_id: uuid.UUID, result_text: str, session_id: Optional[str]
) -> None:
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
            task_id,
            result_text,
            session_id,
        )


async def fail(task_id: uuid.UUID, error: str) -> None:
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
            task_id,
            error,
        )


async def get_task(task_id: uuid.UUID) -> Optional[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM tasks WHERE id = $1", task_id)
        return dict(row) if row else None


async def append_progress(task_id: uuid.UUID, note: str) -> None:
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
            task_id,
            note,
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
            task_id,
            key,
            value,
        )
