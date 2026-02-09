from __future__ import annotations

import re
import sqlite3
import time
from typing import Any, Callable


def insert_memory_event_sync(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    *,
    safe_json_loads: Callable[[str], list[Any]],
) -> int:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO memory_events (
            created_at_utc, created_ts,
            guild_id, channel_id, channel_name,
            author_id, author_name,
            source_message_id,
            text, tags_json, importance, tier,
            topic_id, topic_source, topic_confidence,
            summarized,
            logged_from_channel_id, logged_from_channel_name, logged_from_message_id,
            source_channel_id, source_channel_name
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload["created_at_utc"],
            payload["created_ts"],
            payload.get("guild_id"),
            payload.get("channel_id"),
            payload.get("channel_name"),
            payload.get("author_id"),
            payload.get("author_name"),
            payload.get("source_message_id"),
            payload["text"],
            payload.get("tags_json", "[]"),
            int(payload.get("importance", 0)),
            int(payload.get("tier", 1)),
            payload.get("topic_id"),
            payload.get("topic_source", "none"),
            payload.get("topic_confidence"),
            int(payload.get("summarized", 0)),
            payload.get("logged_from_channel_id"),
            payload.get("logged_from_channel_name"),
            payload.get("logged_from_message_id"),
            payload.get("source_channel_id"),
            payload.get("source_channel_name"),
        ),
    )
    mem_id = int(cur.lastrowid)

    tags_list = safe_json_loads(payload.get("tags_json", "[]"))
    topic_id = (payload.get("topic_id") or "").strip().lower()
    if topic_id and topic_id not in tags_list:
        tags_list = [topic_id] + list(tags_list)
    tags_for_fts = " ".join(tags_list)

    cur.execute(
        "INSERT INTO memory_events_fts(rowid, text, tags) VALUES (?, ?, ?)",
        (mem_id, payload["text"], tags_for_fts),
    )
    conn.commit()
    return mem_id


def mark_events_summarized_sync(conn: sqlite3.Connection, event_ids: list[int]) -> None:
    if not event_ids:
        return
    cur = conn.cursor()
    cur.execute(
        f"UPDATE memory_events SET summarized = 1 WHERE id IN ({','.join(['?'] * len(event_ids))})",
        tuple(event_ids),
    )
    conn.commit()


def search_memory_events_by_tag_sync(
    conn: sqlite3.Connection,
    subject_tag: str,
    kind_tag: str,
    limit: int,
    *,
    safe_json_loads: Callable[[str], list[Any]],
) -> list[dict[str, Any]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, created_at_utc, channel_name, author_name, text, tags_json, importance, topic_id
        FROM memory_events
        WHERE tags_json LIKE ? AND tags_json LIKE ?
        ORDER BY created_ts DESC
        LIMIT ?
        """,
        (f'%"{subject_tag}"%', f'%"{kind_tag}"%', int(limit)),
    )
    rows = cur.fetchall()
    out = []
    for r in rows:
        out.append(
            {
                "id": r[0],
                "created_at_utc": r[1],
                "channel_name": r[2],
                "author_name": r[3],
                "text": r[4],
                "tags": safe_json_loads(r[5] or "[]"),
                "importance": r[6],
                "topic_id": r[7],
            }
        )
    return out


def upsert_summary_sync(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    *,
    safe_json_loads: Callable[[str], list[Any]],
) -> int:
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM memory_summaries WHERE topic_id = ? ORDER BY id DESC LIMIT 1",
        (payload["topic_id"],),
    )
    row = cur.fetchone()
    if row:
        sid = int(row[0])
        cur.execute(
            """
            UPDATE memory_summaries
            SET updated_at_utc=?, start_ts=?, end_ts=?, tags_json=?, importance=?, summary_text=?
            WHERE id=?
            """,
            (
                payload["updated_at_utc"],
                payload.get("start_ts"),
                payload.get("end_ts"),
                payload.get("tags_json", "[]"),
                int(payload.get("importance", 1)),
                payload["summary_text"],
                sid,
            ),
        )
    else:
        cur.execute(
            """
            INSERT INTO memory_summaries (
                topic_id, created_at_utc, updated_at_utc,
                start_ts, end_ts, tags_json, importance, summary_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["topic_id"],
                payload["created_at_utc"],
                payload["updated_at_utc"],
                payload.get("start_ts"),
                payload.get("end_ts"),
                payload.get("tags_json", "[]"),
                int(payload.get("importance", 1)),
                payload["summary_text"],
            ),
        )
        sid = int(cur.lastrowid)

    tags_for_fts = " ".join(safe_json_loads(payload.get("tags_json", "[]")))
    cur.execute("DELETE FROM memory_summaries_fts WHERE rowid = ?", (sid,))
    cur.execute(
        "INSERT INTO memory_summaries_fts(rowid, topic_id, summary_text, tags) VALUES (?, ?, ?, ?)",
        (sid, payload["topic_id"], payload["summary_text"], tags_for_fts),
    )

    conn.commit()
    return sid


def search_memory_events_sync(
    conn: sqlite3.Connection,
    query: str,
    scope: str,
    limit: int = 8,
    *,
    build_fts_query: Callable[[str], str],
    parse_recall_scope: Callable[[str | None], tuple[str, int | None, int | None]],
    stage_at_least: Callable[[str], bool],
    safe_json_loads: Callable[[str], list[Any]],
) -> list[dict[str, Any]]:
    fts_q = build_fts_query(query)
    if not fts_q:
        return []

    temporal_scope, guild_id, channel_id = parse_recall_scope(scope)

    if temporal_scope == "hot":
        allowed_tiers = (0,)
    elif temporal_scope == "warm":
        allowed_tiers = (0, 1)
    elif temporal_scope == "cold":
        allowed_tiers = (2,)
    else:
        allowed_tiers = (0, 1, 2, 3)

    cur = conn.cursor()
    tier_placeholders = ",".join("?" for _ in allowed_tiers)
    cur.execute(
        f"""
        SELECT me.id, me.created_at_utc, me.created_ts,
               me.channel_id, me.channel_name,
               me.author_id, me.author_name,
               me.source_message_id,
               me.text, me.tags_json, me.importance, me.tier,
               me.topic_id, me.topic_source, me.topic_confidence,

               me.logged_from_channel_id, me.logged_from_channel_name, me.logged_from_message_id,
               me.source_channel_id, me.source_channel_name,

               bm25(memory_events_fts) as rank
        FROM memory_events_fts
        JOIN memory_events me ON me.id = memory_events_fts.rowid
        WHERE memory_events_fts MATCH ?
        AND me.tier IN ({tier_placeholders})
        AND (? IS NULL OR me.channel_id = ?)
        AND (? IS NULL OR me.guild_id = ?)
        LIMIT 60
        """,
        (fts_q, *allowed_tiers, channel_id, channel_id, guild_id, guild_id),
    )
    rows = cur.fetchall()

    scored: list[tuple[float, dict[str, Any]]] = []
    now = int(time.time())

    for (
        mid,
        created_at_utc,
        created_ts,
        row_channel_id,
        channel_name,
        author_id,
        author_name,
        source_message_id,
        text,
        tags_json,
        importance,
        tier,
        topic_id,
        topic_source,
        topic_confidence,
        logged_from_channel_id,
        logged_from_channel_name,
        logged_from_message_id,
        source_channel_id,
        source_channel_name,
        rank,
    ) in rows:
        tier = int(tier or 1)
        if tier not in allowed_tiers:
            continue

        importance = int(importance or 0)
        if stage_at_least("M1") and not stage_at_least("M2"):
            if importance == 0 and (now - int(created_ts or 0)) > 14 * 86400:
                continue
        if stage_at_least("M2"):
            if importance == 0 and tier >= 3:
                continue

        base = -float(rank or 0.0)
        if tier == 0:
            recency_boost = 2.0
        elif tier == 1:
            recency_boost = 1.0
        elif tier == 2:
            recency_boost = 0.25
        else:
            recency_boost = 0.0

        importance_boost = 2.0 if importance == 1 else 0.0
        score = base + recency_boost + importance_boost

        scored.append(
            (
                score,
                {
                    "id": int(mid),
                    "created_at_utc": created_at_utc,
                    "created_ts": int(created_ts or 0),
                    "channel_id": row_channel_id,
                    "channel_name": channel_name,
                    "author_id": author_id,
                    "author_name": author_name,
                    "source_message_id": source_message_id,
                    "text": text,
                    "tags": safe_json_loads(tags_json),
                    "importance": importance,
                    "tier": tier,
                    "topic_id": topic_id,
                    "topic_source": topic_source,
                    "topic_confidence": topic_confidence,
                    "logged_from_channel_id": logged_from_channel_id,
                    "logged_from_channel_name": logged_from_channel_name,
                    "logged_from_message_id": logged_from_message_id,
                    "source_channel_id": source_channel_id,
                    "source_channel_name": source_channel_name,
                },
            )
        )

    scored.sort(key=lambda x: x[0], reverse=True)
    return [d for _, d in scored[:limit]]


def search_memory_summaries_sync(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 3,
    *,
    build_fts_query: Callable[[str], str],
    safe_json_loads: Callable[[str], list[Any]],
) -> list[dict[str, Any]]:
    fts_q = build_fts_query(query)
    if not fts_q:
        return []
    cur = conn.cursor()
    cur.execute(
        """
        SELECT ms.id, ms.topic_id, ms.updated_at_utc, ms.start_ts, ms.end_ts, ms.tags_json, ms.importance, ms.summary_text,
               bm25(memory_summaries_fts) as rank
        FROM memory_summaries_fts
        JOIN memory_summaries ms ON ms.id = memory_summaries_fts.rowid
        WHERE memory_summaries_fts MATCH ?
        LIMIT 20
        """,
        (fts_q,),
    )
    rows = cur.fetchall()
    out = []
    for (sid, topic_id, updated_at_utc, start_ts, end_ts, tags_json, importance, summary_text, rank) in rows:
        out.append(
            {
                "id": int(sid),
                "topic_id": topic_id,
                "updated_at_utc": updated_at_utc,
                "start_ts": int(start_ts or 0),
                "end_ts": int(end_ts or 0),
                "tags": safe_json_loads(tags_json),
                "importance": int(importance or 1),
                "summary_text": summary_text,
                "rank": float(rank or 0.0),
            }
        )
    out.sort(key=lambda d: d["rank"])
    return out[:limit]


def cleanup_memory_sync(
    conn: sqlite3.Connection,
    *,
    stage_at_least: Callable[[str], bool],
) -> tuple[int, int]:
    cur = conn.cursor()
    now = int(time.time())
    events_deleted = 0
    summaries_deleted = 0

    cur.execute(
        """
        UPDATE memory_events
        SET tier = CASE
            WHEN (? - created_ts) < 86400 THEN 0
            WHEN (? - created_ts) < 14*86400 THEN 1
            WHEN (? - created_ts) < 90*86400 THEN 2
            ELSE 3
        END
        """,
        (now, now, now),
    )

    if stage_at_least("M1") and not stage_at_least("M2"):
        cur.execute("DELETE FROM memory_events WHERE importance=0 AND created_ts < ?", (now - 14 * 86400,))
        events_deleted += cur.rowcount
    elif stage_at_least("M2"):
        cur.execute("DELETE FROM memory_events WHERE importance=0 AND created_ts < ?", (now - 90 * 86400,))
        events_deleted += cur.rowcount

    cur.execute("DELETE FROM memory_events_fts WHERE rowid NOT IN (SELECT id FROM memory_events)")
    cur.execute("DELETE FROM memory_summaries_fts WHERE rowid NOT IN (SELECT id FROM memory_summaries)")
    conn.commit()
    return events_deleted, summaries_deleted


def fetch_topic_events_sync(
    conn: sqlite3.Connection,
    topic_id: str,
    min_age_days: int = 14,
    max_events: int = 200,
    *,
    safe_json_loads: Callable[[str], list[Any]],
) -> list[dict[str, Any]]:
    topic_id = (topic_id or "").strip().lower()
    if not topic_id:
        return []
    cur = conn.cursor()
    cutoff = int(time.time()) - int(min_age_days) * 86400
    like_pat = f'%"{topic_id}"%'

    cur.execute(
        """
        SELECT id, created_at_utc, created_ts, channel_name, author_name, text, tags_json
        FROM memory_events
        WHERE importance = 1
          AND summarized = 0
          AND created_ts < ?
          AND (
                (topic_id IS NOT NULL AND topic_id = ?)
                OR (tags_json LIKE ?)
              )
        ORDER BY created_ts ASC
        LIMIT ?
        """,
        (cutoff, topic_id, like_pat, int(max_events)),
    )
    rows = cur.fetchall()
    out = []
    for (eid, created_at_utc, created_ts, channel_name, author_name, text, tags_json) in rows:
        out.append(
            {
                "id": int(eid),
                "created_at_utc": created_at_utc,
                "created_ts": int(created_ts or 0),
                "channel_name": channel_name,
                "author_name": author_name,
                "text": text,
                "tags": safe_json_loads(tags_json),
            }
        )
    return out


def get_topic_summary_sync(
    conn: sqlite3.Connection,
    topic_id: str,
    *,
    safe_json_loads: Callable[[str], list[Any]],
) -> dict[str, Any] | None:
    topic_id = (topic_id or "").strip().lower()
    if not topic_id:
        return None
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, topic_id, updated_at_utc, start_ts, end_ts, tags_json, importance, summary_text
        FROM memory_summaries
        WHERE topic_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (topic_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    sid, found_topic_id, updated_at_utc, start_ts, end_ts, tags_json, importance, summary_text = row
    return {
        "id": int(sid),
        "topic_id": found_topic_id,
        "updated_at_utc": updated_at_utc,
        "start_ts": int(start_ts or 0),
        "end_ts": int(end_ts or 0),
        "tags": safe_json_loads(tags_json),
        "importance": int(importance or 1),
        "summary_text": summary_text,
    }


def fetch_latest_memory_events_sync(
    conn: sqlite3.Connection,
    limit: int,
) -> list[tuple[str, str, str, str]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT created_at_utc, author_name, COALESCE(channel_name,''), text
        FROM memory_events
        WHERE text IS NOT NULL AND TRIM(text) != ''
        ORDER BY id DESC
        LIMIT ?
        """,
        (int(limit),),
    )
    return cur.fetchall()


def fetch_memory_events_since_sync(
    conn: sqlite3.Connection,
    since_iso_utc: str,
    limit: int,
) -> list[tuple[str, str, str, str]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT created_at_utc, author_name, COALESCE(channel_name,''), text
        FROM memory_events
        WHERE created_at_utc >= ?
          AND text IS NOT NULL AND TRIM(text) != ''
        ORDER BY id DESC
        LIMIT ?
        """,
        (since_iso_utc, int(limit)),
    )
    return cur.fetchall()


def set_memory_origin_sync(
    conn: sqlite3.Connection,
    mem_id: int,
    source_channel_id: int | None,
    source_channel_name: str | None,
) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE memory_events
        SET source_channel_id = ?,
            source_channel_name = ?
        WHERE id = ?
        """,
        (source_channel_id, source_channel_name, int(mem_id)),
    )
    conn.commit()


def list_known_topics_sync(conn: sqlite3.Connection, limit: int = 200) -> list[str]:
    cur = conn.cursor()
    topics: set[str] = set()
    try:
        cur.execute(
            "SELECT DISTINCT topic_id FROM memory_events WHERE topic_id IS NOT NULL AND topic_id != '' LIMIT ?",
            (int(limit),),
        )
        for (topic_id,) in cur.fetchall():
            if topic_id:
                topics.add(str(topic_id).strip().lower())
    except Exception:
        pass
    try:
        cur.execute(
            "SELECT DISTINCT topic_id FROM memory_summaries WHERE topic_id IS NOT NULL AND topic_id != '' LIMIT ?",
            (int(limit),),
        )
        for (topic_id,) in cur.fetchall():
            if topic_id:
                topics.add(str(topic_id).strip().lower())
    except Exception:
        pass

    out = [topic_id for topic_id in topics if re.fullmatch(r"[a-z0-9_\-]{3,}", topic_id)]
    out.sort()
    return out[: int(limit)]


def topic_counts_sync(conn: sqlite3.Connection, limit: int = 15) -> list[tuple[str, int]]:
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT topic_id, COUNT(*) as n
            FROM memory_events
            WHERE topic_id IS NOT NULL AND topic_id != ''
            GROUP BY topic_id
            ORDER BY n DESC
            LIMIT ?
            """,
            (int(limit),),
        )
        rows = cur.fetchall()
        return [(str(topic_id), int(count)) for (topic_id, count) in rows if topic_id]
    except Exception:
        return []
