from __future__ import annotations

import os
import sqlite3
import unittest

from db.migrate import apply_sqlite_migrations
from memory.store import search_memory_events_sync
from retrieval.fts_query import build_fts_query


def _stage_at_least(_stage: str) -> bool:
    return True


def _parse_recall_scope(_scope: str | None) -> tuple[str, int | None, int | None]:
    return ("auto", None, None)


class FtsQueryTests(unittest.TestCase):
    def test_hyphenated_words_are_split(self):
        query = build_fts_query("ultra-tight follow-up")
        self.assertEqual(query, "ultra OR tight OR follow")

    def test_search_with_hyphenated_prompt_does_not_raise(self):
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        apply_sqlite_migrations(conn, os.path.join(os.getcwd(), "migrations"))
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO memory_events (
                created_at_utc, created_ts, text, tags_json, importance, tier
            ) VALUES ('2026-02-09T00:00:00+00:00', 0, 'tight follow up draft', '[]', 1, 0)
            """
        )
        event_id = int(cur.lastrowid)
        cur.execute(
            "INSERT INTO memory_events_fts(rowid, text, tags) VALUES (?, ?, '')",
            (event_id, "tight follow up draft"),
        )
        conn.commit()

        events = search_memory_events_sync(
            conn,
            "let's do an ultra-tight version of Draft B",
            "auto",
            limit=8,
            build_fts_query=build_fts_query,
            parse_recall_scope=_parse_recall_scope,
            stage_at_least=_stage_at_least,
            safe_json_loads=lambda _s: [],
        )
        self.assertIsInstance(events, list)
        conn.close()


if __name__ == "__main__":
    unittest.main()
