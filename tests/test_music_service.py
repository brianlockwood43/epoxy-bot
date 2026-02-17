from __future__ import annotations

import unittest
from unittest import mock

try:
    from misc.adhoc_modules.music_service import MusicQueueItem
    from misc.adhoc_modules.music_service import MusicService
except ModuleNotFoundError:
    MusicQueueItem = None
    MusicService = None


if MusicService is not None:
    class _StubMusicService(MusicService):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self._metadata_map: dict[str, dict] = {}
            self._stream_map: dict[str, tuple[bool, str | None, str | None]] = {}

        async def fetch_video_metadata(self, canonical_url: str):
            payload = self._metadata_map.get(canonical_url)
            if payload is None:
                return (False, None, "missing metadata fixture")
            return (True, dict(payload), None)

        async def resolve_stream_url(self, canonical_url: str):
            return self._stream_map.get(canonical_url, (False, None, "missing stream fixture"))
else:  # pragma: no cover
    _StubMusicService = object


class _FakeVoiceClient:
    def __init__(self):
        self.connected = True
        self.playing = False
        self.paused = False
        self.after = None
        self.play_calls = 0
        self.stop_calls = 0
        self.disconnect_calls = 0
        self.channel = type("C", (), {"id": 555})()

    def is_connected(self):
        return bool(self.connected)

    def is_playing(self):
        return bool(self.playing)

    def is_paused(self):
        return bool(self.paused)

    def play(self, source, after):
        self.playing = True
        self.paused = False
        self.play_calls += 1
        self.after = after

    def stop(self):
        self.stop_calls += 1
        self.playing = False
        self.paused = False
        cb = self.after
        self.after = None
        if cb is not None:
            cb(None)

    def pause(self):
        if self.playing:
            self.playing = False
            self.paused = True

    def resume(self):
        if self.paused:
            self.paused = False
            self.playing = True

    async def disconnect(self, force=True):
        self.disconnect_calls += 1
        self.connected = False


class _FakeVoiceChannel:
    def __init__(self, channel_id: int, guild):
        self.id = int(channel_id)
        self.guild = guild

    async def connect(self):
        vc = _FakeVoiceClient()
        vc.channel = self
        self.guild.voice_client = vc
        return vc


class _FakeGuild:
    def __init__(self, guild_id: int, voice_channel_id: int):
        self.id = int(guild_id)
        self.voice_client = None
        self._channels = {int(voice_channel_id): _FakeVoiceChannel(voice_channel_id, self)}

    def get_channel(self, channel_id: int):
        return self._channels.get(int(channel_id))


class _FakeBot:
    def __init__(self, guild):
        self._guild = guild

    async def fetch_channel(self, channel_id: int):
        return self._guild.get_channel(int(channel_id))


def _service_factory(**overrides):
    base = dict(
        enabled=True,
        risk_ack="I_ACCEPT_YOUTUBE_RISK",
        text_channel_id=111,
        voice_channel_id=555,
        operator_user_ids={1},
        queue_max=25,
        max_per_user=3,
        queue_cooldown_seconds=0,
        idle_disconnect_seconds=30,
        yt_min_score=2,
        yt_allow_keywords=["lofi", "smooth jazz", "chillhop", "jazzhop", "study beats"],
        yt_deny_keywords=["hardstyle", "phonk"],
        min_duration_seconds=90,
        max_duration_seconds=7200,
        dry_run=False,
    )
    base.update(overrides)
    return _StubMusicService(**base)


@unittest.skipIf(MusicService is None, "music service dependencies missing")
class MusicServiceUnitTests(unittest.TestCase):
    def test_normalize_youtube_watch_and_short(self):
        svc = _service_factory()
        ok, canonical, vid, err = svc.normalize_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertTrue(ok, err)
        self.assertEqual(canonical, "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual(vid, "dQw4w9WgXcQ")

        ok2, canonical2, vid2, err2 = svc.normalize_youtube_url("https://youtu.be/dQw4w9WgXcQ")
        self.assertTrue(ok2, err2)
        self.assertEqual(canonical2, "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual(vid2, "dQw4w9WgXcQ")

    def test_normalize_rejects_playlist_link(self):
        svc = _service_factory()
        ok, _, _, err = svc.normalize_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=abc")
        self.assertFalse(ok)
        self.assertIn("playlist", (err or "").lower())

    def test_heuristic_accepts_lofi_music_metadata(self):
        svc = _service_factory()
        out = svc.evaluate_metadata_heuristic(
            {
                "title": "Lofi chillhop focus mix",
                "uploader": "Calm Channel",
                "description": "smooth jazz and lofi study beats",
                "tags": ["lofi", "study beats"],
                "categories": ["Music"],
                "duration": 300,
            }
        )
        self.assertTrue(out["passes"])
        self.assertGreaterEqual(out["score"], svc.yt_min_score)

    def test_heuristic_rejects_deny_keyword(self):
        svc = _service_factory()
        out = svc.evaluate_metadata_heuristic(
            {
                "title": "Lofi but hardstyle flip",
                "uploader": "Test",
                "description": "hardstyle remix",
                "tags": ["lofi", "hardstyle"],
                "categories": ["Music"],
                "duration": 240,
            }
        )
        self.assertFalse(out["passes"])
        self.assertGreater(len(out["deny_hits"]), 0)


@unittest.skipIf(MusicService is None, "music service dependencies missing")
class MusicServiceAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.yt_patch = mock.patch("misc.adhoc_modules.music_service.yt_dlp", object())
        self.yt_patch.start()

    async def asyncTearDown(self):
        self.yt_patch.stop()

    def _seed_metadata(self, svc: _StubMusicService, video_id: str, title: str):
        url = f"https://www.youtube.com/watch?v={video_id}"
        svc._metadata_map[url] = {
            "id": video_id,
            "title": title,
            "uploader": "Uploader",
            "description": "lofi chillhop smooth jazz",
            "tags": ["lofi", "chillhop"],
            "categories": ["Music"],
            "duration": 240,
        }
        return url

    async def test_queue_rejects_duplicate_video(self):
        svc = _service_factory()
        self._seed_metadata(svc, "dQw4w9WgXcQ", "Track One")

        ok1, _ = await svc.queue_youtube(raw_url="https://youtu.be/dQw4w9WgXcQ", submitted_by_user_id=10, force=False)
        ok2, msg2 = await svc.queue_youtube(raw_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ", submitted_by_user_id=11, force=False)
        self.assertTrue(ok1)
        self.assertFalse(ok2)
        self.assertIn("already in the queue", msg2.lower())

    async def test_queue_enforces_per_user_limit(self):
        svc = _service_factory(max_per_user=1, queue_cooldown_seconds=0)
        self._seed_metadata(svc, "dQw4w9WgXcQ", "Track One")
        self._seed_metadata(svc, "9bZkp7q19f0", "Track Two")

        ok1, _ = await svc.queue_youtube(raw_url="https://youtu.be/dQw4w9WgXcQ", submitted_by_user_id=22, force=False)
        ok2, msg2 = await svc.queue_youtube(raw_url="https://youtu.be/9bZkp7q19f0", submitted_by_user_id=22, force=False)
        self.assertTrue(ok1)
        self.assertFalse(ok2)
        self.assertIn("per-user", msg2.lower())

    async def test_queue_enforces_cooldown(self):
        svc = _service_factory(queue_cooldown_seconds=60, max_per_user=5)
        self._seed_metadata(svc, "dQw4w9WgXcQ", "Track One")
        self._seed_metadata(svc, "9bZkp7q19f0", "Track Two")

        ok1, _ = await svc.queue_youtube(raw_url="https://youtu.be/dQw4w9WgXcQ", submitted_by_user_id=33, force=False)
        ok2, msg2 = await svc.queue_youtube(raw_url="https://youtu.be/9bZkp7q19f0", submitted_by_user_id=33, force=False)
        self.assertTrue(ok1)
        self.assertFalse(ok2)
        self.assertIn("wait", msg2.lower())

    async def test_force_queue_bypasses_metadata_heuristic(self):
        svc = _service_factory()
        bad_url = "https://www.youtube.com/watch?v=J---aiyznGQ"
        svc._metadata_map[bad_url] = {
            "id": "J---aiyznGQ",
            "title": "Aggressive hardstyle",
            "uploader": "Nope",
            "description": "hardstyle",
            "tags": ["hardstyle"],
            "categories": ["Music"],
            "duration": 240,
        }

        ok1, _ = await svc.queue_youtube(raw_url=bad_url, submitted_by_user_id=44, force=True)
        self.assertTrue(ok1)

    async def test_start_connects_and_plays_first_track(self):
        svc = _service_factory(queue_cooldown_seconds=0)
        url = self._seed_metadata(svc, "dQw4w9WgXcQ", "Track One")
        svc._stream_map[url] = (True, "https://audio.local/one", None)
        await svc.queue_youtube(raw_url=url, submitted_by_user_id=50, force=False)

        guild = _FakeGuild(guild_id=1, voice_channel_id=555)
        bot = _FakeBot(guild)
        with mock.patch("misc.adhoc_modules.music_service.discord.FFmpegPCMAudio", return_value=object()):
            ok, _ = await svc.start(bot=bot, guild=guild, actor_user_id=1)
        self.assertTrue(ok)
        self.assertIsNotNone(guild.voice_client)
        self.assertEqual(guild.voice_client.play_calls, 1)
        self.assertIsNotNone(svc.current_item)

    async def test_resolve_failure_skips_to_next_track(self):
        svc = _service_factory(queue_cooldown_seconds=0)
        url1 = self._seed_metadata(svc, "dQw4w9WgXcQ", "Track One")
        url2 = self._seed_metadata(svc, "9bZkp7q19f0", "Track Two")
        svc._stream_map[url1] = (False, None, "boom")
        svc._stream_map[url2] = (True, "https://audio.local/two", None)
        await svc.queue_youtube(raw_url=url1, submitted_by_user_id=60, force=False)
        await svc.queue_youtube(raw_url=url2, submitted_by_user_id=61, force=False)

        guild = _FakeGuild(guild_id=1, voice_channel_id=555)
        bot = _FakeBot(guild)
        with mock.patch("misc.adhoc_modules.music_service.discord.FFmpegPCMAudio", return_value=object()):
            ok, _ = await svc.start(bot=bot, guild=guild, actor_user_id=1)
        self.assertTrue(ok)
        self.assertIsNotNone(svc.current_item)
        self.assertEqual(svc.current_item.video_id, "9bZkp7q19f0")
        self.assertEqual(guild.voice_client.play_calls, 1)

    async def test_skip_and_stop(self):
        svc = _service_factory(queue_cooldown_seconds=0)
        url = self._seed_metadata(svc, "dQw4w9WgXcQ", "Track One")
        svc._stream_map[url] = (True, "https://audio.local/one", None)
        await svc.queue_youtube(raw_url=url, submitted_by_user_id=70, force=False)

        guild = _FakeGuild(guild_id=1, voice_channel_id=555)
        bot = _FakeBot(guild)
        with mock.patch("misc.adhoc_modules.music_service.discord.FFmpegPCMAudio", return_value=object()):
            ok, _ = await svc.start(bot=bot, guild=guild, actor_user_id=1)
        self.assertTrue(ok)

        ok_skip, _ = await svc.skip(actor_user_id=1)
        self.assertTrue(ok_skip)
        self.assertGreaterEqual(guild.voice_client.stop_calls, 1)

        ok_stop, _ = await svc.stop(actor_user_id=1)
        self.assertTrue(ok_stop)
        self.assertEqual(len(svc.queue), 0)
        self.assertGreaterEqual(guild.voice_client.disconnect_calls, 1)


if __name__ == "__main__":
    unittest.main()
