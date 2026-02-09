from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_platform(platform: str) -> str:
    return str(platform or "").strip().lower()


def _normalize_external_id(external_id: str) -> str:
    return str(external_id or "").strip()


def canonical_person_id_sync(conn: sqlite3.Connection, person_id: int, *, max_hops: int = 32) -> int:
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
        merged_into = row[0]
        if merged_into is None:
            return int(current)
        next_id = int(merged_into)
        if next_id in seen:
            print(f"[Identity] canonical_person_id cycle detected at person_id={start}; returning start id.")
            return int(start)
        seen.add(next_id)
        current = next_id
        hops += 1

    print(f"[Identity] canonical_person_id hop guard hit at person_id={start}; returning current={current}.")
    return int(current)


def resolve_person_id_sync(conn: sqlite3.Connection, platform: str, external_id: str) -> int | None:
    plat = _normalize_platform(platform)
    ext = _normalize_external_id(external_id)
    if not plat or not ext:
        return None

    cur = conn.cursor()
    cur.execute(
        """
        SELECT person_id
        FROM person_identifiers
        WHERE platform = ?
          AND external_id = ?
          AND revoked_at IS NULL
        ORDER BY id ASC
        LIMIT 1
        """,
        (plat, ext),
    )
    row = cur.fetchone()
    if not row:
        return None
    return int(canonical_person_id_sync(conn, int(row[0])))


def get_or_create_person_sync(
    conn: sqlite3.Connection,
    *,
    platform: str,
    external_id: str,
    origin: str,
    label: str | None = None,
) -> int:
    plat = _normalize_platform(platform)
    ext = _normalize_external_id(external_id)
    src = str(origin or "").strip()
    if not plat:
        raise ValueError("platform is required")
    if not ext:
        raise ValueError("external_id is required")
    now = _utc_now_iso()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, person_id
        FROM person_identifiers
        WHERE platform = ?
          AND external_id = ?
          AND revoked_at IS NULL
        ORDER BY id ASC
        """,
        (plat, ext),
    )
    active_rows = cur.fetchall()
    if active_rows:
        if len(active_rows) != 1:
            print(
                f"[Identity] active identifier cardinality mismatch for {plat}:{ext}; "
                f"expected=1 actual={len(active_rows)}"
            )
        chosen_identifier_id = int(active_rows[0][0])
        chosen_person_id = int(active_rows[0][1])
        cur.execute(
            """
            UPDATE person_identifiers
            SET last_seen_at = ?
            WHERE platform = ?
              AND external_id = ?
              AND revoked_at IS NULL
            """,
            (now, plat, ext),
        )
        # Ensure chosen row gets touched even in odd data states.
        cur.execute(
            "UPDATE person_identifiers SET last_seen_at = ? WHERE id = ?",
            (now, chosen_identifier_id),
        )
        conn.commit()
        return int(canonical_person_id_sync(conn, chosen_person_id))

    try:
        cur.execute(
            """
            INSERT INTO people (created_at, origin, status, merged_into_person_id)
            VALUES (?, ?, 'active', NULL)
            """,
            (now, src),
        )
        person_id = int(cur.lastrowid)
        cur.execute(
            """
            INSERT INTO person_identifiers (
                person_id, platform, external_id, label, strength, created_at, last_seen_at, revoked_at
            ) VALUES (?, ?, ?, ?, 'primary', ?, ?, NULL)
            """,
            (int(person_id), plat, ext, (str(label).strip() if label is not None else None), now, now),
        )
        conn.commit()
        return int(person_id)
    except sqlite3.IntegrityError:
        conn.rollback()
        resolved = resolve_person_id_sync(conn, plat, ext)
        if resolved is None:
            raise
        return int(resolved)


def revoke_identifier_sync(
    conn: sqlite3.Connection,
    *,
    platform: str,
    external_id: str,
    reason: str | None = None,
) -> None:
    plat = _normalize_platform(platform)
    ext = _normalize_external_id(external_id)
    if not plat or not ext:
        return
    _ = reason  # reserved for future audit logging
    now = _utc_now_iso()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE person_identifiers
        SET revoked_at = ?, last_seen_at = ?
        WHERE platform = ?
          AND external_id = ?
          AND revoked_at IS NULL
        """,
        (now, now, plat, ext),
    )
    changed = int(cur.rowcount or 0)
    conn.commit()
    if changed != 1:
        print(
            f"[Identity] revoke_identifier cardinality mismatch for {plat}:{ext}; "
            f"expected=1 actual={changed}"
        )


def touch_person_seen_sync(
    conn: sqlite3.Connection,
    *,
    person_id: int,
    platform: str | None = None,
    external_id: str | None = None,
) -> None:
    now = _utc_now_iso()
    canonical_id = int(canonical_person_id_sync(conn, int(person_id)))
    cur = conn.cursor()

    if platform is not None and external_id is not None:
        cur.execute(
            """
            UPDATE person_identifiers
            SET last_seen_at = ?
            WHERE person_id = ?
              AND platform = ?
              AND external_id = ?
              AND revoked_at IS NULL
            """,
            (now, canonical_id, _normalize_platform(platform), _normalize_external_id(external_id)),
        )
    elif platform is not None:
        cur.execute(
            """
            UPDATE person_identifiers
            SET last_seen_at = ?
            WHERE person_id = ?
              AND platform = ?
              AND revoked_at IS NULL
            """,
            (now, canonical_id, _normalize_platform(platform)),
        )
    else:
        cur.execute(
            """
            UPDATE person_identifiers
            SET last_seen_at = ?
            WHERE person_id = ?
              AND revoked_at IS NULL
            """,
            (now, canonical_id),
        )
    conn.commit()


def dedupe_memory_events_by_id(events: list[dict[str, Any]], *, limit: int | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for event in events or []:
        if not isinstance(event, dict):
            continue
        memory_id_raw = event.get("id")
        if memory_id_raw is None:
            continue
        try:
            memory_id = int(memory_id_raw)
        except Exception:
            continue
        if memory_id in seen:
            continue
        seen.add(memory_id)
        out.append(event)
        if limit is not None and len(out) >= int(limit):
            break
    return out


def list_person_facts_sync(conn: sqlite3.Connection, person_id: int) -> list[dict[str, Any]]:
    _ = conn
    _ = person_id
    # Deferred in M3.1: person_facts table/pipeline are intentionally not implemented yet.
    return []
