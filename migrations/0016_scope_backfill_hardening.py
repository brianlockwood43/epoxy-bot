from __future__ import annotations

import sqlite3


def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (table,))
    return cur.fetchone() is not None


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    return any(str(row[1]) == column for row in cur.fetchall())


def upgrade(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()

    if _has_table(conn, "memory_events"):
        if not _has_column(conn, "memory_events", "scope"):
            cur.execute("ALTER TABLE memory_events ADD COLUMN scope TEXT")
        if not _has_column(conn, "memory_events", "lifecycle"):
            cur.execute("ALTER TABLE memory_events ADD COLUMN lifecycle TEXT DEFAULT 'active'")

        cur.execute(
            """
            UPDATE memory_events
            SET scope = CASE
                WHEN channel_id IS NOT NULL THEN 'channel:' || channel_id
                WHEN guild_id IS NOT NULL THEN 'guild:' || guild_id
                ELSE 'global'
            END
            WHERE scope IS NULL OR TRIM(scope) = ''
            """
        )
        cur.execute(
            """
            UPDATE memory_events
            SET lifecycle = 'active'
            WHERE lifecycle IS NULL OR TRIM(lifecycle) = ''
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_mem_events_scope ON memory_events(scope)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_mem_events_lifecycle ON memory_events(lifecycle)")

    if _has_table(conn, "memory_summaries"):
        if not _has_column(conn, "memory_summaries", "scope"):
            cur.execute("ALTER TABLE memory_summaries ADD COLUMN scope TEXT")
        if not _has_column(conn, "memory_summaries", "lifecycle"):
            cur.execute("ALTER TABLE memory_summaries ADD COLUMN lifecycle TEXT DEFAULT 'active'")

        cur.execute(
            """
            UPDATE memory_summaries
            SET scope = 'global'
            WHERE scope IS NULL
               OR TRIM(scope) = ''
               OR scope LIKE 'topic:%'
            """
        )
        cur.execute(
            """
            UPDATE memory_summaries
            SET lifecycle = 'active'
            WHERE lifecycle IS NULL OR TRIM(lifecycle) = ''
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_mem_summaries_scope ON memory_summaries(scope)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_mem_summaries_lifecycle ON memory_summaries(lifecycle)")

    conn.commit()
