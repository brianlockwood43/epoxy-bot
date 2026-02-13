from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def upgrade(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    now = _utc_now_iso()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS meta_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            name TEXT,
            statement TEXT,
            priority TEXT DEFAULT 'medium',
            applies_to TEXT,
            scope TEXT DEFAULT 'global',
            evidence_json TEXT DEFAULT '[]',
            confidence REAL DEFAULT 0.6,
            stability TEXT DEFAULT 'medium',
            lifecycle TEXT DEFAULT 'active',
            conflict_resolution_rule TEXT,
            signals_json TEXT DEFAULT '[]',
            implications_json TEXT DEFAULT '[]',
            created_at_utc TEXT,
            updated_at_utc TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_ref TEXT NOT NULL,
            to_ref TEXT NOT NULL,
            relation TEXT NOT NULL,
            weight REAL DEFAULT 1.0,
            confidence REAL DEFAULT 0.6,
            created_by TEXT DEFAULT 'system',
            lifecycle TEXT DEFAULT 'active',
            created_at_utc TEXT,
            updated_at_utc TEXT
        )
        """
    )

    cur.execute("CREATE INDEX IF NOT EXISTS idx_meta_items_kind ON meta_items(kind)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_meta_items_scope ON meta_items(scope)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_meta_items_lifecycle ON meta_items(lifecycle)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_meta_items_priority ON meta_items(priority)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_links_from_ref ON memory_links(from_ref)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_links_to_ref ON memory_links(to_ref)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_links_relation ON memory_links(relation)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_links_lifecycle ON memory_links(lifecycle)")

    seed_policies = [
        (
            "policy:member_privacy",
            "Do not reveal private information about other members in member-facing contexts.",
            "critical",
            "controller",
            "no_cross_member_private_disclosure;redact_discord_mentions_in_member_context",
        ),
        (
            "policy:public_safe",
            "In public channels, keep responses privacy-safe and avoid exposing member-specific private details.",
            "critical",
            "controller",
            "no_cross_member_private_disclosure;redact_discord_mentions_in_member_context",
        ),
        (
            "policy:dm_privacy",
            "In direct messages, use only context-appropriate memory and avoid cross-member disclosure unless explicitly authorized.",
            "high",
            "controller",
            "no_cross_member_private_disclosure",
        ),
        (
            "policy:staff_confidential",
            "Staff channels may discuss operational context, but member-private details should remain need-to-know.",
            "high",
            "controller",
            "no_cross_member_private_disclosure",
        ),
        (
            "policy:leadership_confidential",
            "Leadership contexts can include cross-member analysis when necessary, while preserving auditability and discretion.",
            "high",
            "controller",
            "",
        ),
        (
            "policy:default",
            "When context is ambiguous, prioritize privacy and conservative disclosure.",
            "high",
            "controller",
            "no_cross_member_private_disclosure",
        ),
    ]

    for scope, statement, priority, applies_to, conflict_rule in seed_policies:
        cur.execute(
            """
            SELECT id
            FROM meta_items
            WHERE kind='policy'
              AND COALESCE(scope, 'global') = ?
              AND COALESCE(statement, '') = ?
            LIMIT 1
            """,
            (scope, statement),
        )
        row = cur.fetchone()
        if row:
            cur.execute(
                """
                UPDATE meta_items
                SET priority = ?,
                    applies_to = ?,
                    conflict_resolution_rule = ?,
                    lifecycle = 'active',
                    updated_at_utc = ?
                WHERE id = ?
                """,
                (priority, applies_to, conflict_rule, now, int(row[0])),
            )
            continue

        cur.execute(
            """
            INSERT INTO meta_items (
                kind, name, statement, priority, applies_to, scope,
                lifecycle, conflict_resolution_rule, created_at_utc, updated_at_utc
            ) VALUES (
                'policy', ?, ?, ?, ?, ?, 'active', ?, ?, ?
            )
            """,
            (scope, statement, priority, applies_to, scope, conflict_rule, now, now),
        )

    conn.commit()
