from __future__ import annotations

import sqlite3


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    return any(str(row[1]) == column for row in cur.fetchall())


def upgrade(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    additions = [
        ("draft_version", "TEXT"),
        ("draft_variant_id", "TEXT"),
        ("prompt_fingerprint", "TEXT"),
    ]
    for name, col_type in additions:
        if not _has_column(conn, "episode_logs", name):
            cur.execute(f"ALTER TABLE episode_logs ADD COLUMN {name} {col_type}")

    cur.execute("CREATE INDEX IF NOT EXISTS idx_episode_logs_draft_variant_id ON episode_logs(draft_variant_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_episode_logs_prompt_fingerprint ON episode_logs(prompt_fingerprint)")
    conn.commit()
