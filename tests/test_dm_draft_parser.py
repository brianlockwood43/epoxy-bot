from __future__ import annotations

import unittest

from controller.dm_draft_parser import parse_dm_draft_request


class DmDraftParserTests(unittest.TestCase):
    def test_parses_key_value_single_line(self):
        text = (
            "target=<@123456789012345678>; objective=De-escalate this thread; "
            "situation_context=Member is upset about feedback style; "
            "my_goals=build trust|support accountability; "
            "non_negotiables=no shaming|no mind reading; tone=steady"
        )
        parsed = parse_dm_draft_request(text)
        req = parsed.request
        self.assertEqual(parsed.parse_quality, "full")
        self.assertEqual(req.target_user_id, 123456789012345678)
        self.assertEqual(req.objective, "De-escalate this thread")
        self.assertEqual(req.tone, "steady")
        self.assertEqual(req.my_goals, ["build trust", "support accountability"])
        self.assertEqual(req.non_negotiables, ["no shaming", "no mind reading"])

    def test_parses_multiline_lists(self):
        text = """
objective: Hold boundary while preserving trust
situation_context:
  Member said coaching felt dismissive.
my_goals:
- Keep relationship intact
- Reinforce growth direction
non_negotiables:
- no shaming
- no moralizing
tone: warm-direct
""".strip()
        parsed = parse_dm_draft_request(text)
        req = parsed.request
        self.assertEqual(parsed.parse_quality, "full")
        self.assertIn("dismissive", req.situation_context)
        self.assertEqual(req.my_goals, ["Keep relationship intact", "Reinforce growth direction"])
        self.assertEqual(req.non_negotiables, ["no shaming", "no moralizing"])

    def test_partial_missing_fields_deterministic(self):
        text = "objective: Clear the air quickly\nsituation_context: We had conflict in DMs."
        parsed = parse_dm_draft_request(text)
        self.assertEqual(parsed.parse_quality, "partial")
        self.assertEqual(parsed.missing_fields, ["my_goals", "non_negotiables", "tone"])

    def test_insufficient_when_objective_and_context_missing(self):
        parsed = parse_dm_draft_request("tone=direct")
        self.assertEqual(parsed.parse_quality, "insufficient")
        self.assertIn("objective", parsed.missing_fields)
        self.assertIn("situation_context", parsed.missing_fields)

    def test_parses_mode_override_colon(self):
        parsed = parse_dm_draft_request(
            "objective: x\nsituation_context: y\nmy_goals: a\nnon_negotiables: b\ntone: steady\nmode: collab"
        )
        self.assertEqual(parsed.request.mode, "collab")

    def test_parses_mode_override_equals(self):
        parsed = parse_dm_draft_request(
            "objective=x; situation_context=y; my_goals=a; non_negotiables=b; tone=steady; mode=best_effort"
        )
        self.assertIsNone(parsed.request.mode)

    def test_invalid_mode_ignored(self):
        parsed = parse_dm_draft_request(
            "objective=x; situation_context=y; my_goals=a; non_negotiables=b; tone=steady; mode=wild"
        )
        self.assertIsNone(parsed.request.mode)


if __name__ == "__main__":
    unittest.main()
