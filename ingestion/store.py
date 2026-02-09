from __future__ import annotations

import sqlite3


def insert_message_sync(conn: sqlite3.Connection, payload: dict) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR IGNORE INTO messages (
            message_id, guild_id, guild_name,
            channel_id, channel_name,
            author_id, author_name,
            created_at_utc, content, attachments
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload["message_id"],
            payload["guild_id"],
            payload["guild_name"],
            payload["channel_id"],
            payload["channel_name"],
            payload["author_id"],
            payload["author_name"],
            payload["created_at_utc"],
            payload["content"],
            payload["attachments"],
        ),
    )
    conn.commit()


def fetch_last_messages_by_author_sync(
    conn: sqlite3.Connection,
    channel_id: int,
    before_message_id: int,
    author_name_like: str,
    limit: int = 1,
) -> list[tuple[str, str, str]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT created_at_utc, author_name, content
        FROM messages
        WHERE channel_id = ?
          AND message_id < ?
          AND author_name LIKE ?
          AND content IS NOT NULL
          AND TRIM(content) != ''
        ORDER BY message_id DESC
        LIMIT ?
        """,
        (channel_id, before_message_id, author_name_like, limit),
    )
    return cur.fetchall()


def get_backfill_done_sync(conn: sqlite3.Connection, channel_id: int) -> tuple[bool, str | None]:
    cur = conn.cursor()
    cur.execute(
        "SELECT backfill_done, last_backfill_at_utc FROM channel_state WHERE channel_id = ? LIMIT 1",
        (int(channel_id),),
    )
    row = cur.fetchone()
    if not row:
        return (False, None)
    return (int(row[0]) == 1, row[1])


def set_backfill_done_sync(conn: sqlite3.Connection, channel_id: int, iso_utc: str) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO channel_state (channel_id, backfill_done, last_backfill_at_utc)
        VALUES (?, 1, ?)
        ON CONFLICT(channel_id) DO UPDATE SET
            backfill_done=1,
            last_backfill_at_utc=excluded.last_backfill_at_utc
        """,
        (channel_id, iso_utc),
    )
    conn.commit()


def reset_all_backfill_done_sync(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute("UPDATE channel_state SET backfill_done = 0, last_backfill_at_utc = NULL")
    conn.commit()


def reset_backfill_done_sync(conn: sqlite3.Connection, channel_id: int) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE channel_state
        SET backfill_done = 0,
            last_backfill_at_utc = NULL
        WHERE channel_id = ?
        """,
        (int(channel_id),),
    )
    conn.commit()


def fetch_recent_context_sync(
    conn: sqlite3.Connection,
    channel_id: int,
    before_message_id: int,
    limit: int,
) -> list[tuple[str, str, str]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT created_at_utc, author_name, content
        FROM messages
        WHERE channel_id = ?
          AND message_id < ?
          AND content IS NOT NULL
          AND TRIM(content) != ''
        ORDER BY message_id DESC
        LIMIT ?
        """,
        (channel_id, before_message_id, limit),
    )
    return cur.fetchall()


def fetch_messages_since_sync(
    conn: sqlite3.Connection,
    channel_id: int,
    since_iso_utc: str,
    limit: int,
) -> list[tuple[str, str, str]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT created_at_utc, author_name, content
        FROM messages
        WHERE channel_id = ?
          AND created_at_utc >= ?
          AND content IS NOT NULL
          AND TRIM(content) != ''
        ORDER BY message_id DESC
        LIMIT ?
        """,
        (int(channel_id), since_iso_utc, int(limit)),
    )
    return cur.fetchall()


def fetch_latest_messages_sync(
    conn: sqlite3.Connection,
    channel_id: int,
    limit: int,
) -> list[tuple[str, str, str]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT created_at_utc, author_name, content
        FROM messages
        WHERE channel_id = ?
          AND content IS NOT NULL
          AND TRIM(content) != ''
        ORDER BY message_id DESC
        LIMIT ?
        """,
        (int(channel_id), int(limit)),
    )
    return cur.fetchall()
