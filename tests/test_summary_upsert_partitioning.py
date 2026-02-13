from __future__ import annotations

import os
import sqlite3
import unittest

from db.migrate import apply_sqlite_migrations
from memory.store import get_topic_summary_sync
from memory.store import upsert_summary_sync


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


class SummaryUpsertPartitioningTests(unittest.TestCase):
    def test_upsert_partitioned_by_topic_scope_and_type(self):
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        apply_sqlite_migrations(conn, os.path.join(os.getcwd(), "migrations"))

        p1 = {
            "topic_id": "ops",
            "summary_type": "topic_gist",
            "scope": "channel:100",
            "created_at_utc": "2026-02-13T00:00:00+00:00",
            "updated_at_utc": "2026-02-13T00:00:00+00:00",
            "start_ts": 1,
            "end_ts": 2,
            "tags_json": '["ops"]',
            "importance": 1,
            "summary_text": "summary A",
        }
        sid_100 = upsert_summary_sync(conn, p1, safe_json_loads=lambda _s: [])

        p2 = dict(p1)
        p2["scope"] = "channel:200"
        p2["summary_text"] = "summary B"
        p2["updated_at_utc"] = "2026-02-13T00:01:00+00:00"
        sid_200 = upsert_summary_sync(conn, p2, safe_json_loads=lambda _s: [])

        self.assertNotEqual(sid_100, sid_200)

        p1_update = dict(p1)
        p1_update["summary_text"] = "summary A2"
        p1_update["updated_at_utc"] = "2026-02-13T00:02:00+00:00"
        sid_100_updated = upsert_summary_sync(conn, p1_update, safe_json_loads=lambda _s: [])
        self.assertEqual(sid_100, sid_100_updated)

        cur = conn.cursor()
        cur.execute(
            """
            SELECT COUNT(*)
            FROM memory_summaries
            WHERE topic_id='ops'
              AND summary_type='topic_gist'
              AND COALESCE(lifecycle, 'active')='active'
            """
        )
        self.assertEqual(int(cur.fetchone()[0]), 2)

        s100 = get_topic_summary_sync(
            conn,
            "ops",
            scope="auto channel:100 guild:1",
            summary_type="topic_gist",
            parse_recall_scope=_parse_recall_scope,
            safe_json_loads=lambda _s: [],
        )
        s200 = get_topic_summary_sync(
            conn,
            "ops",
            scope="auto channel:200 guild:1",
            summary_type="topic_gist",
            parse_recall_scope=_parse_recall_scope,
            safe_json_loads=lambda _s: [],
        )
        self.assertIsNotNone(s100)
        self.assertIsNotNone(s200)
        self.assertEqual(s100["summary_text"], "summary A2")
        self.assertEqual(s200["summary_text"], "summary B")
        conn.close()

    def test_topic_summary_prefers_channel_partition_over_guild(self):
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        apply_sqlite_migrations(conn, os.path.join(os.getcwd(), "migrations"))

        upsert_summary_sync(
            conn,
            {
                "topic_id": "ops",
                "summary_type": "topic_gist",
                "scope": "guild:1",
                "created_at_utc": "2026-02-13T00:00:00+00:00",
                "updated_at_utc": "2026-02-13T00:05:00+00:00",
                "start_ts": 1,
                "end_ts": 2,
                "tags_json": '["ops"]',
                "importance": 1,
                "summary_text": "guild summary",
            },
            safe_json_loads=lambda _s: [],
        )
        upsert_summary_sync(
            conn,
            {
                "topic_id": "ops",
                "summary_type": "topic_gist",
                "scope": "channel:100",
                "created_at_utc": "2026-02-13T00:00:00+00:00",
                "updated_at_utc": "2026-02-13T00:01:00+00:00",
                "start_ts": 1,
                "end_ts": 2,
                "tags_json": '["ops"]',
                "importance": 1,
                "summary_text": "channel summary",
            },
            safe_json_loads=lambda _s: [],
        )

        summary = get_topic_summary_sync(
            conn,
            "ops",
            scope="auto channel:100 guild:1",
            summary_type="topic_gist",
            parse_recall_scope=_parse_recall_scope,
            safe_json_loads=lambda _s: [],
        )
        self.assertIsNotNone(summary)
        self.assertEqual(summary["scope"], "channel:100")
        self.assertEqual(summary["summary_text"], "channel summary")
        conn.close()

    def test_active_partition_uniqueness_index_enforced(self):
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        apply_sqlite_migrations(conn, os.path.join(os.getcwd(), "migrations"))
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO memory_summaries (
                topic_id, summary_type, scope, created_at_utc, updated_at_utc,
                start_ts, end_ts, tags_json, importance, summary_text, lifecycle
            ) VALUES (
                'ops', 'topic_gist', 'channel:123',
                '2026-02-13T00:00:00+00:00', '2026-02-13T00:00:00+00:00',
                1, 1, '[]', 1, 'one', 'active'
            )
            """
        )
        conn.commit()

        with self.assertRaises(sqlite3.IntegrityError):
            cur.execute(
                """
                INSERT INTO memory_summaries (
                    topic_id, summary_type, scope, created_at_utc, updated_at_utc,
                    start_ts, end_ts, tags_json, importance, summary_text, lifecycle
                ) VALUES (
                    'ops', 'topic_gist', 'channel:123',
                    '2026-02-13T00:00:00+00:00', '2026-02-13T00:00:00+00:00',
                    1, 1, '[]', 1, 'two', 'active'
                )
                """
            )

        # Historical duplicates are allowed when non-active.
        cur.execute(
            """
            INSERT INTO memory_summaries (
                topic_id, summary_type, scope, created_at_utc, updated_at_utc,
                start_ts, end_ts, tags_json, importance, summary_text, lifecycle
            ) VALUES (
                'ops', 'topic_gist', 'channel:123',
                '2026-02-13T00:00:00+00:00', '2026-02-13T00:00:00+00:00',
                1, 1, '[]', 1, 'legacy', 'deprecated'
            )
            """
        )
        conn.commit()
        conn.close()


if __name__ == "__main__":
    unittest.main()
