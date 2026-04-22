"""Reaper script: flip stuck 'running' tasks back to 'queued' or 'dead'.

Run as a CronJob every minute. Considers tasks stuck if started_at is older
than REAPER_STUCK_AFTER_MINUTES (default 15).
"""
from __future__ import annotations

import os
import psycopg

STUCK_AFTER = int(os.getenv("REAPER_STUCK_AFTER_MINUTES", "15"))


def main() -> None:
    url = os.environ["DATABASE_URL"]
    with psycopg.connect(url) as conn:
        result = conn.execute(
            """
            UPDATE tasks
            SET status = CASE
                           WHEN attempts >= max_attempts THEN 'dead'
                           ELSE 'queued'
                         END,
                last_error = COALESCE(last_error || ' ', '') ||
                             '[reaped: stuck > %(stuck)s min]',
                started_at = CASE
                               WHEN attempts >= max_attempts THEN started_at
                               ELSE NULL
                             END,
                finished_at = CASE
                                WHEN attempts >= max_attempts THEN now()
                                ELSE finished_at
                              END
            WHERE status = 'running'
              AND started_at < now() - (%(stuck)s || ' minutes')::interval
            RETURNING id
            """,
            {"stuck": STUCK_AFTER},
        )
        rows = result.fetchall()
        conn.commit()

    if rows:
        print(f"reaped {len(rows)} stuck task(s): {[str(r[0]) for r in rows]}")
    else:
        print("no stuck tasks")


if __name__ == "__main__":
    main()
