from __future__ import annotations

import os
import sqlite3
import time
import unittest

from db.migrate import apply_sqlite_migrations
from memory.store import cleanup_memory_sync
from memory.store import fetch_topic_events_sync


def _stage_checker(current_stage: str):
    ranks = {"M0": 0, "M1": 1, "M2": 2, "M3": 3}
    current = ranks.get((current_stage or "M0").upper(), 0)

    def _stage_at_least(stage: str) -> bool:
        return current >= ranks.get((stage or "M0").upper(), 0)

    return _stage_at_least


def _parse_recall_scope(scope: str | None) -> tuple[str, int | None, int | None]:
    text = (scope or "auto").strip().lower()
    temporal = "auto"
    guild_id: int | None = None
    channel_id: int | None = None
    for tok in text.split():
        if tok in {"hot", "warm", "cold", "auto"}:
            temporal = tok
        elif tok.startswith("channel:"):
            try:
                channel_id = int(tok.split(":", 1)[1])
            except Exception:
                channel_id = None
        elif tok.startswith("guild:"):
            try:
                guild_id = int(tok.split(":", 1)[1])
            except Exception:
                guild_id = None
    return temporal, guild_id, channel_id


class MemoryLifecycleCleanupTests(unittest.TestCase):
    def test_cleanup_archives_old_low_importance_without_delete(self):
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        apply_sqlite_migrations(conn, os.path.join(os.getcwd(), "migrations"))
        cur = conn.cursor()
        now = int(time.time())

        cur.execute(
            """
            INSERT INTO memory_events (
                created_at_utc, created_ts, lifecycle, importance, tier, text, tags_json
            ) VALUES ('2025-01-01T00:00:00+00:00', ?, 'active', 0, 1, 'old low importance', '[]')
            """,
            (now - 120 * 86400,),
        )
        low_id = int(cur.lastrowid)

        cur.execute(
            """
            INSERT INTO memory_events (
                created_at_utc, created_ts, lifecycle, importance, tier, text, tags_json
            ) VALUES ('2025-01-01T00:00:00+00:00', ?, 'active', 1, 1, 'old high importance', '[]')
            """,
            (now - 120 * 86400,),
        )
        high_id = int(cur.lastrowid)
        conn.commit()

        cur.execute("SELECT COUNT(*) FROM memory_events")
        before_count = int(cur.fetchone()[0])

        transitioned_events, transitioned_summaries = cleanup_memory_sync(
            conn,
            stage_at_least=_stage_checker("M2"),
        )

        self.assertGreaterEqual(transitioned_events, 1)
        self.assertEqual(transitioned_summaries, 0)

        cur.execute("SELECT COUNT(*) FROM memory_events")
        after_count = int(cur.fetchone()[0])
        self.assertEqual(before_count, after_count)

        cur.execute("SELECT lifecycle, tier FROM memory_events WHERE id=?", (low_id,))
        low_lifecycle, low_tier = cur.fetchone()
        self.assertEqual(low_lifecycle, "archived")
        self.assertEqual(int(low_tier), 3)

        cur.execute("SELECT lifecycle, tier FROM memory_events WHERE id=?", (high_id,))
        high_lifecycle, high_tier = cur.fetchone()
        self.assertEqual(high_lifecycle, "active")
        self.assertEqual(int(high_tier), 3)
        conn.close()

    def test_cleanup_deprecates_expired_event(self):
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        apply_sqlite_migrations(conn, os.path.join(os.getcwd(), "migrations"))
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO memory_events (
                created_at_utc, created_ts, lifecycle, importance, tier, expiry_at_utc, text, tags_json
            ) VALUES (
                '2026-02-10T00:00:00+00:00', ?, 'active', 1, 0, '2000-01-01T00:00:00+00:00', 'expired memory', '[]'
            )
            """,
            (int(time.time()) - 3600,),
        )
        expired_id = int(cur.lastrowid)
        conn.commit()

        transitioned_events, _ = cleanup_memory_sync(
            conn,
            stage_at_least=_stage_checker("M2"),
        )
        self.assertGreaterEqual(transitioned_events, 1)

        cur.execute("SELECT lifecycle FROM memory_events WHERE id=?", (expired_id,))
        lifecycle = str(cur.fetchone()[0] or "")
        self.assertEqual(lifecycle, "deprecated")
        conn.close()

    def test_fetch_topic_events_excludes_non_active(self):
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        apply_sqlite_migrations(conn, os.path.join(os.getcwd(), "migrations"))
        cur = conn.cursor()
        now = int(time.time())

        cur.execute(
            """
            INSERT INTO memory_events (
                created_at_utc, created_ts, lifecycle, importance, summarized, topic_id, text, tags_json
            ) VALUES ('2025-01-01T00:00:00+00:00', ?, 'active', 1, 0, 'ops', 'active topic event', '["ops"]')
            """,
            (now - 30 * 86400,),
        )
        active_id = int(cur.lastrowid)

        cur.execute(
            """
            INSERT INTO memory_events (
                created_at_utc, created_ts, lifecycle, importance, summarized, topic_id, text, tags_json
            ) VALUES ('2025-01-01T00:00:00+00:00', ?, 'archived', 1, 0, 'ops', 'archived topic event', '["ops"]')
            """,
            (now - 30 * 86400,),
        )
        archived_id = int(cur.lastrowid)
        conn.commit()

        rows = fetch_topic_events_sync(
            conn,
            "ops",
            scope="auto",
            min_age_days=14,
            max_events=20,
            parse_recall_scope=_parse_recall_scope,
            safe_json_loads=lambda s: [],
        )
        found_ids = {int(row["id"]) for row in rows}
        self.assertIn(active_id, found_ids)
        self.assertNotIn(archived_id, found_ids)
        conn.close()


if __name__ == "__main__":
    unittest.main()
