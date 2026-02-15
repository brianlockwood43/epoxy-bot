from __future__ import annotations

import json
import os
import sqlite3
import time
import unittest

from db.migrate import apply_sqlite_migrations
from memory.service import remember_event
from memory.store import insert_memory_event_sync
from memory.store import search_memory_events_sync
from retrieval.fts_query import build_fts_query


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


def _parse_recall_scope(scope: str | None) -> tuple[str, int | None, int | None]:
    text = (scope or "auto").strip().lower()
    temporal = "auto"
    guild_id: int | None = None
    channel_id: int | None = None
    for token in text.split():
        if token in {"hot", "warm", "cold", "auto"}:
            temporal = token
        elif token.startswith("channel:"):
            try:
                channel_id = int(token.split(":", 1)[1])
            except Exception:
                channel_id = None
        elif token.startswith("guild:"):
            try:
                guild_id = int(token.split(":", 1)[1])
            except Exception:
                guild_id = None
    return temporal, guild_id, channel_id


class MemoryReviewModeOffTests(unittest.IsolatedAsyncioTestCase):
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
            memory_review_mode="off",
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

    async def test_off_mode_writes_active_for_all_sources(self):
        for source_path in ("manual_remember", "manual_profile", "auto_capture", "mining"):
            saved = await self._remember(source_path=source_path)
            self.assertIsNotNone(saved)
            self.assertEqual(saved["lifecycle"], "active")

    async def test_recall_paths_still_exclude_candidate(self):
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO memory_events (
                created_at_utc, created_ts, scope, guild_id, channel_id, lifecycle, text, tags_json, importance, tier
            ) VALUES ('2026-02-15T00:00:00+00:00', 1, 'channel:100', 1, 100, 'active', 'review mode query', '[]', 1, 0)
            """
        )
        active_id = int(cur.lastrowid)
        cur.execute("INSERT INTO memory_events_fts(rowid, text, tags) VALUES (?, ?, '')", (active_id, "review mode query"))

        cur.execute(
            """
            INSERT INTO memory_events (
                created_at_utc, created_ts, scope, guild_id, channel_id, lifecycle, text, tags_json, importance, tier
            ) VALUES ('2026-02-15T00:00:00+00:00', 1, 'channel:100', 1, 100, 'candidate', 'review mode query', '[]', 1, 0)
            """
        )
        candidate_id = int(cur.lastrowid)
        cur.execute("INSERT INTO memory_events_fts(rowid, text, tags) VALUES (?, ?, '')", (candidate_id, "review mode query"))
        self.conn.commit()

        rows = search_memory_events_sync(
            self.conn,
            "review mode query",
            "auto channel:100 guild:1",
            limit=10,
            build_fts_query=build_fts_query,
            parse_recall_scope=_parse_recall_scope,
            stage_at_least=_stage_at_least,
            safe_json_loads=lambda _s: [],
        )
        ids = {int(row["id"]) for row in rows}
        self.assertIn(active_id, ids)
        self.assertNotIn(candidate_id, ids)


if __name__ == "__main__":
    unittest.main()
