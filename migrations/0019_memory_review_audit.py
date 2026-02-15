from __future__ import annotations

import json
import sqlite3


def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (table,))
    return cur.fetchone() is not None


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    return any(str(row[1]) == column for row in cur.fetchall())


def _table_columns(conn: sqlite3.Connection, table: str) -> list[tuple[str, str]]:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    out: list[tuple[str, str]] = []
    for row in cur.fetchall():
        out.append((str(row[1]), str(row[2] or "")))
    return out


def _is_real_declared_type(column_type: str) -> bool:
    t = str(column_type or "").strip().upper()
    return ("REAL" in t) or ("FLOA" in t) or ("DOUB" in t)


def _select_or_default(existing_cols: set[str], col: str, default_sql: str = "NULL") -> str:
    return col if col in existing_cols else default_sql


def _normalized_importance_expr(existing_cols: set[str]) -> str:
    if "importance" not in existing_cols:
        return "0.5"
    return (
        "CASE "
        "WHEN importance IS NULL OR TRIM(CAST(importance AS TEXT)) = '' THEN 0.5 "
        "WHEN CAST(importance AS REAL) < 0.0 THEN 0.0 "
        "WHEN CAST(importance AS REAL) > 1.0 THEN 1.0 "
        "ELSE CAST(importance AS REAL) "
        "END"
    )


def _create_memory_events_v2(cur: sqlite3.Cursor) -> None:
    cur.execute(
        """
        CREATE TABLE memory_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at_utc TEXT,
            created_ts INTEGER,
            updated_at_utc TEXT,
            last_verified_at_utc TEXT,
            expiry_at_utc TEXT,
            scope TEXT DEFAULT NULL,
            guild_id INTEGER,
            channel_id INTEGER,
            channel_name TEXT,
            author_id INTEGER,
            author_name TEXT,
            source_message_id INTEGER,
            logged_from_channel_id INTEGER,
            logged_from_channel_name TEXT,
            logged_from_message_id INTEGER,
            source_channel_id INTEGER,
            source_channel_name TEXT,
            type TEXT DEFAULT 'event',
            title TEXT DEFAULT NULL,
            text TEXT NOT NULL,
            tags_json TEXT,
            confidence REAL DEFAULT 0.6,
            stability TEXT DEFAULT 'medium',
            lifecycle TEXT DEFAULT 'active',
            superseded_by INTEGER DEFAULT NULL,
            importance REAL DEFAULT 0.5,
            tier INTEGER DEFAULT 1,
            summarized INTEGER DEFAULT 0,
            topic_id TEXT,
            topic_source TEXT DEFAULT 'manual',
            topic_confidence REAL,
            reviewed_by_user_id INTEGER,
            reviewed_at_utc TEXT,
            review_note TEXT
        )
        """
    )


def _create_memory_event_indexes(cur: sqlite3.Cursor) -> None:
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mem_events_scope ON memory_events(scope)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mem_events_type ON memory_events(type)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mem_events_lifecycle ON memory_events(lifecycle)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mem_events_last_verified ON memory_events(last_verified_at_utc)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mem_events_created_ts ON memory_events(created_ts)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mem_events_tier ON memory_events(tier)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mem_events_importance ON memory_events(importance)")


def _ensure_review_columns(cur: sqlite3.Cursor, conn: sqlite3.Connection) -> None:
    if not _has_column(conn, "memory_events", "reviewed_by_user_id"):
        cur.execute("ALTER TABLE memory_events ADD COLUMN reviewed_by_user_id INTEGER")
    if not _has_column(conn, "memory_events", "reviewed_at_utc"):
        cur.execute("ALTER TABLE memory_events ADD COLUMN reviewed_at_utc TEXT")
    if not _has_column(conn, "memory_events", "review_note"):
        cur.execute("ALTER TABLE memory_events ADD COLUMN review_note TEXT")


def _ensure_audit_table(cur: sqlite3.Cursor) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            actor_person_id INTEGER,
            before_json TEXT NOT NULL DEFAULT '{}',
            after_json TEXT NOT NULL DEFAULT '{}',
            reason TEXT,
            created_at_utc TEXT NOT NULL
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_memory_audit_memory_id ON memory_audit_log(memory_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_memory_audit_created_at ON memory_audit_log(created_at_utc)")


def _rebuild_memory_events_fts(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS memory_events_fts
        USING fts5(text, tags, tokenize='unicode61')
        """
    )
    cur.execute("DELETE FROM memory_events_fts")
    cur.execute("SELECT id, text, tags_json, topic_id FROM memory_events ORDER BY id ASC")
    rows = cur.fetchall()
    for memory_id, text, tags_json, topic_id in rows:
        text_value = str(text or "")
        try:
            tags_raw = json.loads(tags_json or "[]")
        except Exception:
            tags_raw = []
        if not isinstance(tags_raw, list):
            tags_raw = []

        tags: list[str] = []
        seen: set[str] = set()
        for tag in tags_raw:
            clean = str(tag or "").strip().lower()
            if not clean or clean in seen:
                continue
            seen.add(clean)
            tags.append(clean)

        topic = str(topic_id or "").strip().lower()
        if topic and topic not in seen:
            tags = [topic] + tags

        cur.execute(
            "INSERT INTO memory_events_fts(rowid, text, tags) VALUES (?, ?, ?)",
            (int(memory_id), text_value, " ".join(tags)),
        )


def _rebuild_memory_events_table(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    old_table = "memory_events__old_0019"
    if _has_table(conn, old_table):
        cur.execute(f"DROP TABLE {old_table}")
    cur.execute(f"ALTER TABLE memory_events RENAME TO {old_table}")

    old_cols = {name for name, _ in _table_columns(conn, old_table)}
    _create_memory_events_v2(cur)
    _create_memory_event_indexes(cur)

    select_sql = f"""
        INSERT INTO memory_events (
            id,
            created_at_utc,
            created_ts,
            updated_at_utc,
            last_verified_at_utc,
            expiry_at_utc,
            scope,
            guild_id,
            channel_id,
            channel_name,
            author_id,
            author_name,
            source_message_id,
            logged_from_channel_id,
            logged_from_channel_name,
            logged_from_message_id,
            source_channel_id,
            source_channel_name,
            type,
            title,
            text,
            tags_json,
            confidence,
            stability,
            lifecycle,
            superseded_by,
            importance,
            tier,
            summarized,
            topic_id,
            topic_source,
            topic_confidence,
            reviewed_by_user_id,
            reviewed_at_utc,
            review_note
        )
        SELECT
            {_select_or_default(old_cols, 'id')},
            {_select_or_default(old_cols, 'created_at_utc')},
            {_select_or_default(old_cols, 'created_ts', '0')},
            {_select_or_default(old_cols, 'updated_at_utc')},
            {_select_or_default(old_cols, 'last_verified_at_utc')},
            {_select_or_default(old_cols, 'expiry_at_utc')},
            {_select_or_default(old_cols, 'scope', "'global'")},
            {_select_or_default(old_cols, 'guild_id')},
            {_select_or_default(old_cols, 'channel_id')},
            {_select_or_default(old_cols, 'channel_name')},
            {_select_or_default(old_cols, 'author_id')},
            {_select_or_default(old_cols, 'author_name')},
            {_select_or_default(old_cols, 'source_message_id')},
            {_select_or_default(old_cols, 'logged_from_channel_id')},
            {_select_or_default(old_cols, 'logged_from_channel_name')},
            {_select_or_default(old_cols, 'logged_from_message_id')},
            {_select_or_default(old_cols, 'source_channel_id')},
            {_select_or_default(old_cols, 'source_channel_name')},
            {_select_or_default(old_cols, 'type', "'event'")},
            {_select_or_default(old_cols, 'title')},
            {_select_or_default(old_cols, 'text', "''")},
            {_select_or_default(old_cols, 'tags_json', "'[]'")},
            {_select_or_default(old_cols, 'confidence', '0.6')},
            {_select_or_default(old_cols, 'stability', "'medium'")},
            {_select_or_default(old_cols, 'lifecycle', "'active'")},
            {_select_or_default(old_cols, 'superseded_by')},
            {_normalized_importance_expr(old_cols)},
            {_select_or_default(old_cols, 'tier', '1')},
            {_select_or_default(old_cols, 'summarized', '0')},
            {_select_or_default(old_cols, 'topic_id')},
            {_select_or_default(old_cols, 'topic_source', "'manual'")},
            {_select_or_default(old_cols, 'topic_confidence')},
            {_select_or_default(old_cols, 'reviewed_by_user_id')},
            {_select_or_default(old_cols, 'reviewed_at_utc')},
            {_select_or_default(old_cols, 'review_note')}
        FROM {old_table}
    """
    cur.execute(select_sql)
    cur.execute(f"DROP TABLE {old_table}")


def upgrade(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    conn.execute("BEGIN")
    try:
        if _has_table(conn, "memory_events"):
            col_types = dict(_table_columns(conn, "memory_events"))
            importance_type = str(col_types.get("importance") or "")
            needs_rebuild = not _is_real_declared_type(importance_type)
            if needs_rebuild:
                _rebuild_memory_events_table(conn)
            else:
                _ensure_review_columns(cur, conn)
                _create_memory_event_indexes(cur)

            _rebuild_memory_events_fts(conn)

        _ensure_audit_table(cur)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
