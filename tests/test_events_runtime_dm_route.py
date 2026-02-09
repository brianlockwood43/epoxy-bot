from __future__ import annotations

import unittest

from misc.mention_routes import classify_mention_route
from misc.mention_routes import extract_dm_mode_payload


class EventsRuntimeDmRouteTests(unittest.TestCase):
    def test_extracts_dm_payload_colon(self):
        payload = extract_dm_mode_payload("dm: objective=hello; situation_context=world")
        self.assertEqual(payload, "objective=hello; situation_context=world")

    def test_extracts_dm_payload_space(self):
        payload = extract_dm_mode_payload("DM objective=hello")
        self.assertEqual(payload, "objective=hello")

    def test_non_dm_prompt_routes_default(self):
        self.assertEqual(classify_mention_route("what do you think"), "default")
        self.assertIsNone(extract_dm_mode_payload("what do you think"))

    def test_dm_prompt_routes_dm_draft(self):
        self.assertEqual(classify_mention_route("dm: make this calmer"), "dm_draft")


if __name__ == "__main__":
    unittest.main()
