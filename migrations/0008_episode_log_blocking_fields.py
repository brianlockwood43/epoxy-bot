from __future__ import annotations

import sqlite3


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    return any(str(row[1]) == column for row in cur.fetchall())


def upgrade(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    additions = [
        ("blocking_collab", "INTEGER"),
        ("critical_missing_fields_json", "TEXT"),
        ("blocking_reason", "TEXT"),
    ]
    for name, col_type in additions:
        if not _has_column(conn, "episode_logs", name):
            cur.execute(f"ALTER TABLE episode_logs ADD COLUMN {name} {col_type}")

    cur.execute("CREATE INDEX IF NOT EXISTS idx_episode_logs_blocking_collab ON episode_logs(blocking_collab)")
    conn.commit()

