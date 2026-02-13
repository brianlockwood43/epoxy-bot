from __future__ import annotations

import unittest

try:
    from misc.events_runtime import _compose_recall_scope
except ModuleNotFoundError:
    _compose_recall_scope = None


@unittest.skipIf(_compose_recall_scope is None, "discord.py not installed")
class EventsRuntimeScopeTests(unittest.TestCase):
    def test_compose_scope_with_channel_and_guild(self):
        scope = _compose_recall_scope(
            temporal_scope="warm",
            channel_id=123,
            guild_id=456,
        )
        self.assertEqual(scope, "warm channel:123 guild:456")

    def test_compose_scope_with_channel_only(self):
        scope = _compose_recall_scope(
            temporal_scope="hot",
            channel_id=321,
            guild_id=None,
        )
        self.assertEqual(scope, "hot channel:321")

    def test_compose_scope_normalizes_unknown_temporal(self):
        scope = _compose_recall_scope(
            temporal_scope="something_else",
            channel_id=None,
            guild_id=None,
        )
        self.assertEqual(scope, "auto")


if __name__ == "__main__":
    unittest.main()
