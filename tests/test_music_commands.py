from __future__ import annotations

import unittest

try:
    import discord
    from discord.ext import commands
except ModuleNotFoundError:
    discord = None
    commands = None

if commands is not None:
    from misc.commands.command_deps import CommandDeps
    from misc.commands.command_deps import CommandGates
    from misc.commands.commands_music import register as register_music


@unittest.skipIf(commands is None, "discord.py not installed")
class MusicCommandsAuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_non_operator_blocked_from_transport_controls(self):
        class StubMusicService:
            text_channel_id = 123

            def disabled_reason(self):
                return None

            def in_music_text_channel(self, channel_id: int):
                return int(channel_id) == 123

            def is_operator(self, user_id: int):
                return False

        class FakeChannel:
            id = 123

            async def send(self, text):
                return None

        class FakeAuthor:
            id = 99

        class FakeGuild:
            id = 7

        class FakeCtx:
            def __init__(self):
                self.channel = FakeChannel()
                self.author = FakeAuthor()
                self.guild = FakeGuild()
                self.sent: list[str] = []

            async def send(self, text):
                self.sent.append(text)

        bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
        register_music(
            bot,
            deps=CommandDeps(
                send_chunked=lambda channel, text: None,
                music_service=StubMusicService(),
            ),
            gates=CommandGates(
                in_allowed_channel=lambda ctx: True,
                allowed_channel_ids={123},
                user_is_owner=lambda user: False,
            ),
        )

        for name in ("music.start", "music.stop", "music.skip", "music.pause", "music.resume", "music.clearqueue", "music.forcequeue"):
            cmd = bot.get_command(name)
            self.assertIsNotNone(cmd)
            ctx = FakeCtx()
            if name == "music.forcequeue":
                await cmd.callback(ctx, youtube_url="https://youtu.be/dQw4w9WgXcQ")
            else:
                await cmd.callback(ctx)
            self.assertTrue(any("operator-only" in s.lower() for s in ctx.sent), f"missing operator gate for {name}")

    async def test_queue_commands_blocked_outside_music_channel(self):
        class StubMusicService:
            text_channel_id = 123

            def disabled_reason(self):
                return None

            def in_music_text_channel(self, channel_id: int):
                return int(channel_id) == 123

            def is_operator(self, user_id: int):
                return True

        class FakeChannel:
            id = 999

            async def send(self, text):
                return None

        class FakeAuthor:
            id = 1

        class FakeCtx:
            def __init__(self):
                self.channel = FakeChannel()
                self.author = FakeAuthor()
                self.guild = object()
                self.sent: list[str] = []

            async def send(self, text):
                self.sent.append(text)

        bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
        register_music(
            bot,
            deps=CommandDeps(
                send_chunked=lambda channel, text: None,
                music_service=StubMusicService(),
            ),
            gates=CommandGates(
                in_allowed_channel=lambda ctx: True,
                allowed_channel_ids={123},
                user_is_owner=lambda user: False,
            ),
        )

        for name in ("music.queue", "music.queue_list", "music.now"):
            cmd = bot.get_command(name)
            self.assertIsNotNone(cmd)
            ctx = FakeCtx()
            if name == "music.queue":
                await cmd.callback(ctx, youtube_url="https://youtu.be/dQw4w9WgXcQ")
            elif name == "music.queue_list":
                await cmd.callback(ctx, 10)
            else:
                await cmd.callback(ctx)
            self.assertTrue(any("only available" in s.lower() for s in ctx.sent), f"missing channel gate for {name}")

    async def test_disabled_reason_is_returned_deterministically(self):
        class StubMusicService:
            text_channel_id = 123

            def disabled_reason(self):
                return "risk acknowledgment missing"

            def in_music_text_channel(self, channel_id: int):
                return True

            def is_operator(self, user_id: int):
                return True

        class FakeChannel:
            id = 123

            async def send(self, text):
                return None

        class FakeAuthor:
            id = 1

        class FakeCtx:
            def __init__(self):
                self.channel = FakeChannel()
                self.author = FakeAuthor()
                self.guild = object()
                self.sent: list[str] = []

            async def send(self, text):
                self.sent.append(text)

        bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
        register_music(
            bot,
            deps=CommandDeps(
                send_chunked=lambda channel, text: None,
                music_service=StubMusicService(),
            ),
            gates=CommandGates(
                in_allowed_channel=lambda ctx: True,
                allowed_channel_ids={123},
                user_is_owner=lambda user: False,
            ),
        )

        cmd = bot.get_command("music.queue")
        self.assertIsNotNone(cmd)
        ctx = FakeCtx()
        await cmd.callback(ctx, youtube_url="https://youtu.be/dQw4w9WgXcQ")
        self.assertTrue(any("music is disabled" in s.lower() for s in ctx.sent))


if __name__ == "__main__":
    unittest.main()
