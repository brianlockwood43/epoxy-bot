from __future__ import annotations

import sqlite3
import unittest

from controller.store import ensure_controller_schema
from controller.store import fetch_episode_logs_sync
from controller.store import insert_episode_log_sync
from controller.store import update_latest_dm_draft_evaluation_sync
from controller.store import update_latest_dm_draft_feedback_sync


class ControllerStoreDmFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        ensure_controller_schema(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_updates_latest_dm_draft_episode(self):
        insert_episode_log_sync(
            self.conn,
            {
                "timestamp_utc": "2026-01-01T00:00:00+00:00",
                "user_id": 1,
                "tags": ["mode:dm_draft"],
                "input_excerpt": "x",
                "assistant_output_excerpt": "y",
            },
        )
        insert_episode_log_sync(
            self.conn,
            {
                "timestamp_utc": "2026-01-01T00:01:00+00:00",
                "user_id": 1,
                "tags": ["mode:dm_draft"],
                "input_excerpt": "x2",
                "assistant_output_excerpt": "y2",
            },
        )
        row = update_latest_dm_draft_feedback_sync(
            self.conn,
            user_id=1,
            outcome="sent",
            note="worked well",
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["explicit_rating"], 2)
        self.assertEqual(row["outcome"], "sent")

    def test_returns_none_when_no_dm_episode(self):
        row = update_latest_dm_draft_feedback_sync(
            self.conn,
            user_id=42,
            outcome="keep",
            note=None,
        )
        self.assertIsNone(row)

    def test_updates_latest_dm_draft_evaluation(self):
        insert_episode_log_sync(
            self.conn,
            {
                "timestamp_utc": "2026-01-01T00:00:00+00:00",
                "user_id": 9,
                "tags": ["mode:dm_draft"],
                "input_excerpt": "x",
                "assistant_output_excerpt": "y",
                "implicit_signals": {"foo": "bar"},
            },
        )
        row = update_latest_dm_draft_evaluation_sync(
            self.conn,
            user_id=9,
            rubric_scores={
                "tone_fit": 2,
                "de_escalation": 1,
                "agency_respect": 2,
                "boundary_clarity": 1,
                "actionability": 2,
                "context_honesty": 2,
            },
            failure_tags=["too_vague"],
            note="solid tone",
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["episode_id"], 1)
        self.assertEqual(row["evaluation"]["rubric"]["tone_fit"], 2)
        self.assertEqual(row["evaluation"]["failure_tags"], ["too_vague"])

    def test_eval_returns_none_when_no_dm_episode(self):
        row = update_latest_dm_draft_evaluation_sync(
            self.conn,
            user_id=404,
            rubric_scores={"tone_fit": 1},
            failure_tags=[],
            note=None,
        )
        self.assertIsNone(row)

    def test_persists_first_class_target_fields(self):
        insert_episode_log_sync(
            self.conn,
            {
                "timestamp_utc": "2026-01-01T00:00:00+00:00",
                "user_id": 12,
                "tags": ["mode:dm_draft"],
                "input_excerpt": "dm target",
                "assistant_output_excerpt": "draft",
                "target_user_id": 345678901234567890,
                "target_display_name": "Caleb",
                "target_type": "member",
                "target_confidence": 0.75,
                "target_entity_key": "discord:345678901234567890",
                "mode_requested": "collab",
                "mode_inferred": "best_effort",
                "mode_used": "collab",
                "dm_guidelines_version": "dm_guidelines_v2",
                "dm_guidelines_source": "env_override",
                "blocking_collab": True,
                "critical_missing_fields": ["target", "objective"],
                "blocking_reason": "multiple_critical_missing",
                "draft_version": "1.1",
                "draft_variant_id": "primary",
                "prompt_fingerprint": "abc123deadbeef",
            },
        )
        rows = fetch_episode_logs_sync(self.conn, limit=1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["target_user_id"], 345678901234567890)
        self.assertEqual(rows[0]["target_display_name"], "Caleb")
        self.assertEqual(rows[0]["target_type"], "member")
        self.assertAlmostEqual(float(rows[0]["target_confidence"]), 0.75, places=6)
        self.assertEqual(rows[0]["target_entity_key"], "discord:345678901234567890")
        self.assertEqual(rows[0]["mode_requested"], "collab")
        self.assertEqual(rows[0]["mode_inferred"], "best_effort")
        self.assertEqual(rows[0]["mode_used"], "collab")
        self.assertEqual(rows[0]["dm_guidelines_version"], "dm_guidelines_v2")
        self.assertEqual(rows[0]["dm_guidelines_source"], "env_override")
        self.assertTrue(rows[0]["blocking_collab"])
        self.assertEqual(rows[0]["critical_missing_fields"], ["target", "objective"])
        self.assertEqual(rows[0]["blocking_reason"], "multiple_critical_missing")
        self.assertEqual(rows[0]["draft_version"], "1.1")
        self.assertEqual(rows[0]["draft_variant_id"], "primary")
        self.assertEqual(rows[0]["prompt_fingerprint"], "abc123deadbeef")


if __name__ == "__main__":
    unittest.main()
