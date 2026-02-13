from __future__ import annotations

import os
import sqlite3
import unittest

from db.migrate import apply_sqlite_migrations
from memory.store import search_memory_summaries_sync
from retrieval.fts_query import build_fts_query


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


class SummaryScopeFilterTests(unittest.TestCase):
    def test_summary_recall_honors_scope_and_lifecycle(self):
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        apply_sqlite_migrations(conn, os.path.join(os.getcwd(), "migrations"))
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO memory_summaries (
                topic_id, summary_type, scope, created_at_utc, updated_at_utc,
                start_ts, end_ts, tags_json, importance, summary_text, lifecycle
            ) VALUES (
                'ops', 'topic_gist', 'channel:100', '2026-02-13T00:00:00+00:00', '2026-02-13T00:00:00+00:00',
                1, 1, '[]', 1, 'scope summary payload', 'active'
            )
            """
        )
        id_allowed = int(cur.lastrowid)
        cur.execute(
            "INSERT INTO memory_summaries_fts(rowid, topic_id, summary_text, tags) VALUES (?, ?, ?, '')",
            (id_allowed, "ops", "scope summary payload"),
        )

        cur.execute(
            """
            INSERT INTO memory_summaries (
                topic_id, summary_type, scope, created_at_utc, updated_at_utc,
                start_ts, end_ts, tags_json, importance, summary_text, lifecycle
            ) VALUES (
                'ops', 'topic_gist', 'channel:200', '2026-02-13T00:00:00+00:00', '2026-02-13T00:00:00+00:00',
                1, 1, '[]', 1, 'scope summary payload', 'active'
            )
            """
        )
        id_blocked = int(cur.lastrowid)
        cur.execute(
            "INSERT INTO memory_summaries_fts(rowid, topic_id, summary_text, tags) VALUES (?, ?, ?, '')",
            (id_blocked, "ops", "scope summary payload"),
        )

        cur.execute(
            """
            INSERT INTO memory_summaries (
                topic_id, summary_type, scope, created_at_utc, updated_at_utc,
                start_ts, end_ts, tags_json, importance, summary_text, lifecycle
            ) VALUES (
                'ops', 'topic_gist', 'global', '2026-02-13T00:00:00+00:00', '2026-02-13T00:00:00+00:00',
                1, 1, '[]', 1, 'scope summary payload', 'active'
            )
            """
        )
        id_global = int(cur.lastrowid)
        cur.execute(
            "INSERT INTO memory_summaries_fts(rowid, topic_id, summary_text, tags) VALUES (?, ?, ?, '')",
            (id_global, "ops", "scope summary payload"),
        )

        cur.execute(
            """
            INSERT INTO memory_summaries (
                topic_id, summary_type, scope, created_at_utc, updated_at_utc,
                start_ts, end_ts, tags_json, importance, summary_text, lifecycle
            ) VALUES (
                'ops', 'topic_gist', 'channel:100', '2026-02-13T00:00:00+00:00', '2026-02-13T00:00:00+00:00',
                1, 1, '[]', 1, 'scope summary payload', 'archived'
            )
            """
        )
        id_archived = int(cur.lastrowid)
        cur.execute(
            "INSERT INTO memory_summaries_fts(rowid, topic_id, summary_text, tags) VALUES (?, ?, ?, '')",
            (id_archived, "ops", "scope summary payload"),
        )
        conn.commit()

        scoped_rows = search_memory_summaries_sync(
            conn,
            "scope summary payload",
            "auto channel:100 guild:1",
            limit=10,
            build_fts_query=build_fts_query,
            parse_recall_scope=_parse_recall_scope,
            safe_json_loads=lambda _s: [],
        )
        scoped_ids = {int(row["id"]) for row in scoped_rows}
        self.assertIn(id_allowed, scoped_ids)
        self.assertNotIn(id_blocked, scoped_ids)
        self.assertNotIn(id_global, scoped_ids)
        self.assertNotIn(id_archived, scoped_ids)

        global_rows = search_memory_summaries_sync(
            conn,
            "scope summary payload",
            "auto",
            limit=10,
            build_fts_query=build_fts_query,
            parse_recall_scope=_parse_recall_scope,
            safe_json_loads=lambda _s: [],
        )
        global_ids = {int(row["id"]) for row in global_rows}
        self.assertIn(id_global, global_ids)
        self.assertNotIn(id_allowed, global_ids)
        conn.close()


if __name__ == "__main__":
    unittest.main()
