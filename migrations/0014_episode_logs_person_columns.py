from __future__ import annotations

import re
import sqlite3


SNOWFLAKE_RE = re.compile(r"^[0-9]{15,22}$")


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    return any(str(row[1]) == column for row in cur.fetchall())


def _canonical_person_id(conn: sqlite3.Connection, person_id: int, *, max_hops: int = 32) -> int:
    start = int(person_id)
    current = start
    seen: set[int] = {start}
    cur = conn.cursor()
    hops = 0
    while hops < max_hops:
        cur.execute("SELECT merged_into_person_id FROM people WHERE id = ? LIMIT 1", (int(current),))
        row = cur.fetchone()
        if not row:
            return int(current)
        nxt = row[0]
        if nxt is None:
            return int(current)
        next_id = int(nxt)
        if next_id in seen:
            print(f"[Migration 0014] canonicalization cycle for person_id={start}; returning start.")
            return int(start)
        seen.add(next_id)
        current = next_id
        hops += 1
    print(f"[Migration 0014] canonicalization hop guard hit for person_id={start}; returning current={current}.")
    return int(current)


def _resolve_person_id(conn: sqlite3.Connection, discord_external_id: str) -> int | None:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT person_id
        FROM person_identifiers
        WHERE platform='discord'
          AND external_id=?
          AND revoked_at IS NULL
        ORDER BY id ASC
        LIMIT 1
        """,
        (discord_external_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return _canonical_person_id(conn, int(row[0]))


def upgrade(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='episode_logs' LIMIT 1")
    if cur.fetchone() is None:
        return
    if not _has_column(conn, "episode_logs", "person_id"):
        cur.execute("ALTER TABLE episode_logs ADD COLUMN person_id INTEGER")
    if not _has_column(conn, "episode_logs", "target_person_id"):
        cur.execute("ALTER TABLE episode_logs ADD COLUMN target_person_id INTEGER")

    cur.execute(
        """
        SELECT id, user_id, person_id, target_user_id, target_person_id
        FROM episode_logs
        ORDER BY id ASC
        """
    )
    rows = cur.fetchall()
    for row_id, user_id, person_id, target_user_id, target_person_id in rows:
        updates: list[tuple[str, int]] = []
        if person_id is None and user_id is not None:
            uid = str(user_id).strip()
            if SNOWFLAKE_RE.fullmatch(uid):
                resolved = _resolve_person_id(conn, uid)
                if resolved is not None:
                    updates.append(("person_id", int(resolved)))

        if target_person_id is None and target_user_id is not None:
            tuid = str(target_user_id).strip()
            if SNOWFLAKE_RE.fullmatch(tuid):
                resolved_target = _resolve_person_id(conn, tuid)
                if resolved_target is not None:
                    updates.append(("target_person_id", int(resolved_target)))

        if updates:
            set_sql = ", ".join(f"{col}=?" for col, _ in updates)
            params = [int(value) for _, value in updates] + [int(row_id)]
            cur.execute(f"UPDATE episode_logs SET {set_sql} WHERE id = ?", params)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_episode_logs_person_id ON episode_logs(person_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_episode_logs_target_person_id ON episode_logs(target_person_id)")
    conn.commit()
