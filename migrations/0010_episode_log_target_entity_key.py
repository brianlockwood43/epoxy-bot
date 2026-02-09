from __future__ import annotations

import sqlite3


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    return any(str(row[1]) == column for row in cur.fetchall())


def upgrade(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    if not _has_column(conn, "episode_logs", "target_entity_key"):
        cur.execute("ALTER TABLE episode_logs ADD COLUMN target_entity_key TEXT")

    cur.execute("CREATE INDEX IF NOT EXISTS idx_episode_logs_target_entity_key ON episode_logs(target_entity_key)")
    conn.commit()

