from __future__ import annotations

import json
import os
import sqlite3
import time
import unittest

from db.migrate import apply_sqlite_migrations
from memory.service import remember_event
from memory.store import insert_memory_event_sync


class _NoopAsyncLock:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _stage_at_least(stage: str) -> bool:
    ranks = {"M0": 0, "M1": 1, "M2": 2, "M3": 3}
    return ranks.get((stage or "M0").upper(), 0) <= ranks["M3"]


def _normalize_tags(tags: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        cleaned = str(tag or "").strip().lower()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
    return out


def _utc_iso(_dt=None) -> str:
    return "2026-02-15T00:00:00+00:00"


def _utc_ts(_dt=None) -> int:
    return int(time.time())


def _insert_memory(conn: sqlite3.Connection, payload: dict) -> int:
    return insert_memory_event_sync(conn, payload, safe_json_loads=lambda s: json.loads(s or "[]"))


class MemoryReviewModeCaptureOnlyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        apply_sqlite_migrations(self.conn, os.path.join(os.getcwd(), "migrations"))
        self.lock = _NoopAsyncLock()

    async def asyncTearDown(self):
        self.conn.close()

    async def _remember(self, *, source_path: str) -> dict | None:
        return await remember_event(
            text=f"test memory {source_path}",
            tags=["ops"],
            importance=1,
            message=None,
            topic_hint=None,
            memory_review_mode="capture_only",
            source_path=source_path,
            owner_override_active=False,
            stage_at_least=_stage_at_least,
            normalize_tags=_normalize_tags,
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

    async def test_capture_only_routes_manual_remember_to_active_and_others_to_candidate(self):
        expectations = {
            "manual_remember": "active",
            "manual_profile": "candidate",
            "auto_capture": "candidate",
            "mining": "candidate",
        }
        cur = self.conn.cursor()

        for source_path, expected in expectations.items():
            saved = await self._remember(source_path=source_path)
            self.assertIsNotNone(saved)
            self.assertEqual(saved["lifecycle"], expected)

            cur.execute("SELECT lifecycle FROM memory_events WHERE id = ?", (int(saved["id"]),))
            row = cur.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(str(row[0]), expected)


if __name__ == "__main__":
    unittest.main()
