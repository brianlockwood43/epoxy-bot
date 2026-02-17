from __future__ import annotations

import json
import re
import sqlite3


def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (table,))
    return cur.fetchone() is not None


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    return any(str(row[1]) == column for row in cur.fetchall())


def _safe_json_loads(raw: str) -> list[str]:
    try:
        parsed = json.loads(raw or "[]")
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    out: list[str] = []
    for value in parsed:
        clean = str(value or "").strip().lower()
        if clean:
            out.append(clean)
    return out


def _extract_kind_from_tags(tags: list[str]) -> str | None:
    known_kinds = {
        "decision",
        "policy",
        "canon",
        "profile",
        "protocol",
        "proposal",
        "insight",
        "task",
        "event",
        "preference",
        "concept",
        "relationship",
        "instruction",
        "skill",
        "artifact_ref",
        "note",
    }
    for tag in tags:
        match = re.fullmatch(r"kind:([a-z0-9_\-]+)", tag)
        if match:
            kind = str(match.group(1) or "").strip().lower()
            if kind:
                return kind
        if re.fullmatch(r"[a-z0-9_\-]+", tag) and tag in known_kinds:
            return tag
    return None


def _backfill_type_from_tags(conn: sqlite3.Connection) -> None:
    if not _has_column(conn, "memory_events", "type"):
        return
    if not _has_column(conn, "memory_events", "tags_json"):
        return

    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, tags_json
        FROM memory_events
        WHERE type IS NULL OR TRIM(type) = ''
        """
    )
    rows = cur.fetchall()
    for memory_id, tags_json in rows:
        kind = _extract_kind_from_tags(_safe_json_loads(str(tags_json or "[]"))) or "event"
        cur.execute(
            "UPDATE memory_events SET type = ? WHERE id = ?",
            (kind, int(memory_id)),
        )


def upgrade(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    conn.execute("BEGIN")
    try:
        if _has_table(conn, "memory_events"):
            if not _has_column(conn, "memory_events", "provenance_json"):
                cur.execute("ALTER TABLE memory_events ADD COLUMN provenance_json TEXT DEFAULT '{}'")
            cur.execute(
                """
                UPDATE memory_events
                SET provenance_json='{}'
                WHERE provenance_json IS NULL OR TRIM(provenance_json) = ''
                """
            )
            _backfill_type_from_tags(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
