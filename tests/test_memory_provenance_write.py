from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime
from datetime import timezone
from importlib import import_module
from pathlib import Path
from shutil import copy2

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


def _utc_iso(dt: datetime | None = None) -> str:
    dt = dt or datetime(2026, 2, 16, tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _utc_ts(dt: datetime | None = None) -> int:
    dt = dt or datetime(2026, 2, 16, tzinfo=timezone.utc)
    return int(dt.timestamp())


def _insert_memory(conn: sqlite3.Connection, payload: dict) -> int:
    return insert_memory_event_sync(conn, payload, safe_json_loads=lambda s: json.loads(s or "[]"))


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _copy_migrations_without_0020(dst_dir: Path) -> None:
    src_dir = _repo_root() / "migrations"
    for src in sorted(src_dir.iterdir()):
        if not src.is_file():
            continue
        if src.name.startswith("0020_"):
            continue
        copy2(src, dst_dir / src.name)


class _FakeGuild:
    id = 123


class _FakeChannel:
    id = 456
    name = "ops"

    def __str__(self) -> str:
        return self.name


class _FakeAuthor:
    id = 789

    def __str__(self) -> str:
        return "tester"


class _FakeMessage:
    id = 999
    guild = _FakeGuild()
    channel = _FakeChannel()
    author = _FakeAuthor()
    created_at = datetime(2026, 2, 16, tzinfo=timezone.utc)


class MemoryProvenanceWriteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        apply_sqlite_migrations(self.conn, os.path.join(os.getcwd(), "migrations"))
        self.lock = _NoopAsyncLock()

    async def asyncTearDown(self):
        self.conn.close()

    async def test_remember_event_writes_provenance_json_when_message_available(self):
        saved = await remember_event(
            text="Provenance write test",
            tags=["policy"],
            importance=1,
            message=_FakeMessage(),
            topic_hint="governance",
            memory_review_mode="off",
            source_path="auto_capture",
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

        cur = self.conn.cursor()
        cur.execute("SELECT type, provenance_json FROM memory_events WHERE id = ?", (int(saved["id"]),))
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(str(row[0] or ""), "policy")

        provenance = json.loads(str(row[1] or "{}"))
        self.assertEqual(provenance.get("source"), "auto_capture")
        self.assertEqual(provenance.get("surface"), "public_channel")
        self.assertEqual(provenance.get("channel_id"), "456")
        self.assertEqual(provenance.get("message_id"), "999")

    def test_migration_0020_adds_provenance_and_backfills_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            _copy_migrations_without_0020(tmp_dir)

            conn = sqlite3.connect(":memory:", check_same_thread=False)
            apply_sqlite_migrations(conn, str(tmp_dir))

            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO memory_events (
                    created_at_utc, created_ts, scope, lifecycle, type, text, tags_json, importance, tier
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "2026-02-16T00:00:00+00:00",
                    int(time.time()),
                    "global",
                    "active",
                    "",
                    "legacy row for 0020",
                    json.dumps(["kind:profile", "profile"]),
                    0.5,
                    1,
                ),
            )
            memory_id = int(cur.lastrowid)
            conn.commit()

            mod = import_module("migrations.0020_memory_provenance_and_type_backfill")
            mod.upgrade(conn)
            mod.upgrade(conn)

            cur.execute("SELECT type, provenance_json FROM memory_events WHERE id = ?", (memory_id,))
            migrated = cur.fetchone()
            self.assertIsNotNone(migrated)
            self.assertEqual(str(migrated[0] or ""), "profile")
            self.assertEqual(str(migrated[1] or "{}"), "{}")
            conn.close()


if __name__ == "__main__":
    unittest.main()
