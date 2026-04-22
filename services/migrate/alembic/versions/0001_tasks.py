"""create tasks table

Revision ID: 0001
Revises:
Create Date: 2026-04-22
"""
from __future__ import annotations

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE EXTENSION IF NOT EXISTS pgcrypto
    """)

    op.execute("""
        CREATE TABLE tasks (
          id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          source            text NOT NULL,
          subject           text,
          payload           jsonb NOT NULL DEFAULT '{}'::jsonb,
          status            text NOT NULL DEFAULT 'queued'
                            CHECK (status IN ('queued','running','succeeded','failed','dead')),
          agent             text,
          claude_session_id text,
          attempts          int  NOT NULL DEFAULT 0,
          max_attempts      int  NOT NULL DEFAULT 3,
          scheduled_for     timestamptz,
          last_error        text,
          result_text       text,
          created_at        timestamptz NOT NULL DEFAULT now(),
          started_at        timestamptz,
          finished_at       timestamptz
        )
    """)

    op.execute("""
        CREATE INDEX tasks_ready
          ON tasks (scheduled_for NULLS FIRST, created_at)
          WHERE status = 'queued'
    """)

    op.execute("""
        CREATE INDEX tasks_recent ON tasks (created_at DESC)
    """)

    op.execute("""
        CREATE FUNCTION tasks_notify() RETURNS trigger AS $$
        BEGIN
          IF NEW.status = 'queued' THEN
            PERFORM pg_notify('tasks_new', NEW.id::text);
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)

    op.execute("""
        CREATE TRIGGER tasks_notify_ins
          AFTER INSERT ON tasks
          FOR EACH ROW EXECUTE FUNCTION tasks_notify()
    """)

    op.execute("""
        CREATE TRIGGER tasks_notify_upd
          AFTER UPDATE OF status ON tasks
          FOR EACH ROW
          WHEN (NEW.status = 'queued' AND OLD.status IS DISTINCT FROM 'queued')
          EXECUTE FUNCTION tasks_notify()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS tasks_notify_upd ON tasks")
    op.execute("DROP TRIGGER IF EXISTS tasks_notify_ins ON tasks")
    op.execute("DROP FUNCTION IF EXISTS tasks_notify")
    op.execute("DROP TABLE IF EXISTS tasks")
