from __future__ import annotations

import json
import os
import sqlite3
import time
import unittest

from db.migrate import apply_sqlite_migrations
from memory.service import remember_event
from memory.store import insert_memory_event_sync
from memory.tagging import extract_kind
from memory.tagging import extract_topics
from memory.tagging import normalize_memory_tags


class _NoopAsyncLock:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _stage_at_least(stage: str) -> bool:
    ranks = {"M0": 0, "M1": 1, "M2": 2, "M3": 3}
    return ranks.get((stage or "M0").upper(), 0) <= ranks["M3"]


def _utc_iso(_dt=None) -> str:
    return "2026-02-16T00:00:00+00:00"


def _utc_ts(_dt=None) -> int:
    return int(time.time())


def _insert_memory(conn: sqlite3.Connection, payload: dict) -> int:
    return insert_memory_event_sync(conn, payload, safe_json_loads=lambda s: json.loads(s or "[]"))


class MemoryTypedTagsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        apply_sqlite_migrations(self.conn, os.path.join(os.getcwd(), "migrations"))
        self.lock = _NoopAsyncLock()

    async def asyncTearDown(self):
        self.conn.close()

    def test_tagging_helpers_normalize_and_extract(self):
        tags = normalize_memory_tags(
            ["Decision", "ops", "topic:ops", "subject:user:42", "source:mining", "kind:decision"],
            preserve_legacy=True,
        )
        self.assertEqual(extract_kind(tags), "decision")
        self.assertIn("kind:decision", tags)
        self.assertIn("decision", tags)
        self.assertIn("topic:ops", tags)
        self.assertIn("ops", tags)
        self.assertIn("subject:user:42", tags)
        self.assertIn("source:mining", tags)
        self.assertEqual(extract_topics(tags), ["ops"])

    async def test_remember_event_normalizes_typed_tags_and_sets_type(self):
        saved = await remember_event(
            text="Typed tags write-path test",
            tags=["decision", "ops", "subject:user:42"],
            importance=1,
            message=None,
            topic_hint=None,
            memory_review_mode="off",
            source_path="manual_remember",
            owner_override_active=False,
            stage_at_least=_stage_at_least,
            normalize_tags=lambda tags: tags,
            reserved_kind_tags={"decision", "policy", "canon", "profile", "protocol"},
            topic_suggest=False,
            topic_min_conf=0.85,
            topic_allowlist=[],
            db_lock=self.lock,
            db_conn=self.conn,
            list_known_topics_sync=lambda _conn, _limit: [],
            client=None,
            openai_model="gpt-5.1",
            utc_iso=_utc_iso,
            utc_ts=_utc_ts,
            infer_tier=lambda _ts: 1,
            safe_json_dumps=lambda v: json.dumps(v),
            insert_memory_event_sync=_insert_memory,
        )
        self.assertIsNotNone(saved)
        memory_id = int(saved["id"])

        cur = self.conn.cursor()
        cur.execute("SELECT type, tags_json FROM memory_events WHERE id = ?", (memory_id,))
        row = cur.fetchone()
        self.assertIsNotNone(row)
        memory_type = str(row[0] or "")
        stored_tags = json.loads(str(row[1] or "[]"))
        self.assertEqual(memory_type, "decision")
        self.assertIn("kind:decision", stored_tags)
        self.assertIn("decision", stored_tags)
        self.assertIn("topic:ops", stored_tags)
        self.assertIn("ops", stored_tags)
        self.assertIn("subject:user:42", stored_tags)
        self.assertIn("source:manual_remember", stored_tags)


if __name__ == "__main__":
    unittest.main()
