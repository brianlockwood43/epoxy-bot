from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS people (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            origin TEXT,
            status TEXT DEFAULT 'active',
            merged_into_person_id INTEGER
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS person_identifiers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_id INTEGER NOT NULL,
            platform TEXT NOT NULL,
            external_id TEXT NOT NULL,
            label TEXT,
            strength TEXT DEFAULT 'primary',
            created_at TEXT,
            last_seen_at TEXT,
            revoked_at TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_person_identifiers_platform_external_active
        ON person_identifiers(platform, external_id)
        WHERE revoked_at IS NULL
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_person_identifiers_person_platform_active
        ON person_identifiers(person_id, platform, revoked_at)
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_person_identifiers_person_id ON person_identifiers(person_id)")
    conn.commit()
