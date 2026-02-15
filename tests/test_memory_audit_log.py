from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from shutil import copy2

from importlib import import_module

from db.migrate import apply_sqlite_migrations
from memory.lifecycle_service import MemoryLifecycleError
from memory.lifecycle_service import approve_memory_sync
from memory.lifecycle_service import list_candidate_memories_sync
from memory.lifecycle_service import reject_memory_sync
from memory.store import insert_memory_event_sync


def _safe_json_loads(raw: str):
    try:
        return json.loads(raw) if raw else []
    except Exception:
        return []


def _safe_json_dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _utc_now_iso() -> str:
    return "2026-02-15T12:00:00+00:00"


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


def _insert_memory(
    conn: sqlite3.Connection,
    *,
    lifecycle: str,
    text: str,
    tags: list[str] | None = None,
    importance: int = 0,
    topic_id: str | None = None,
) -> int:
    payload = {
        "created_at_utc": "2026-02-15T10:00:00+00:00",
        "created_ts": int(time.time()),
        "scope": "global",
        "guild_id": None,
        "channel_id": None,
        "channel_name": None,
        "author_id": 123,
        "author_name": "tester",
        "source_message_id": 555,
        "lifecycle": lifecycle,
        "text": text,
        "tags_json": _safe_json_dumps(tags or []),
        "importance": int(importance),
        "tier": 1,
        "topic_id": topic_id,
        "topic_source": "manual",
        "topic_confidence": None,
        "summarized": 0,
        "logged_from_channel_id": None,
        "logged_from_channel_name": None,
        "logged_from_message_id": None,
        "source_channel_id": None,
        "source_channel_name": None,
    }
    return insert_memory_event_sync(conn, payload, safe_json_loads=_safe_json_loads)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _copy_migrations_without_0019(dst_dir: Path) -> None:
    src_dir = _repo_root() / "migrations"
    for src in sorted(src_dir.iterdir()):
        if not src.is_file():
            continue
        if src.name.startswith("0019_"):
            continue
        copy2(src, dst_dir / src.name)


class MemoryAuditLogTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        apply_sqlite_migrations(self.conn, os.path.join(os.getcwd(), "migrations"))

    def tearDown(self):
        self.conn.close()

    def test_migration_0019_is_idempotent_and_adds_columns_table_indexes(self):
        apply_sqlite_migrations(self.conn, os.path.join(os.getcwd(), "migrations"))
        cur = self.conn.cursor()
        cur.execute("PRAGMA table_info(memory_events)")
        info_rows = cur.fetchall()
        cols = {str(row[1]) for row in info_rows}
        self.assertIn("reviewed_by_user_id", cols)
        self.assertIn("reviewed_at_utc", cols)
        self.assertIn("review_note", cols)
        importance_row = next((row for row in info_rows if str(row[1]) == "importance"), None)
        self.assertIsNotNone(importance_row)
        self.assertIn("REAL", str(importance_row[2] or "").upper())

        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='memory_audit_log'")
        self.assertIsNotNone(cur.fetchone())
        cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_memory_audit_memory_id'")
        self.assertIsNotNone(cur.fetchone())
        cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_memory_audit_created_at'")
        self.assertIsNotNone(cur.fetchone())

    def test_list_candidates_only_returns_candidate_lifecycle(self):
        candidate_id = _insert_memory(self.conn, lifecycle="candidate", text="candidate memory")
        _insert_memory(self.conn, lifecycle="active", text="active memory")

        rows = list_candidate_memories_sync(
            self.conn,
            limit=20,
            offset=0,
            safe_json_loads=_safe_json_loads,
        )
        ids = {int(r["id"]) for r in rows}
        self.assertIn(candidate_id, ids)
        self.assertEqual(len(ids), 1)

    def test_approve_writes_review_fields_audit_and_fts_tags(self):
        memory_id = _insert_memory(
            self.conn,
            lifecycle="candidate",
            text="candidate to approve",
            tags=["ops"],
            importance=0,
        )
        updated = approve_memory_sync(
            self.conn,
            memory_id=memory_id,
            actor_person_id=777,
            tags=["ops", "decision"],
            topic_id="governance",
            importance=0.9,
            note="approved during review",
            utc_now_iso=_utc_now_iso,
            normalize_tags=_normalize_tags,
            safe_json_loads=_safe_json_loads,
            safe_json_dumps=_safe_json_dumps,
        )

        self.assertEqual(updated["lifecycle"], "active")
        self.assertAlmostEqual(float(updated["importance"]), 0.9, places=6)
        self.assertEqual(str(updated.get("topic_id") or ""), "governance")
        self.assertEqual(int(updated.get("reviewed_by_user_id") or 0), 777)
        self.assertEqual(str(updated.get("reviewed_at_utc") or ""), _utc_now_iso())
        self.assertEqual(str(updated.get("review_note") or ""), "approved during review")

        cur = self.conn.cursor()
        cur.execute(
            "SELECT action, actor_person_id, before_json, after_json, reason FROM memory_audit_log WHERE memory_id=?",
            (memory_id,),
        )
        rows = cur.fetchall()
        self.assertEqual(len(rows), 1)
        action, actor_person_id, before_json, after_json, reason = rows[0]
        self.assertEqual(str(action), "approve")
        self.assertEqual(int(actor_person_id), 777)
        self.assertEqual(str(reason), "approved during review")

        before_obj = json.loads(before_json)
        after_obj = json.loads(after_json)
        self.assertEqual(str(before_obj.get("lifecycle") or ""), "candidate")
        self.assertEqual(str(after_obj.get("lifecycle") or ""), "active")
        self.assertAlmostEqual(float(after_obj.get("importance") or 0.0), 0.9, places=6)
        self.assertIn("governance", after_obj.get("tags") or [])

        cur.execute("SELECT tags FROM memory_events_fts WHERE rowid = ?", (memory_id,))
        fts_tags = str(cur.fetchone()[0] or "")
        self.assertIn("governance", fts_tags)
        self.assertIn("decision", fts_tags)

    def test_approve_defaults_importance_to_point_five_when_omitted(self):
        memory_id = _insert_memory(
            self.conn,
            lifecycle="candidate",
            text="candidate default importance",
            tags=["ops"],
            importance=1,
        )
        updated = approve_memory_sync(
            self.conn,
            memory_id=memory_id,
            actor_person_id=777,
            utc_now_iso=_utc_now_iso,
            normalize_tags=_normalize_tags,
            safe_json_loads=_safe_json_loads,
            safe_json_dumps=_safe_json_dumps,
        )
        self.assertAlmostEqual(float(updated["importance"]), 0.5, places=6)

    def test_reject_writes_review_fields_and_audit_reason(self):
        memory_id = _insert_memory(
            self.conn,
            lifecycle="candidate",
            text="candidate to reject",
            tags=["ops"],
            importance=0,
        )
        updated = reject_memory_sync(
            self.conn,
            memory_id=memory_id,
            actor_person_id=555,
            reason="duplicate",
            utc_now_iso=_utc_now_iso,
            safe_json_loads=_safe_json_loads,
            safe_json_dumps=_safe_json_dumps,
        )

        self.assertEqual(str(updated.get("lifecycle") or ""), "deprecated")
        self.assertEqual(int(updated.get("reviewed_by_user_id") or 0), 555)
        self.assertEqual(str(updated.get("review_note") or ""), "duplicate")

        cur = self.conn.cursor()
        cur.execute(
            "SELECT action, actor_person_id, reason, before_json, after_json FROM memory_audit_log WHERE memory_id=?",
            (memory_id,),
        )
        rows = cur.fetchall()
        self.assertEqual(len(rows), 1)
        action, actor_person_id, reason, before_json, after_json = rows[0]
        self.assertEqual(str(action), "reject")
        self.assertEqual(int(actor_person_id), 555)
        self.assertEqual(str(reason), "duplicate")
        self.assertEqual(str(json.loads(before_json).get("lifecycle") or ""), "candidate")
        self.assertEqual(str(json.loads(after_json).get("lifecycle") or ""), "deprecated")

    def test_approve_and_reject_require_candidate_state(self):
        active_id = _insert_memory(self.conn, lifecycle="active", text="already active")
        with self.assertRaises(MemoryLifecycleError) as approve_err:
            approve_memory_sync(
                self.conn,
                memory_id=active_id,
                actor_person_id=1,
                utc_now_iso=_utc_now_iso,
                normalize_tags=_normalize_tags,
                safe_json_loads=_safe_json_loads,
                safe_json_dumps=_safe_json_dumps,
            )
        self.assertEqual(approve_err.exception.code, "not_candidate")

        with self.assertRaises(MemoryLifecycleError) as reject_err:
            reject_memory_sync(
                self.conn,
                memory_id=active_id,
                actor_person_id=1,
                utc_now_iso=_utc_now_iso,
                safe_json_loads=_safe_json_loads,
                safe_json_dumps=_safe_json_dumps,
            )
        self.assertEqual(reject_err.exception.code, "not_candidate")

    def test_migration_rebuild_normalizes_integer_importance_and_rebuilds_fts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            _copy_migrations_without_0019(tmp_dir)

            conn = sqlite3.connect(":memory:", check_same_thread=False)
            apply_sqlite_migrations(conn, str(tmp_dir))

            memory_id = _insert_memory(
                conn,
                lifecycle="candidate",
                text="old integer importance row",
                tags=["ops"],
                importance=1,
            )
            cur = conn.cursor()
            cur.execute("UPDATE memory_events SET importance = 2 WHERE id = ?", (memory_id,))
            conn.commit()

            mod = import_module("migrations.0019_memory_review_audit")
            mod.upgrade(conn)

            cur.execute("SELECT importance FROM memory_events WHERE id = ?", (memory_id,))
            normalized = float(cur.fetchone()[0])
            self.assertAlmostEqual(normalized, 1.0, places=6)

            cur.execute("PRAGMA table_info(memory_events)")
            info_rows = cur.fetchall()
            importance_row = next((row for row in info_rows if str(row[1]) == "importance"), None)
            self.assertIsNotNone(importance_row)
            self.assertIn("REAL", str(importance_row[2] or "").upper())

            cur.execute("SELECT rowid, text FROM memory_events_fts WHERE rowid = ?", (memory_id,))
            fts_row = cur.fetchone()
            self.assertIsNotNone(fts_row)
            self.assertEqual(int(fts_row[0]), memory_id)
            self.assertIn("old integer importance row", str(fts_row[1]))
            conn.close()


if __name__ == "__main__":
    unittest.main()
