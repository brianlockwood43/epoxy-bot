from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

try:
    from misc.discord_gates import message_in_allowed_channels
except ModuleNotFoundError:
    message_in_allowed_channels = None


@unittest.skipIf(message_in_allowed_channels is None, "discord.py not installed")
class DiscordGatesTests(unittest.TestCase):
    def test_dm_is_allowed_without_channel_allowlist(self):
        message = SimpleNamespace(
            guild=None,
            channel=SimpleNamespace(id=999),
        )
        self.assertTrue(message_in_allowed_channels(message, allowed_channel_ids={123}))

    def test_allowed_channel_is_allowed(self):
        message = SimpleNamespace(
            guild=SimpleNamespace(id=1),
            channel=SimpleNamespace(id=123),
        )
        self.assertTrue(message_in_allowed_channels(message, allowed_channel_ids={123}))

    def test_disallowed_channel_is_blocked(self):
        message = SimpleNamespace(
            guild=SimpleNamespace(id=1),
            channel=SimpleNamespace(id=999),
        )
        self.assertFalse(message_in_allowed_channels(message, allowed_channel_ids={123}))

    def test_thread_parent_allowlist_is_honored(self):
        class FakeThread:
            def __init__(self, channel_id: int, parent_id: int):
                self.id = int(channel_id)
                self.parent = SimpleNamespace(id=int(parent_id))

        message = SimpleNamespace(
            guild=SimpleNamespace(id=1),
            channel=FakeThread(channel_id=777, parent_id=123),
        )
        with mock.patch("misc.discord_gates.discord.Thread", FakeThread):
            self.assertTrue(message_in_allowed_channels(message, allowed_channel_ids={123}))


if __name__ == "__main__":
    unittest.main()
