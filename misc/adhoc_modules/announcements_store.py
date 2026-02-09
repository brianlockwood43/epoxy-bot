from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any


ANNOUNCEMENT_TERMINAL_STATES = {"posted", "manual_done", "missed", "cancelled"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dumps(value: Any, fallback: str = "{}") -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return fallback


def _row_to_cycle(row: sqlite3.Row | tuple[Any, ...] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    cols = [
        "id",
        "target_date_local",
        "timezone",
        "weekday_key",
        "status",
        "completion_path",
        "prep_channel_id",
        "prep_message_id",
        "prep_thread_id",
        "target_channel_id",
        "publish_at_utc",
        "draft_text",
        "override_text",
        "final_text",
        "approved_by_user_id",
        "approved_at_utc",
        "posted_message_id",
        "posted_at_utc",
        "manual_done_by_user_id",
        "manual_done_at_utc",
        "manual_done_link",
        "manual_done_note",
        "manual_prev_status",
        "created_at_utc",
        "updated_at_utc",
        "last_error",
    ]
    out: dict[str, Any] = {}
    for idx, col in enumerate(cols):
        out[col] = row[idx]
    for k in (
        "id",
        "prep_channel_id",
        "prep_message_id",
        "prep_thread_id",
        "target_channel_id",
        "approved_by_user_id",
        "posted_message_id",
        "manual_done_by_user_id",
    ):
        if out.get(k) is not None:
            out[k] = int(out[k])
    return out


def fetch_cycle_by_date_sync(conn: sqlite3.Connection, *, target_date_local: str, timezone: str) -> dict[str, Any] | None:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            id, target_date_local, timezone, weekday_key, status, completion_path,
            prep_channel_id, prep_message_id, prep_thread_id, target_channel_id, publish_at_utc,
            draft_text, override_text, final_text, approved_by_user_id, approved_at_utc,
            posted_message_id, posted_at_utc, manual_done_by_user_id, manual_done_at_utc,
            manual_done_link, manual_done_note, manual_prev_status, created_at_utc,
            updated_at_utc, last_error
        FROM announcement_cycles
        WHERE target_date_local = ? AND timezone = ?
        LIMIT 1
        """,
        (target_date_local, timezone),
    )
    return _row_to_cycle(cur.fetchone())


def fetch_cycle_by_id_sync(conn: sqlite3.Connection, cycle_id: int) -> dict[str, Any] | None:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            id, target_date_local, timezone, weekday_key, status, completion_path,
            prep_channel_id, prep_message_id, prep_thread_id, target_channel_id, publish_at_utc,
            draft_text, override_text, final_text, approved_by_user_id, approved_at_utc,
            posted_message_id, posted_at_utc, manual_done_by_user_id, manual_done_at_utc,
            manual_done_link, manual_done_note, manual_prev_status, created_at_utc,
            updated_at_utc, last_error
        FROM announcement_cycles
        WHERE id = ?
        LIMIT 1
        """,
        (int(cycle_id),),
    )
    return _row_to_cycle(cur.fetchone())


def fetch_cycle_by_prep_thread_sync(conn: sqlite3.Connection, prep_thread_id: int) -> dict[str, Any] | None:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            id, target_date_local, timezone, weekday_key, status, completion_path,
            prep_channel_id, prep_message_id, prep_thread_id, target_channel_id, publish_at_utc,
            draft_text, override_text, final_text, approved_by_user_id, approved_at_utc,
            posted_message_id, posted_at_utc, manual_done_by_user_id, manual_done_at_utc,
            manual_done_link, manual_done_note, manual_prev_status, created_at_utc,
            updated_at_utc, last_error
        FROM announcement_cycles
        WHERE prep_thread_id = ?
        LIMIT 1
        """,
        (int(prep_thread_id),),
    )
    return _row_to_cycle(cur.fetchone())


def create_or_get_cycle_sync(
    conn: sqlite3.Connection,
    *,
    target_date_local: str,
    timezone: str,
    weekday_key: str,
    target_channel_id: int,
    publish_at_utc: str,
) -> dict[str, Any]:
    cur = conn.cursor()
    now = _utc_now_iso()
    cur.execute(
        """
        INSERT INTO announcement_cycles (
            target_date_local, timezone, weekday_key, status,
            target_channel_id, publish_at_utc, created_at_utc, updated_at_utc
        )
        VALUES (?, ?, ?, 'planned', ?, ?, ?, ?)
        ON CONFLICT(target_date_local, timezone) DO NOTHING
        """,
        (target_date_local, timezone, weekday_key, int(target_channel_id), publish_at_utc, now, now),
    )
    conn.commit()
    row = fetch_cycle_by_date_sync(conn, target_date_local=target_date_local, timezone=timezone)
    if not row:
        raise RuntimeError("Failed to create/fetch announcement cycle")
    return row


def update_cycle_fields_sync(conn: sqlite3.Connection, cycle_id: int, fields: dict[str, Any]) -> dict[str, Any] | None:
    if not fields:
        return fetch_cycle_by_id_sync(conn, cycle_id)
    if any(key in {"id", "target_date_local", "timezone"} for key in fields.keys()):
        raise ValueError("Immutable cycle fields cannot be updated")

    assignments: list[str] = []
    values: list[Any] = []
    for key, value in fields.items():
        assignments.append(f"{key} = ?")
        values.append(value)
    assignments.append("updated_at_utc = ?")
    values.append(_utc_now_iso())
    values.append(int(cycle_id))

    cur = conn.cursor()
    cur.execute(
        f"UPDATE announcement_cycles SET {', '.join(assignments)} WHERE id = ?",
        tuple(values),
    )
    conn.commit()
    return fetch_cycle_by_id_sync(conn, int(cycle_id))


def set_prep_refs_sync(
    conn: sqlite3.Connection,
    *,
    cycle_id: int,
    prep_channel_id: int,
    prep_message_id: int | None,
    prep_thread_id: int | None,
) -> dict[str, Any] | None:
    return update_cycle_fields_sync(
        conn,
        int(cycle_id),
        {
            "prep_channel_id": int(prep_channel_id),
            "prep_message_id": int(prep_message_id) if prep_message_id is not None else None,
            "prep_thread_id": int(prep_thread_id) if prep_thread_id is not None else None,
            "status": "prep_pinged",
        },
    )


def set_draft_sync(conn: sqlite3.Connection, *, cycle_id: int, draft_text: str, clear_approval: bool = True) -> dict[str, Any] | None:
    fields: dict[str, Any] = {
        "draft_text": (draft_text or "").strip(),
        "status": "draft_ready",
        "last_error": None,
    }
    if clear_approval:
        fields["approved_by_user_id"] = None
        fields["approved_at_utc"] = None
    return update_cycle_fields_sync(conn, int(cycle_id), fields)


def set_override_sync(conn: sqlite3.Connection, *, cycle_id: int, override_text: str | None) -> dict[str, Any] | None:
    return update_cycle_fields_sync(
        conn,
        int(cycle_id),
        {"override_text": (override_text or "").strip() if override_text is not None else None},
    )


def approve_cycle_sync(conn: sqlite3.Connection, *, cycle_id: int, user_id: int) -> dict[str, Any] | None:
    return update_cycle_fields_sync(
        conn,
        int(cycle_id),
        {
            "status": "approved",
            "approved_by_user_id": int(user_id),
            "approved_at_utc": _utc_now_iso(),
            "last_error": None,
        },
    )


def unapprove_cycle_sync(conn: sqlite3.Connection, *, cycle_id: int) -> dict[str, Any] | None:
    return update_cycle_fields_sync(
        conn,
        int(cycle_id),
        {
            "status": "draft_ready",
            "approved_by_user_id": None,
            "approved_at_utc": None,
        },
    )


def mark_manual_done_sync(
    conn: sqlite3.Connection,
    *,
    cycle_id: int,
    user_id: int,
    completion_path: str,
    link: str | None,
    note: str | None,
) -> dict[str, Any] | None:
    current = fetch_cycle_by_id_sync(conn, int(cycle_id))
    if not current:
        return None
    prev_status = current.get("status") or "planned"
    return update_cycle_fields_sync(
        conn,
        int(cycle_id),
        {
            "status": "manual_done",
            "completion_path": completion_path,
            "manual_done_by_user_id": int(user_id),
            "manual_done_at_utc": _utc_now_iso(),
            "manual_done_link": (link or "").strip() or None,
            "manual_done_note": (note or "").strip() or None,
            "manual_prev_status": prev_status,
            "last_error": None,
        },
    )


def undo_manual_done_sync(conn: sqlite3.Connection, *, cycle_id: int) -> dict[str, Any] | None:
    current = fetch_cycle_by_id_sync(conn, int(cycle_id))
    if not current:
        return None
    restored = (current.get("manual_prev_status") or "draft_ready").strip() or "draft_ready"
    if restored in ANNOUNCEMENT_TERMINAL_STATES:
        restored = "draft_ready"
    return update_cycle_fields_sync(
        conn,
        int(cycle_id),
        {
            "status": restored,
            "completion_path": None,
            "manual_done_by_user_id": None,
            "manual_done_at_utc": None,
            "manual_done_link": None,
            "manual_done_note": None,
            "manual_prev_status": None,
        },
    )


def mark_missed_sync(conn: sqlite3.Connection, *, cycle_id: int, reason: str | None = None) -> dict[str, Any] | None:
    return update_cycle_fields_sync(
        conn,
        int(cycle_id),
        {"status": "missed", "last_error": (reason or "").strip() or None},
    )


def mark_posted_sync(
    conn: sqlite3.Connection,
    *,
    cycle_id: int,
    posted_message_id: int | None,
    final_text: str,
    completion_path: str = "epoxy_posted",
) -> bool:
    cur = conn.cursor()
    now = _utc_now_iso()
    cur.execute(
        """
        UPDATE announcement_cycles
        SET status='posted',
            completion_path=?,
            posted_message_id=?,
            posted_at_utc=?,
            final_text=?,
            updated_at_utc=?,
            last_error=NULL
        WHERE id=?
          AND status='approved'
          AND posted_at_utc IS NULL
        """,
        (
            completion_path,
            int(posted_message_id) if posted_message_id is not None else None,
            now,
            (final_text or "").strip(),
            now,
            int(cycle_id),
        ),
    )
    conn.commit()
    return cur.rowcount > 0


def upsert_answer_sync(
    conn: sqlite3.Connection,
    *,
    cycle_id: int,
    question_id: str,
    answer_text: str,
    answered_by_user_id: int,
    source_message_id: int | None,
) -> int:
    now = _utc_now_iso()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO announcement_answers (
            cycle_id, question_id, answer_text, answered_by_user_id, answered_at_utc, source_message_id
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(cycle_id, question_id) DO UPDATE SET
            answer_text=excluded.answer_text,
            answered_by_user_id=excluded.answered_by_user_id,
            answered_at_utc=excluded.answered_at_utc,
            source_message_id=excluded.source_message_id
        """,
        (
            int(cycle_id),
            (question_id or "").strip().lower(),
            (answer_text or "").strip(),
            int(answered_by_user_id),
            now,
            int(source_message_id) if source_message_id is not None else None,
        ),
    )
    conn.commit()
    if cur.lastrowid:
        return int(cur.lastrowid)
    cur.execute(
        """
        SELECT id FROM announcement_answers
        WHERE cycle_id = ? AND question_id = ?
        LIMIT 1
        """,
        (int(cycle_id), (question_id or "").strip().lower()),
    )
    row = cur.fetchone()
    return int(row[0]) if row else 0


def fetch_answers_sync(conn: sqlite3.Connection, cycle_id: int) -> list[dict[str, Any]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, cycle_id, question_id, answer_text, answered_by_user_id, answered_at_utc, source_message_id
        FROM announcement_answers
        WHERE cycle_id = ?
        ORDER BY id ASC
        """,
        (int(cycle_id),),
    )
    out: list[dict[str, Any]] = []
    for row in cur.fetchall():
        out.append(
            {
                "id": int(row[0]),
                "cycle_id": int(row[1]),
                "question_id": row[2],
                "answer_text": row[3],
                "answered_by_user_id": int(row[4]) if row[4] is not None else None,
                "answered_at_utc": row[5],
                "source_message_id": int(row[6]) if row[6] is not None else None,
            }
        )
    return out


def insert_audit_log_sync(
    conn: sqlite3.Connection,
    *,
    cycle_id: int | None,
    action: str,
    actor_type: str,
    actor_user_id: int | None,
    payload: dict[str, Any] | None = None,
) -> int:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO announcement_audit_log (
            cycle_id, action, actor_type, actor_user_id, payload_json, created_at_utc
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            int(cycle_id) if cycle_id is not None else None,
            (action or "").strip().lower(),
            (actor_type or "").strip().lower(),
            int(actor_user_id) if actor_user_id is not None else None,
            _dumps(payload or {}, "{}"),
            _utc_now_iso(),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def list_audit_log_sync(conn: sqlite3.Connection, cycle_id: int, limit: int = 100) -> list[dict[str, Any]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, cycle_id, action, actor_type, actor_user_id, payload_json, created_at_utc
        FROM announcement_audit_log
        WHERE cycle_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (int(cycle_id), max(1, min(int(limit), 500))),
    )
    out: list[dict[str, Any]] = []
    for row in cur.fetchall():
        payload: dict[str, Any]
        try:
            payload = json.loads(row[5] or "{}")
        except Exception:
            payload = {}
        out.append(
            {
                "id": int(row[0]),
                "cycle_id": int(row[1]),
                "action": row[2],
                "actor_type": row[3],
                "actor_user_id": int(row[4]) if row[4] is not None else None,
                "payload": payload,
                "created_at_utc": row[6],
            }
        )
    return out
