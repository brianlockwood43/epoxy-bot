from __future__ import annotations

import sqlite3


def _safe_add_columns(cur: sqlite3.Cursor, table: str, clauses: list[str]) -> None:
    for clause in clauses:
        stmt = f"ALTER TABLE {table} ADD COLUMN {clause}"
        try:
            cur.execute(stmt)
        except sqlite3.OperationalError:
            # Existing column and/or legacy schema edge cases are tolerated.
            pass


def upgrade(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()

    _safe_add_columns(
        cur,
        "memory_events",
        [
            "topic_id TEXT",
            "topic_source TEXT DEFAULT 'manual'",
            "topic_confidence REAL",
            "logged_from_channel_id INTEGER",
            "logged_from_channel_name TEXT",
            "logged_from_message_id INTEGER",
            "source_channel_id INTEGER",
            "source_channel_name TEXT",
            "updated_at_utc TEXT",
            "last_verified_at_utc TEXT",
            "expiry_at_utc TEXT",
            "scope TEXT",
            "type TEXT DEFAULT 'event'",
            "title TEXT",
            "confidence REAL DEFAULT 0.6",
            "stability TEXT DEFAULT 'medium'",
            "lifecycle TEXT DEFAULT 'active'",
            "superseded_by INTEGER",
        ],
    )

    _safe_add_columns(
        cur,
        "memory_summaries",
        [
            "summary_type TEXT DEFAULT 'topic_gist'",
            "scope TEXT",
            "covers_event_ids_json TEXT DEFAULT '[]'",
            "confidence REAL DEFAULT 0.6",
            "stability TEXT DEFAULT 'medium'",
            "last_verified_at_utc TEXT",
            "lifecycle TEXT DEFAULT 'active'",
            "tier INTEGER DEFAULT 2",
            "generated_by_model TEXT",
            "prompt_hash TEXT",
            "job_id TEXT",
        ],
    )

    # Best-effort backfills.
    try:
        cur.execute(
            "UPDATE memory_events SET topic_id = json_extract(tags_json, '$[0]') "
            "WHERE (topic_id IS NULL OR topic_id='') AND tags_json IS NOT NULL AND tags_json != '[]'"
        )
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute(
            "UPDATE memory_events SET updated_at_utc = created_at_utc "
            "WHERE updated_at_utc IS NULL AND created_at_utc IS NOT NULL"
        )
        cur.execute(
            "UPDATE memory_events SET last_verified_at_utc = created_at_utc "
            "WHERE last_verified_at_utc IS NULL AND created_at_utc IS NOT NULL"
        )
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute(
            "UPDATE memory_summaries SET last_verified_at_utc = updated_at_utc "
            "WHERE last_verified_at_utc IS NULL AND updated_at_utc IS NOT NULL"
        )
        cur.execute(
            "UPDATE memory_summaries SET summary_type = 'topic_gist' "
            "WHERE summary_type IS NULL OR summary_type = ''"
        )
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute(
            """
            UPDATE memory_events
            SET scope = CASE
                WHEN channel_id IS NOT NULL THEN 'channel:' || channel_id
                WHEN guild_id IS NOT NULL THEN 'guild:' || guild_id
                ELSE 'global'
            END
            WHERE scope IS NULL OR scope = ''
            """
        )
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute(
            """
            UPDATE memory_summaries
            SET scope = CASE
                WHEN topic_id IS NOT NULL AND topic_id != '' THEN 'topic:' || topic_id
                ELSE 'global'
            END
            WHERE scope IS NULL OR scope = ''
            """
        )
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute(
            """
            UPDATE memory_events
            SET type = CASE
                WHEN tags_json LIKE '%"policy"%' THEN 'policy'
                WHEN tags_json LIKE '%"protocol"%' THEN 'instruction'
                WHEN tags_json LIKE '%"profile"%' THEN 'preference'
                WHEN tags_json LIKE '%"decision"%' THEN 'event'
                WHEN tags_json LIKE '%"canon"%' THEN 'concept'
                ELSE 'event'
            END
            WHERE (type IS NULL OR type = '' OR type = 'event')
              AND tags_json IS NOT NULL AND tags_json != ''
            """
        )
    except sqlite3.OperationalError:
        pass

    cur.execute("CREATE INDEX IF NOT EXISTS idx_mem_events_scope ON memory_events(scope)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mem_events_type ON memory_events(type)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mem_events_lifecycle ON memory_events(lifecycle)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mem_events_last_verified ON memory_events(last_verified_at_utc)")

    cur.execute("CREATE INDEX IF NOT EXISTS idx_mem_summaries_type ON memory_summaries(summary_type)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mem_summaries_scope ON memory_summaries(scope)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mem_summaries_lifecycle ON memory_summaries(lifecycle)")

    conn.commit()

