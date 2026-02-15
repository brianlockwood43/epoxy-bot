from __future__ import annotations

import sqlite3
from typing import Any
from typing import Callable


class MemoryLifecycleError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = str(code)


def _normalize_memory_row(
    row_obj: dict[str, Any],
    *,
    safe_json_loads: Callable[[str], Any],
) -> dict[str, Any]:
    out = dict(row_obj)
    raw_tags = safe_json_loads(str(out.get("tags_json") or "[]"))
    if not isinstance(raw_tags, list):
        raw_tags = []
    tags: list[str] = []
    seen: set[str] = set()
    for tag in raw_tags:
        cleaned = str(tag or "").strip().lower()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        tags.append(cleaned)
    out["tags"] = tags
    out["importance"] = _normalize_importance(out.get("importance"), default=0.5)
    return out


def _fetch_memory_row_by_id(cur: sqlite3.Cursor, memory_id: int) -> dict[str, Any] | None:
    cur.execute("SELECT * FROM memory_events WHERE id = ? LIMIT 1", (int(memory_id),))
    row = cur.fetchone()
    if row is None:
        return None
    cols = [str(d[0]) for d in (cur.description or ())]
    return {cols[i]: row[i] for i in range(len(cols))}


def _normalize_importance(importance: Any, *, default: float = 0.5) -> float:
    if importance is None:
        return float(default)
    try:
        value = float(importance)
    except Exception as exc:
        raise MemoryLifecycleError("invalid_importance", "importance must be numeric") from exc
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return float(value)


def list_candidate_memories_sync(
    conn: sqlite3.Connection,
    *,
    limit: int = 20,
    offset: int = 0,
    safe_json_loads: Callable[[str], Any],
) -> list[dict[str, Any]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, created_at_utc, created_ts, scope, lifecycle, text, tags_json, importance, topic_id
        FROM memory_events
        WHERE COALESCE(lifecycle, 'active') = 'candidate'
        ORDER BY COALESCE(created_ts, 0) DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        (int(limit), int(offset)),
    )
    rows = cur.fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = {
            "id": int(row[0]),
            "created_at_utc": row[1],
            "created_ts": int(row[2] or 0),
            "scope": row[3] or "global",
            "lifecycle": row[4] or "active",
            "text": row[5] or "",
            "tags_json": row[6] or "[]",
            "importance": _normalize_importance(row[7], default=0.5),
            "topic_id": row[8] or "",
        }
        out.append(_normalize_memory_row(item, safe_json_loads=safe_json_loads))
    return out


def write_memory_audit_sync(
    conn: sqlite3.Connection,
    *,
    memory_id: int,
    action: str,
    actor_person_id: int | None,
    before_obj: dict[str, Any],
    after_obj: dict[str, Any],
    reason: str | None,
    created_at_utc: str,
    safe_json_dumps: Callable[[Any], str],
) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO memory_audit_log (
            memory_id,
            action,
            actor_person_id,
            before_json,
            after_json,
            reason,
            created_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(memory_id),
            str(action),
            int(actor_person_id) if actor_person_id is not None else None,
            safe_json_dumps(before_obj or {}),
            safe_json_dumps(after_obj or {}),
            (str(reason).strip() if reason else None),
            str(created_at_utc),
        ),
    )


def approve_memory_sync(
    conn: sqlite3.Connection,
    *,
    memory_id: int,
    actor_person_id: int | None,
    tags: list[str] | None = None,
    topic_id: str | None = None,
    importance: float | None = None,
    note: str | None = None,
    utc_now_iso: Callable[[], str],
    normalize_tags: Callable[[list[str]], list[str]],
    safe_json_loads: Callable[[str], Any],
    safe_json_dumps: Callable[[Any], str],
) -> dict[str, Any]:
    now_iso = str(utc_now_iso())
    conn.execute("BEGIN")
    try:
        cur = conn.cursor()
        before_row = _fetch_memory_row_by_id(cur, int(memory_id))
        if before_row is None:
            raise MemoryLifecycleError("not_found", f"memory #{int(memory_id)} not found")

        lifecycle = str(before_row.get("lifecycle") or "active").strip().lower()
        if lifecycle != "candidate":
            raise MemoryLifecycleError("not_candidate", "memory lifecycle must be candidate")

        existing_tags = safe_json_loads(str(before_row.get("tags_json") or "[]"))
        if not isinstance(existing_tags, list):
            existing_tags = []
        existing_tags_clean = [str(tag or "").strip().lower() for tag in existing_tags if str(tag or "").strip()]
        next_tags = normalize_tags(list(existing_tags_clean))
        if tags is not None:
            next_tags = normalize_tags(list(tags))

        current_topic = str(before_row.get("topic_id") or "").strip().lower()
        next_topic = current_topic
        if topic_id is not None:
            next_topic = str(topic_id or "").strip().lower()
        if next_topic and next_topic not in next_tags:
            next_tags = [next_topic] + [tag for tag in next_tags if tag != next_topic]

        next_importance = 0.5 if importance is None else _normalize_importance(importance, default=0.5)

        review_note = str(note).strip() if note and str(note).strip() else None
        tags_json = safe_json_dumps(next_tags)
        cur.execute(
            """
            UPDATE memory_events
            SET lifecycle = 'active',
                updated_at_utc = ?,
                reviewed_by_user_id = ?,
                reviewed_at_utc = ?,
                review_note = ?,
                tags_json = ?,
                topic_id = ?,
                importance = ?
            WHERE id = ?
            """,
            (
                now_iso,
                int(actor_person_id) if actor_person_id is not None else None,
                now_iso,
                review_note,
                tags_json,
                next_topic or None,
                float(next_importance),
                int(memory_id),
            ),
        )

        cur.execute("DELETE FROM memory_events_fts WHERE rowid = ?", (int(memory_id),))
        cur.execute(
            "INSERT INTO memory_events_fts(rowid, text, tags) VALUES (?, ?, ?)",
            (
                int(memory_id),
                str(before_row.get("text") or ""),
                " ".join(next_tags),
            ),
        )

        after_row = _fetch_memory_row_by_id(cur, int(memory_id))
        if after_row is None:
            raise MemoryLifecycleError("not_found", f"memory #{int(memory_id)} not found after update")

        before_snapshot = _normalize_memory_row(before_row, safe_json_loads=safe_json_loads)
        after_snapshot = _normalize_memory_row(after_row, safe_json_loads=safe_json_loads)
        write_memory_audit_sync(
            conn,
            memory_id=int(memory_id),
            action="approve",
            actor_person_id=actor_person_id,
            before_obj=before_snapshot,
            after_obj=after_snapshot,
            reason=review_note,
            created_at_utc=now_iso,
            safe_json_dumps=safe_json_dumps,
        )

        conn.commit()
        return after_snapshot
    except Exception:
        conn.rollback()
        raise


def reject_memory_sync(
    conn: sqlite3.Connection,
    *,
    memory_id: int,
    actor_person_id: int | None,
    reason: str | None = None,
    utc_now_iso: Callable[[], str],
    safe_json_loads: Callable[[str], Any],
    safe_json_dumps: Callable[[Any], str],
) -> dict[str, Any]:
    now_iso = str(utc_now_iso())
    conn.execute("BEGIN")
    try:
        cur = conn.cursor()
        before_row = _fetch_memory_row_by_id(cur, int(memory_id))
        if before_row is None:
            raise MemoryLifecycleError("not_found", f"memory #{int(memory_id)} not found")

        lifecycle = str(before_row.get("lifecycle") or "active").strip().lower()
        if lifecycle != "candidate":
            raise MemoryLifecycleError("not_candidate", "memory lifecycle must be candidate")

        clean_reason = str(reason).strip() if reason and str(reason).strip() else None
        cur.execute(
            """
            UPDATE memory_events
            SET lifecycle = 'deprecated',
                updated_at_utc = ?,
                reviewed_by_user_id = ?,
                reviewed_at_utc = ?,
                review_note = ?
            WHERE id = ?
            """,
            (
                now_iso,
                int(actor_person_id) if actor_person_id is not None else None,
                now_iso,
                clean_reason,
                int(memory_id),
            ),
        )

        after_row = _fetch_memory_row_by_id(cur, int(memory_id))
        if after_row is None:
            raise MemoryLifecycleError("not_found", f"memory #{int(memory_id)} not found after update")

        before_snapshot = _normalize_memory_row(before_row, safe_json_loads=safe_json_loads)
        after_snapshot = _normalize_memory_row(after_row, safe_json_loads=safe_json_loads)
        write_memory_audit_sync(
            conn,
            memory_id=int(memory_id),
            action="reject",
            actor_person_id=actor_person_id,
            before_obj=before_snapshot,
            after_obj=after_snapshot,
            reason=clean_reason,
            created_at_utc=now_iso,
            safe_json_dumps=safe_json_dumps,
        )

        conn.commit()
        return after_snapshot
    except Exception:
        conn.rollback()
        raise
