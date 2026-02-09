from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    return [str(row[1]) for row in cur.fetchall()]


def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (table,))
    return cur.fetchone() is not None


def _get_or_create_person_for_discord(conn: sqlite3.Connection, discord_id: str, *, seen_ts: str, now: str) -> int:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, person_id
        FROM person_identifiers
        WHERE platform='discord'
          AND external_id=?
          AND revoked_at IS NULL
        ORDER BY id ASC
        """,
        (discord_id,),
    )
    rows = cur.fetchall()
    if rows:
        if len(rows) != 1:
            print(
                f"[Migration 0013] active identifier cardinality mismatch for discord:{discord_id}; "
                f"expected=1 actual={len(rows)}"
            )
        person_id = int(rows[0][1])
        cur.execute(
            """
            UPDATE person_identifiers
            SET last_seen_at=?
            WHERE platform='discord'
              AND external_id=?
              AND revoked_at IS NULL
            """,
            (seen_ts, discord_id),
        )
        return person_id

    cur.execute(
        """
        INSERT INTO people (created_at, origin, status, merged_into_person_id)
        VALUES (?, ?, 'active', NULL)
        """,
        (now, "discord:migration_0013"),
    )
    person_id = int(cur.lastrowid)
    cur.execute(
        """
        INSERT INTO person_identifiers (
            person_id, platform, external_id, label, strength, created_at, last_seen_at, revoked_at
        ) VALUES (?, 'discord', ?, 'discord_user_id', 'primary', ?, ?, NULL)
        """,
        (person_id, discord_id, now, seen_ts),
    )
    return person_id


def upgrade(conn: sqlite3.Connection) -> None:
    if not _has_table(conn, "user_profiles"):
        return

    cols = _table_columns(conn, "user_profiles")
    if "person_id" in cols and "id" not in cols:
        # Already migrated schema shape.
        return
    if "id" not in cols:
        return

    cur = conn.cursor()
    now = _utc_now_iso()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_profiles_new (
            person_id INTEGER PRIMARY KEY,
            layer_estimate TEXT DEFAULT 'unknown',
            risk_flags_json TEXT DEFAULT '[]',
            preferred_tone TEXT,
            dev_arc_meta_ids_json TEXT DEFAULT '[]',
            last_seen_at_utc TEXT
        )
        """
    )

    cur.execute(
        """
        SELECT id, layer_estimate, risk_flags_json, preferred_tone, dev_arc_meta_ids_json, last_seen_at_utc
        FROM user_profiles
        ORDER BY id ASC
        """
    )
    rows = cur.fetchall()
    for row in rows:
        legacy_id = row[0]
        layer_estimate = row[1]
        risk_flags_json = row[2]
        preferred_tone = row[3]
        dev_arc_meta_ids_json = row[4]
        old_seen = row[5]
        seen_ts = old_seen or now
        legacy_external = str(legacy_id).strip()
        if not legacy_external:
            print("[Migration 0013] skipping empty legacy user_profiles.id value")
            continue
        person_id = _get_or_create_person_for_discord(conn, legacy_external, seen_ts=seen_ts, now=now)

        cur.execute(
            """
            INSERT INTO user_profiles_new (
                person_id, layer_estimate, risk_flags_json, preferred_tone, dev_arc_meta_ids_json, last_seen_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(person_id) DO UPDATE SET
                layer_estimate=excluded.layer_estimate,
                risk_flags_json=excluded.risk_flags_json,
                preferred_tone=excluded.preferred_tone,
                dev_arc_meta_ids_json=excluded.dev_arc_meta_ids_json,
                last_seen_at_utc=excluded.last_seen_at_utc
            """,
            (
                int(person_id),
                layer_estimate or "unknown",
                risk_flags_json or "[]",
                preferred_tone,
                dev_arc_meta_ids_json or "[]",
                seen_ts,
            ),
        )

    cur.execute("DROP TABLE user_profiles")
    cur.execute("ALTER TABLE user_profiles_new RENAME TO user_profiles")
    conn.commit()
