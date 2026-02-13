from __future__ import annotations

import os
import sqlite3
import unittest

from db.migrate import apply_sqlite_migrations
from memory.meta_store import insert_link_sync
from memory.meta_store import list_meta_items_sync
from memory.meta_store import resolve_policy_bundle_sync
from memory.meta_store import upsert_meta_item_sync


class MetaPolicyResolutionTests(unittest.TestCase):
    def test_resolves_seeded_policies_and_enforcement_flags(self):
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        apply_sqlite_migrations(conn, os.path.join(os.getcwd(), "migrations"))

        bundle = resolve_policy_bundle_sync(
            conn,
            sensitivity_policy_id="policy:member_privacy",
            caller_type="member",
            surface="public_channel",
        )

        self.assertIn("policies", bundle)
        self.assertGreaterEqual(len(bundle["policies"]), 1)
        self.assertTrue(bundle["enforcement"].get("no_cross_member_private_disclosure"))
        self.assertTrue(bundle["enforcement"].get("redact_discord_mentions_in_member_context"))
        conn.close()

    def test_upsert_meta_and_link_roundtrip(self):
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        apply_sqlite_migrations(conn, os.path.join(os.getcwd(), "migrations"))

        meta_id = upsert_meta_item_sync(
            conn,
            {
                "kind": "narrative",
                "name": "Brian systems arc",
                "scope": "global",
                "signals": ["memory:1", "memory:2"],
                "implications": ["prefer explicit tradeoffs"],
                "confidence": 0.8,
                "stability": "medium",
                "lifecycle": "active",
                "created_at_utc": "2026-02-13T00:00:00+00:00",
                "updated_at_utc": "2026-02-13T00:00:00+00:00",
            },
        )
        self.assertGreater(meta_id, 0)

        link_id = insert_link_sync(
            conn,
            {
                "from_ref": f"meta:{meta_id}",
                "to_ref": "memory:42",
                "relation": "supports",
                "weight": 1.0,
                "confidence": 0.9,
                "created_by": "human",
                "lifecycle": "active",
                "created_at_utc": "2026-02-13T00:00:00+00:00",
                "updated_at_utc": "2026-02-13T00:00:00+00:00",
            },
        )
        self.assertGreater(link_id, 0)

        narratives = list_meta_items_sync(conn, kind="narrative", scope="global", lifecycle="active", limit=10)
        self.assertEqual(len(narratives), 1)
        self.assertEqual(narratives[0]["id"], meta_id)
        self.assertEqual(narratives[0]["name"], "Brian systems arc")
        conn.close()


if __name__ == "__main__":
    unittest.main()
