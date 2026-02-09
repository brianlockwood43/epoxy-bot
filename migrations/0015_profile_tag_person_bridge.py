from __future__ import annotations

import json
import sqlite3


BATCH_SIZE = 500
TAG_CAP = 128


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
            print(f"[Migration 0015] canonicalization cycle for person_id={start}; returning start.")
            return int(start)
        seen.add(next_id)
        current = next_id
        hops += 1
    print(f"[Migration 0015] canonicalization hop guard for person_id={start}; returning current={current}.")
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


def _dedupe_keep_order(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        token = str(item or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def upgrade(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='memory_events' LIMIT 1")
    if cur.fetchone() is None:
        return
    cur.execute(
        """
        SELECT id, tags_json
        FROM memory_events
        WHERE tags_json IS NULL
           OR tags_json = ''
           OR tags_json LIKE '%subject:user:%'
        ORDER BY id ASC
        """
    )
    rows = cur.fetchall()

    changed = 0
    for memory_id, tags_json in rows:
        raw = (tags_json or "").strip()
        if not raw:
            tags: list[str] = []
        else:
            try:
                parsed = json.loads(raw)
            except Exception:
                print(f"[Migration 0015] skipping malformed tags_json for memory_events.id={memory_id}")
                continue
            if not isinstance(parsed, list):
                print(f"[Migration 0015] skipping non-list tags_json for memory_events.id={memory_id}")
                continue
            tags = [str(t).strip() for t in parsed if str(t).strip()]

        original = list(tags)
        user_tags = [t for t in tags if t.startswith("subject:user:")]
        if not user_tags:
            continue

        for user_tag in user_tags:
            external_id = user_tag.split(":", 2)[-1].strip()
            if not external_id:
                continue
            person_id = _resolve_person_id(conn, external_id)
            if person_id is None:
                continue
            person_tag = f"subject:person:{int(person_id)}"
            if person_tag in tags:
                continue
            if TAG_CAP is not None and len(tags) >= TAG_CAP:
                # Required future key wins at cap: remove one legacy subject:user:* tag first.
                drop_index = next((i for i, token in enumerate(tags) if token.startswith("subject:user:")), -1)
                if drop_index >= 0:
                    tags.pop(drop_index)
                else:
                    # No removable legacy tag at cap; skip insertion deterministically.
                    continue
            tags.insert(0, person_tag)

        tags = _dedupe_keep_order(tags)
        if tags != original:
            cur.execute("UPDATE memory_events SET tags_json = ? WHERE id = ?", (json.dumps(tags), int(memory_id)))
            changed += 1
            if changed % BATCH_SIZE == 0:
                conn.commit()

    conn.commit()
