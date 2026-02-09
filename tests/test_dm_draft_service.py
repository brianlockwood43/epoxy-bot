from __future__ import annotations

import unittest

from controller.dm_draft_service import DmDraftVariant
from controller.dm_draft_service import compute_recall_coverage
from controller.dm_draft_service import compute_recall_provenance_counts
from controller.dm_draft_service import DmDraftRun
from controller.dm_draft_service import evaluate_collab_blocking
from controller.dm_draft_service import format_dm_result_for_discord
from controller.dm_draft_service import infer_completion_mode
from controller.dm_draft_service import parse_dm_result_from_model
from controller.dm_draft_service import select_mode
from controller.dm_draft_parser import DmDraftRequest


class DmDraftServiceTests(unittest.TestCase):
    def test_mode_inference_urgency_to_best_effort(self):
        text = "No time, just draft this ASAP!!! I'm cooked."
        self.assertEqual(infer_completion_mode(text), "best_effort")

    def test_mode_inference_reflective_to_collab(self):
        text = "Help me think this through and ask me what is missing."
        self.assertEqual(infer_completion_mode(text), "collab")

    def test_mode_inference_tie_defaults_best_effort(self):
        text = "help me think but also urgent"
        self.assertEqual(infer_completion_mode(text), "best_effort")

    def test_recall_coverage_thresholds(self):
        self.assertEqual(compute_recall_coverage(0)["level"], "thin")
        self.assertEqual(compute_recall_coverage(2)["level"], "thin")
        self.assertEqual(compute_recall_coverage(3)["level"], "mixed")
        self.assertEqual(compute_recall_coverage(7)["level"], "mixed")
        self.assertEqual(compute_recall_coverage(8)["level"], "rich")

    def test_recall_coverage_includes_provenance_counts(self):
        coverage = compute_recall_coverage(
            5,
            provenance_counts={
                "target_profile_count": 2,
                "recent_dm_count": 1,
                "public_interaction_count": 0,
                "notes_count": 3,
                "policy_count": 1,
            },
        )
        self.assertEqual(coverage["level"], "mixed")
        self.assertIn("provenance_counts", coverage)
        self.assertEqual(coverage["provenance_counts"]["notes_count"], 3)

    def test_compute_recall_provenance_counts(self):
        events = [
            {"id": 10, "tags": ["dm", "note"], "source_channel_name": "dm-thread"},
            {"id": 11, "tags": ["public"], "source_channel_name": "public-chat"},
            {"id": 12, "tags": ["policy"], "source_channel_name": "staff-room"},
        ]
        summaries = [
            {"id": 21, "tags": ["note"], "topic_id": "notes"},
            {"id": 22, "tags": ["policy"], "topic_id": "policy"},
        ]
        profile_events = [
            {"id": 31, "tags": ["profile", "subject:user:123"]},
            {"id": 32, "tags": ["profile", "subject:user:123"]},
        ]
        counts = compute_recall_provenance_counts(events, summaries, profile_events)
        self.assertEqual(counts["target_profile_count"], 2)
        self.assertEqual(counts["recent_dm_count"], 1)
        self.assertEqual(counts["public_interaction_count"], 1)
        self.assertEqual(counts["notes_count"], 2)
        self.assertEqual(counts["policy_count"], 2)

    def test_select_mode_uses_override_when_present(self):
        mode_used, mode_inferred = select_mode(
            mode_requested="collab",
            prompt_text="urgent no time do your best",
        )
        self.assertEqual(mode_used, "collab")
        self.assertEqual(mode_inferred, "best_effort")

    def test_select_mode_defaults_to_auto_heuristic(self):
        mode_used, mode_inferred = select_mode(
            mode_requested="auto",
            prompt_text="Help me think this through.",
        )
        self.assertEqual(mode_inferred, "collab")
        self.assertEqual(mode_used, "collab")

    def test_select_mode_auto_urgency_still_uses_collab(self):
        mode_used, mode_inferred = select_mode(
            mode_requested=None,
            prompt_text="No time, just draft this ASAP!!! I'm cooked.",
        )
        self.assertEqual(mode_inferred, "best_effort")
        self.assertEqual(mode_used, "collab")

    def test_collab_blocks_when_target_missing(self):
        req = DmDraftRequest(
            objective="de-escalate",
            situation_context="conflict in thread",
            my_goals=["trust"],
            non_negotiables=["no shaming"],
            tone="steady",
        )
        blocked, fields, reason = evaluate_collab_blocking(
            mode="collab",
            req=req,
            missing_fields=[],
            prompt_text=req.situation_context,
        )
        self.assertTrue(blocked)
        self.assertIn("target", fields)
        self.assertIn(reason, {"missing_target", "multiple_critical_missing"})

    def test_collab_blocks_when_objective_missing(self):
        req = DmDraftRequest(
            target="<@123456789012345678>",
            target_user_id=123456789012345678,
            objective="",
            situation_context="member upset after feedback",
            my_goals=["trust"],
            non_negotiables=["no shaming"],
            tone="steady",
        )
        blocked, fields, reason = evaluate_collab_blocking(
            mode="collab",
            req=req,
            missing_fields=["objective"],
            prompt_text=req.situation_context,
        )
        self.assertTrue(blocked)
        self.assertIn("objective", fields)
        self.assertIn(reason, {"missing_objective", "multiple_critical_missing"})

    def test_collab_blocks_missing_non_negotiables_when_boundary_context(self):
        req = DmDraftRequest(
            target="<@123456789012345678>",
            target_user_id=123456789012345678,
            objective="hold boundary",
            situation_context="There may be a safety violation and conflict escalation.",
            my_goals=["safety"],
            non_negotiables=[],
            tone="firm",
        )
        blocked, fields, reason = evaluate_collab_blocking(
            mode="collab",
            req=req,
            missing_fields=["non_negotiables"],
            prompt_text=req.situation_context,
        )
        self.assertTrue(blocked)
        self.assertIn("non_negotiables", fields)
        self.assertIn(reason, {"missing_non_negotiables_boundary_context", "multiple_critical_missing"})

    def test_collab_does_not_block_missing_non_negotiables_without_boundary_context(self):
        req = DmDraftRequest(
            target="<@123456789012345678>",
            target_user_id=123456789012345678,
            objective="repair tone",
            situation_context="A normal check-in after a rough week.",
            my_goals=["trust"],
            non_negotiables=[],
            tone="warm",
        )
        blocked, fields, reason = evaluate_collab_blocking(
            mode="collab",
            req=req,
            missing_fields=["non_negotiables"],
            prompt_text=req.situation_context,
        )
        self.assertFalse(blocked)
        self.assertEqual(fields, [])
        self.assertIsNone(reason)

    def test_result_shape_accepts_multi_draft(self):
        raw = """{
          "drafts": [
            {"id":"primary","label":"Primary","text":"Draft one","rationale":"why"},
            {"id":"alt","label":"Alternative","text":"Draft two","rationale":null}
          ],
          "risk_notes": ["n1"],
          "optional_tighten": "tighten"
        }"""
        result = parse_dm_result_from_model(
            raw,
            recall_coverage=compute_recall_coverage(5),
            assumptions_used=[],
        )
        self.assertEqual(len(result.drafts), 2)
        self.assertIsInstance(result.drafts[0], DmDraftVariant)
        self.assertEqual(result.drafts[1].text, "Draft two")

    def test_result_shape_always_has_at_least_one_draft(self):
        raw = '{"risk_notes":["a"]}'
        result = parse_dm_result_from_model(
            raw,
            recall_coverage=compute_recall_coverage(1),
            assumptions_used=[],
        )
        self.assertGreaterEqual(len(result.drafts), 1)

    def test_parse_result_salvages_unescaped_newlines_in_json(self):
        raw = (
            '{"drafts":[{"id":"primary","label":"Primary","text":"line one\nline two","rationale":null}],'
            '"risk_notes":["keep steady"],"optional_tighten":null}'
        )
        result = parse_dm_result_from_model(
            raw,
            recall_coverage=compute_recall_coverage(1),
            assumptions_used=["tone=steady"],
        )
        self.assertEqual(len(result.drafts), 1)
        self.assertIn("line one", result.drafts[0].text)

    def test_format_includes_assumptions_used_section(self):
        result = parse_dm_result_from_model(
            '{"drafts":[{"id":"primary","label":"Primary","text":"hello","rationale":null}]}',
            recall_coverage=compute_recall_coverage(1),
            assumptions_used=["tone=steady", "objective=de-escalate + align next step"],
        )
        run = DmDraftRun(
            result=result,
            mode="collab",
            parse_quality="partial",
            missing_fields=["objective", "tone"],
            assumptions_used=["tone=steady", "objective=de-escalate + align next step"],
            clarifying_questions=[],
            recall_count=1,
        )
        formatted = format_dm_result_for_discord(run)
        self.assertIn("Assumptions Used:", formatted)
        self.assertIn("tone=steady", formatted)


if __name__ == "__main__":
    unittest.main()
