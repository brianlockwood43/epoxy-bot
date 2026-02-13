from __future__ import annotations

import os
import sqlite3
import unittest

from db.migrate import apply_sqlite_migrations
from memory.store import search_memory_events_sync
from retrieval.fts_query import build_fts_query


def _stage_at_least(_stage: str) -> bool:
    return True


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


class MemoryScopeFilterTests(unittest.TestCase):
    def test_channel_scoped_event_recall_blocks_cross_channel(self):
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        apply_sqlite_migrations(conn, os.path.join(os.getcwd(), "migrations"))
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO memory_events (
                created_at_utc, created_ts, scope, guild_id, channel_id, text, tags_json, importance, tier, lifecycle
            ) VALUES ('2026-02-13T00:00:00+00:00', 1, 'channel:100', 1, 100, 'scope check payload', '[]', 1, 0, 'active')
            """
        )
        id_allowed = int(cur.lastrowid)
        cur.execute(
            "INSERT INTO memory_events_fts(rowid, text, tags) VALUES (?, ?, '')",
            (id_allowed, "scope check payload"),
        )

        cur.execute(
            """
            INSERT INTO memory_events (
                created_at_utc, created_ts, scope, guild_id, channel_id, text, tags_json, importance, tier, lifecycle
            ) VALUES ('2026-02-13T00:00:00+00:00', 1, 'channel:200', 1, 200, 'scope check payload', '[]', 1, 0, 'active')
            """
        )
        id_blocked = int(cur.lastrowid)
        cur.execute(
            "INSERT INTO memory_events_fts(rowid, text, tags) VALUES (?, ?, '')",
            (id_blocked, "scope check payload"),
        )

        cur.execute(
            """
            INSERT INTO memory_events (
                created_at_utc, created_ts, scope, guild_id, channel_id, text, tags_json, importance, tier, lifecycle
            ) VALUES ('2026-02-13T00:00:00+00:00', 1, 'channel:100', 1, 100, 'scope check payload', '[]', 1, 0, 'archived')
            """
        )
        id_archived = int(cur.lastrowid)
        cur.execute(
            "INSERT INTO memory_events_fts(rowid, text, tags) VALUES (?, ?, '')",
            (id_archived, "scope check payload"),
        )

        conn.commit()

        rows = search_memory_events_sync(
            conn,
            "scope check payload",
            "auto channel:100 guild:1",
            limit=10,
            build_fts_query=build_fts_query,
            parse_recall_scope=_parse_recall_scope,
            stage_at_least=_stage_at_least,
            safe_json_loads=lambda _s: [],
        )
        ids = {int(row["id"]) for row in rows}
        self.assertIn(id_allowed, ids)
        self.assertNotIn(id_blocked, ids)
        self.assertNotIn(id_archived, ids)
        conn.close()

    def test_hot_scope_preserves_tier_zero_events(self):
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        apply_sqlite_migrations(conn, os.path.join(os.getcwd(), "migrations"))
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO memory_events (
                created_at_utc, created_ts, scope, guild_id, channel_id, text, tags_json, importance, tier, lifecycle
            ) VALUES ('2026-02-13T00:00:00+00:00', 1, 'channel:100', 1, 100, 'hot tier payload', '[]', 1, 0, 'active')
            """
        )
        hot_id = int(cur.lastrowid)
        cur.execute("INSERT INTO memory_events_fts(rowid, text, tags) VALUES (?, ?, '')", (hot_id, "hot tier payload"))

        cur.execute(
            """
            INSERT INTO memory_events (
                created_at_utc, created_ts, scope, guild_id, channel_id, text, tags_json, importance, tier, lifecycle
            ) VALUES ('2026-02-13T00:00:00+00:00', 1, 'channel:100', 1, 100, 'hot tier payload', '[]', 1, 1, 'active')
            """
        )
        warm_id = int(cur.lastrowid)
        cur.execute("INSERT INTO memory_events_fts(rowid, text, tags) VALUES (?, ?, '')", (warm_id, "hot tier payload"))
        conn.commit()

        rows = search_memory_events_sync(
            conn,
            "hot tier payload",
            "hot channel:100 guild:1",
            limit=10,
            build_fts_query=build_fts_query,
            parse_recall_scope=_parse_recall_scope,
            stage_at_least=_stage_at_least,
            safe_json_loads=lambda _s: [],
        )
        ids = {int(row["id"]) for row in rows}
        self.assertIn(hot_id, ids)
        self.assertNotIn(warm_id, ids)
        conn.close()


if __name__ == "__main__":
    unittest.main()
