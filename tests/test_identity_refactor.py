from __future__ import annotations

import importlib.util
import json
import sqlite3
import time
import unittest
from pathlib import Path
from unittest import mock

from controller.identity_store import canonical_person_id_sync
from controller.identity_store import dedupe_memory_events_by_id
from controller.identity_store import get_or_create_person_sync
from controller.identity_store import resolve_person_id_sync
from controller.identity_store import revoke_identifier_sync
from controller.store import ensure_controller_schema
from controller.store import select_active_controller_config_sync
from controller.store import upsert_user_profile_last_seen_sync


def _load_migration_module(filename: str):
    path = Path(__file__).resolve().parents[1] / "migrations" / filename
    spec = importlib.util.spec_from_file_location(f"test_migration_{filename.replace('.', '_')}", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load migration module: {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IdentityRefactorTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        ensure_controller_schema(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_get_or_create_person_idempotent(self):
        person_a = get_or_create_person_sync(
            self.conn,
            platform="discord",
            external_id="237008609773486080",
            origin="discord:test-guild",
            label="discord_user_id",
        )
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT last_seen_at
            FROM person_identifiers
            WHERE platform='discord' AND external_id='237008609773486080' AND revoked_at IS NULL
            """,
        )
        seen_a = str(cur.fetchone()[0])

        time.sleep(0.001)
        person_b = get_or_create_person_sync(
            self.conn,
            platform="discord",
            external_id="237008609773486080",
            origin="discord:test-guild",
            label="discord_user_id",
        )
        cur.execute(
            """
            SELECT last_seen_at
            FROM person_identifiers
            WHERE platform='discord' AND external_id='237008609773486080' AND revoked_at IS NULL
            """,
        )
        seen_b = str(cur.fetchone()[0])

        self.assertEqual(person_a, person_b)
        self.assertGreaterEqual(seen_b, seen_a)

    def test_unique_active_identifier_constraint(self):
        cur = self.conn.cursor()
        cur.execute("INSERT INTO people (created_at, origin, status) VALUES ('t', 'o', 'active')")
        p1 = int(cur.lastrowid)
        cur.execute("INSERT INTO people (created_at, origin, status) VALUES ('t', 'o', 'active')")
        p2 = int(cur.lastrowid)
        cur.execute(
            """
            INSERT INTO person_identifiers (
                person_id, platform, external_id, label, strength, created_at, last_seen_at, revoked_at
            ) VALUES (?, 'discord', '237008609773486080', 'discord_user_id', 'primary', 't', 't', NULL)
            """,
            (p1,),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            cur.execute(
                """
                INSERT INTO person_identifiers (
                    person_id, platform, external_id, label, strength, created_at, last_seen_at, revoked_at
                ) VALUES (?, 'discord', '237008609773486080', 'discord_user_id', 'primary', 't', 't', NULL)
                """,
                (p2,),
            )

    def test_identifier_index_supports_active_handles_lookup_by_person(self):
        cur = self.conn.cursor()
        cur.execute("PRAGMA index_list('person_identifiers')")
        names = {str(row[1]) for row in cur.fetchall()}
        self.assertIn("idx_person_identifiers_person_platform_active", names)

    def test_revoke_identifier_revokes_all_active_and_warns_on_count_mismatch(self):
        cur = self.conn.cursor()
        cur.execute("DROP INDEX IF EXISTS idx_person_identifiers_platform_external_active")
        cur.execute("INSERT INTO people (created_at, origin, status) VALUES ('t', 'o', 'active')")
        p1 = int(cur.lastrowid)
        cur.execute("INSERT INTO people (created_at, origin, status) VALUES ('t', 'o', 'active')")
        p2 = int(cur.lastrowid)
        cur.execute(
            """
            INSERT INTO person_identifiers (
                person_id, platform, external_id, label, strength, created_at, last_seen_at, revoked_at
            ) VALUES (?, 'discord', '237008609773486080', 'discord_user_id', 'primary', 't', 't', NULL)
            """,
            (p1,),
        )
        cur.execute(
            """
            INSERT INTO person_identifiers (
                person_id, platform, external_id, label, strength, created_at, last_seen_at, revoked_at
            ) VALUES (?, 'discord', '237008609773486080', 'discord_user_id', 'primary', 't', 't', NULL)
            """,
            (p2,),
        )
        self.conn.commit()

        with mock.patch("builtins.print") as mocked_print:
            revoke_identifier_sync(
                self.conn,
                platform="discord",
                external_id="237008609773486080",
                reason="test",
            )
            self.assertTrue(mocked_print.called)
            self.assertIn("cardinality mismatch", str(mocked_print.call_args[0][0]))

        cur.execute(
            """
            SELECT COUNT(*)
            FROM person_identifiers
            WHERE platform='discord' AND external_id='237008609773486080' AND revoked_at IS NULL
            """,
        )
        active_count = int(cur.fetchone()[0])
        self.assertEqual(active_count, 0)

    def test_resolve_person_id_returns_canonical_person(self):
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO people (created_at, origin, status, merged_into_person_id) VALUES ('t', 'o', 'active', NULL)"
        )
        p1 = int(cur.lastrowid)
        cur.execute(
            "INSERT INTO people (created_at, origin, status, merged_into_person_id) VALUES ('t', 'o', 'active', NULL)"
        )
        p2 = int(cur.lastrowid)
        cur.execute("UPDATE people SET merged_into_person_id=? WHERE id=?", (p2, p1))
        cur.execute(
            """
            INSERT INTO person_identifiers (
                person_id, platform, external_id, label, strength, created_at, last_seen_at, revoked_at
            ) VALUES (?, 'discord', '237008609773486080', 'discord_user_id', 'primary', 't', 't', NULL)
            """,
            (p1,),
        )
        self.conn.commit()

        resolved = resolve_person_id_sync(self.conn, "discord", "237008609773486080")
        self.assertEqual(resolved, p2)

    def test_canonical_person_id_cycle_returns_start_and_logs_warning(self):
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO people (created_at, origin, status, merged_into_person_id) VALUES ('t', 'o', 'active', NULL)"
        )
        p1 = int(cur.lastrowid)
        cur.execute(
            "INSERT INTO people (created_at, origin, status, merged_into_person_id) VALUES ('t', 'o', 'active', NULL)"
        )
        p2 = int(cur.lastrowid)
        cur.execute("UPDATE people SET merged_into_person_id=? WHERE id=?", (p2, p1))
        cur.execute("UPDATE people SET merged_into_person_id=? WHERE id=?", (p1, p2))
        self.conn.commit()

        with mock.patch("builtins.print") as mocked_print:
            canonical = canonical_person_id_sync(self.conn, p1)
            self.assertEqual(canonical, p1)
            self.assertTrue(mocked_print.called)
            self.assertIn("cycle detected", str(mocked_print.call_args[0][0]))

    def test_profile_keyed_by_person_id(self):
        upsert_user_profile_last_seen_sync(self.conn, person_id=101, last_seen_at_utc="2026-02-09T00:00:00+00:00")
        cur = self.conn.cursor()
        cur.execute("PRAGMA table_info(user_profiles)")
        cols = {str(row[1]) for row in cur.fetchall()}
        self.assertIn("person_id", cols)
        self.assertNotIn("id", cols)
        cur.execute("SELECT person_id FROM user_profiles WHERE person_id=101")
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(int(row[0]), 101)

    def test_migration_preserves_profile_json(self):
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE user_profiles (
                id INTEGER PRIMARY KEY,
                layer_estimate TEXT DEFAULT 'unknown',
                risk_flags_json TEXT DEFAULT '[]',
                preferred_tone TEXT,
                dev_arc_meta_ids_json TEXT DEFAULT '[]',
                last_seen_at_utc TEXT
            )
            """
        )
        cur.execute(
            """
            INSERT INTO user_profiles (id, layer_estimate, risk_flags_json, preferred_tone, dev_arc_meta_ids_json, last_seen_at_utc)
            VALUES (237008609773486080, 'L4', '["boundary_risk"]', 'direct', '[11,12]', '2026-02-09T01:00:00+00:00')
            """
        )
        conn.commit()

        _load_migration_module("0012_people_identity_core.py").upgrade(conn)
        _load_migration_module("0013_user_profiles_person_id.py").upgrade(conn)

        cur.execute("PRAGMA table_info(user_profiles)")
        cols = {str(row[1]) for row in cur.fetchall()}
        self.assertIn("person_id", cols)
        self.assertNotIn("id", cols)
        cur.execute(
            """
            SELECT up.layer_estimate, up.risk_flags_json, up.preferred_tone, up.dev_arc_meta_ids_json, up.last_seen_at_utc,
                   pi.external_id, pi.last_seen_at
            FROM user_profiles up
            JOIN person_identifiers pi ON pi.person_id = up.person_id
            WHERE pi.platform='discord' AND pi.revoked_at IS NULL
            LIMIT 1
            """
        )
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "L4")
        self.assertEqual(row[1], '["boundary_risk"]')
        self.assertEqual(row[2], "direct")
        self.assertEqual(row[3], "[11,12]")
        self.assertEqual(row[4], "2026-02-09T01:00:00+00:00")
        self.assertEqual(row[5], "237008609773486080")
        self.assertEqual(row[6], "2026-02-09T01:00:00+00:00")
        conn.close()

    def test_episode_backfill_only_for_snowflake_like_ids(self):
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE people (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT,
                origin TEXT,
                status TEXT,
                merged_into_person_id INTEGER
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE person_identifiers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id INTEGER NOT NULL,
                platform TEXT NOT NULL,
                external_id TEXT NOT NULL,
                label TEXT,
                strength TEXT,
                created_at TEXT,
                last_seen_at TEXT,
                revoked_at TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE episode_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                target_user_id INTEGER
            )
            """
        )
        cur.execute("INSERT INTO people (created_at, origin, status, merged_into_person_id) VALUES ('t','o','active',NULL)")
        person_id = int(cur.lastrowid)
        cur.execute(
            """
            INSERT INTO person_identifiers (
                person_id, platform, external_id, label, strength, created_at, last_seen_at, revoked_at
            ) VALUES (?, 'discord', '237008609773486080', 'discord_user_id', 'primary', 't', 't', NULL)
            """,
            (person_id,),
        )
        cur.execute("INSERT INTO episode_logs (user_id, target_user_id) VALUES (12345, NULL)")
        cur.execute("INSERT INTO episode_logs (user_id, target_user_id) VALUES (237008609773486080, NULL)")
        conn.commit()

        _load_migration_module("0014_episode_logs_person_columns.py").upgrade(conn)

        cur.execute("SELECT person_id FROM episode_logs WHERE user_id=12345")
        self.assertIsNone(cur.fetchone()[0])
        cur.execute("SELECT person_id FROM episode_logs WHERE user_id=237008609773486080")
        self.assertEqual(int(cur.fetchone()[0]), person_id)
        conn.close()

    def test_episode_backfill_writes_canonical_person_ids(self):
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE people (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT,
                origin TEXT,
                status TEXT,
                merged_into_person_id INTEGER
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE person_identifiers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id INTEGER NOT NULL,
                platform TEXT NOT NULL,
                external_id TEXT NOT NULL,
                label TEXT,
                strength TEXT,
                created_at TEXT,
                last_seen_at TEXT,
                revoked_at TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE episode_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                target_user_id INTEGER
            )
            """
        )
        cur.execute("INSERT INTO people (created_at, origin, status, merged_into_person_id) VALUES ('t','o','active',NULL)")
        p1 = int(cur.lastrowid)
        cur.execute("INSERT INTO people (created_at, origin, status, merged_into_person_id) VALUES ('t','o','active',NULL)")
        p2 = int(cur.lastrowid)
        cur.execute("UPDATE people SET merged_into_person_id=? WHERE id=?", (p2, p1))
        cur.execute(
            """
            INSERT INTO person_identifiers (
                person_id, platform, external_id, label, strength, created_at, last_seen_at, revoked_at
            ) VALUES (?, 'discord', '237008609773486080', 'discord_user_id', 'primary', 't', 't', NULL)
            """,
            (p1,),
        )
        cur.execute("INSERT INTO episode_logs (user_id, target_user_id) VALUES (237008609773486080, NULL)")
        conn.commit()

        _load_migration_module("0014_episode_logs_person_columns.py").upgrade(conn)
        cur.execute("SELECT person_id FROM episode_logs WHERE user_id=237008609773486080")
        self.assertEqual(int(cur.fetchone()[0]), p2)
        conn.close()

    def test_dual_tag_recall_dedupes_memory_ids(self):
        merged = [
            {"id": 11, "text": "from person tag"},
            {"id": 12, "text": "from person tag"},
            {"id": 11, "text": "from user tag duplicate"},
            {"id": 13, "text": "from user tag"},
        ]
        deduped = dedupe_memory_events_by_id(merged, limit=6)
        self.assertEqual([int(row["id"]) for row in deduped], [11, 12, 13])

    def test_tag_bridge_prefers_person_tag_when_at_capacity(self):
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE people (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT,
                origin TEXT,
                status TEXT,
                merged_into_person_id INTEGER
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE person_identifiers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id INTEGER NOT NULL,
                platform TEXT NOT NULL,
                external_id TEXT NOT NULL,
                label TEXT,
                strength TEXT,
                created_at TEXT,
                last_seen_at TEXT,
                revoked_at TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE memory_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tags_json TEXT
            )
            """
        )
        cur.execute("INSERT INTO people (created_at, origin, status, merged_into_person_id) VALUES ('t','o','active',NULL)")
        person_id = int(cur.lastrowid)
        cur.execute(
            """
            INSERT INTO person_identifiers (
                person_id, platform, external_id, label, strength, created_at, last_seen_at, revoked_at
            ) VALUES (?, 'discord', '237008609773486080', 'discord_user_id', 'primary', 't', 't', NULL)
            """,
            (person_id,),
        )
        mod = _load_migration_module("0015_profile_tag_person_bridge.py")
        base_tags = [f"t{i}" for i in range(mod.TAG_CAP - 1)] + ["subject:user:237008609773486080"]
        cur.execute("INSERT INTO memory_events (tags_json) VALUES (?)", (json.dumps(base_tags),))
        conn.commit()

        mod.upgrade(conn)
        cur.execute("SELECT tags_json FROM memory_events LIMIT 1")
        tags_json = str(cur.fetchone()[0])
        tags = json.loads(tags_json)
        self.assertIn(f"subject:person:{person_id}", tags)
        self.assertNotIn("subject:user:237008609773486080", tags)
        self.assertLessEqual(len(tags), mod.TAG_CAP)
        conn.close()

    def test_controller_scope_prefers_person_then_user_without_short_circuit(self):
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO controller_configs (
                scope, persona, depth, strictness, intervention_level, lifecycle
            ) VALUES ('user_id:42', 'guide', 0.2, 0.7, 0.2, 'active')
            """
        )
        cur.execute(
            """
            INSERT INTO controller_configs (
                scope, persona, depth, strictness, intervention_level, lifecycle
            ) VALUES ('person_id:77', 'analyst', 0.8, 0.8, 0.7, 'active')
            """
        )
        self.conn.commit()

        cfg = select_active_controller_config_sync(
            self.conn,
            caller_type="member",
            context_profile_id=1,
            user_id=42,
            person_id=77,
        )
        self.assertEqual(cfg["scope"], "person_id:77")


if __name__ == "__main__":
    unittest.main()
