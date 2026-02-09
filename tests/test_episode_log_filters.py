from __future__ import annotations

import unittest

from controller.episode_log_filters import should_log_episode


class EpisodeLogFilterTests(unittest.TestCase):
    def test_empty_filters_allows(self):
        ctx = {"caller_type": "member", "channel_policy_group": "member", "surface": "public_channel"}
        self.assertTrue(should_log_episode(set(), ctx))

    def test_context_filter_match(self):
        ctx = {"caller_type": "coach", "channel_policy_group": "staff", "surface": "coach_channel"}
        self.assertTrue(should_log_episode({"context:staff"}, ctx))
        self.assertFalse(should_log_episode({"context:leadership"}, ctx))

    def test_caller_filter_match(self):
        ctx = {"caller_type": "founder", "channel_policy_group": "leadership", "surface": "coach_channel"}
        self.assertTrue(should_log_episode({"caller:founder"}, ctx))
        self.assertFalse(should_log_episode({"caller:member"}, ctx))

    def test_surface_filter_match(self):
        ctx = {"caller_type": "member", "channel_policy_group": "dm", "surface": "dm"}
        self.assertTrue(should_log_episode({"surface:dm"}, ctx))
        self.assertFalse(should_log_episode({"surface:public_channel"}, ctx))

    def test_legacy_bare_tokens_work(self):
        ctx = {"caller_type": "member", "channel_policy_group": "member", "surface": "public_channel"}
        self.assertTrue(should_log_episode({"member"}, ctx))
        self.assertTrue(should_log_episode({"public_channel"}, ctx))
        self.assertFalse(should_log_episode({"leadership"}, ctx))

    def test_all_token(self):
        ctx = {"caller_type": "external", "channel_policy_group": "public", "surface": "public_channel"}
        self.assertTrue(should_log_episode({"all"}, ctx))


if __name__ == "__main__":
    unittest.main()
