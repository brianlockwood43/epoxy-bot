from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (table,))
    return cur.fetchone() is not None


def upgrade(conn: sqlite3.Connection) -> None:
    if not _has_table(conn, "memory_summaries"):
        return

    cur = conn.cursor()
    now_iso = _utc_now_iso()

    cur.execute(
        """
        UPDATE memory_summaries
        SET scope = 'global'
        WHERE scope IS NULL OR TRIM(scope) = ''
        """
    )
    cur.execute(
        """
        UPDATE memory_summaries
        SET summary_type = 'topic_gist'
        WHERE summary_type IS NULL OR TRIM(summary_type) = ''
        """
    )
    cur.execute(
        """
        UPDATE memory_summaries
        SET lifecycle = 'active'
        WHERE lifecycle IS NULL OR TRIM(lifecycle) = ''
        """
    )

    # Keep the newest active row per (topic_id, scope, summary_type), preserve old rows as deprecated.
    cur.execute(
        """
        UPDATE memory_summaries
        SET lifecycle = 'deprecated',
            updated_at_utc = ?
        WHERE id IN (
            SELECT older.id
            FROM memory_summaries AS older
            WHERE COALESCE(older.lifecycle, 'active') = 'active'
              AND older.topic_id IS NOT NULL
              AND TRIM(older.topic_id) != ''
              AND EXISTS (
                    SELECT 1
                    FROM memory_summaries AS newer
                    WHERE COALESCE(newer.lifecycle, 'active') = 'active'
                      AND newer.topic_id = older.topic_id
                      AND COALESCE(newer.scope, 'global') = COALESCE(older.scope, 'global')
                      AND COALESCE(newer.summary_type, 'topic_gist') = COALESCE(older.summary_type, 'topic_gist')
                      AND (
                            COALESCE(newer.updated_at_utc, '') > COALESCE(older.updated_at_utc, '')
                            OR (
                                COALESCE(newer.updated_at_utc, '') = COALESCE(older.updated_at_utc, '')
                                AND newer.id > older.id
                            )
                          )
              )
        )
        """,
        (now_iso,),
    )

    cur.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_memory_summaries_partition_active
        ON memory_summaries (
            topic_id,
            COALESCE(scope, 'global'),
            COALESCE(summary_type, 'topic_gist')
        )
        WHERE COALESCE(lifecycle, 'active') = 'active'
          AND topic_id IS NOT NULL
          AND TRIM(topic_id) != ''
        """
    )

    conn.commit()
