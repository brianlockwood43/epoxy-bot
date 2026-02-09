from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import yaml

from db.migrate import apply_sqlite_migrations
from misc.adhoc_modules.announcements_service import AnnouncementService
from misc.adhoc_modules.announcements_service import WEEKDAY_KEYS
from misc.adhoc_modules.announcements_store import fetch_answers_sync


class _DummyCompletions:
    def __init__(self, text: str):
        self._text = text

    def create(self, *args, **kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self._text))])


class _DummyClient:
    def __init__(self, text: str = "Draft body"):
        self.chat = SimpleNamespace(completions=_DummyCompletions(text))


class _FakeBot:
    def __init__(self):
        self._channels: dict[int, _FakeChannel] = {}
        self._next_id = 1000

    def add_channel(self, ch):
        self._channels[int(ch.id)] = ch

    def next_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def get_channel(self, channel_id: int):
        return self._channels.get(int(channel_id))

    async def fetch_channel(self, channel_id: int):
        return self._channels.get(int(channel_id))


class _FakeChannel:
    def __init__(self, bot: _FakeBot, channel_id: int, *, guild=None, parent=None):
        self.bot = bot
        self.id = int(channel_id)
        self.guild = guild
        self.parent = parent
        self.sent: list[str] = []

    async def send(self, text: str):
        self.sent.append(text)
        return _FakeMessage(self.bot, self, self.bot.next_id())


class _FakeMessage:
    def __init__(self, bot: _FakeBot, channel: _FakeChannel, message_id: int):
        self.bot = bot
        self.channel = channel
        self.id = int(message_id)

    async def create_thread(self, name: str):
        thread = _FakeChannel(self.bot, self.bot.next_id(), parent=self.channel)
        self.bot.add_channel(thread)
        return thread


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _migrations_dir() -> str:
    return str(_repo_root() / "migrations")


def _build_templates(path: Path, *, prep_channel_id: int, enabled_days: dict[str, dict]):
    days = {}
    for key in WEEKDAY_KEYS:
        cfg = {
            "enabled": False,
            "target_channel_id": 0,
            "publish_time_local": "16:00",
            "tone": "clear",
            "structure": ["headline", "details"],
            "questions": [
                {"id": "headline", "prompt": "headline?", "required": True},
                {"id": "details", "prompt": "details?", "required": False},
            ],
        }
        if key in enabled_days:
            cfg.update(enabled_days[key])
        days[key] = cfg
    payload = {
        "timezone": "UTC",
        "prep_time_local": "00:00",
        "prep_channel_id": int(prep_channel_id),
        "prep_role_name": "",
        "days": days,
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _today_key() -> str:
    return WEEKDAY_KEYS[datetime.now(timezone.utc).date().weekday()]


def _tomorrow_key() -> str:
    return WEEKDAY_KEYS[(datetime.now(timezone.utc).date().weekday() + 1) % 7]


async def _recall_none(prompt: str, scope: str = "auto"):
    return ([], [])


def _fmt_memory(events, summaries, max_chars: int = 1700):
    return ""


class AnnouncementMigrationTests(unittest.TestCase):
    def test_migration_idempotent(self):
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        apply_sqlite_migrations(conn, _migrations_dir())
        apply_sqlite_migrations(conn, _migrations_dir())
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='announcement_cycles'")
        self.assertIsNotNone(cur.fetchone())


class AnnouncementServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self.tmp.name)
        self.templates_path = self.tmpdir / "announcement_templates.yml"

        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        apply_sqlite_migrations(self.conn, _migrations_dir())
        self.db_lock = asyncio.Lock()

        self.bot = _FakeBot()
        self.prep_channel = _FakeChannel(self.bot, 100)
        self.target_channel = _FakeChannel(self.bot, 200)
        self.bot.add_channel(self.prep_channel)
        self.bot.add_channel(self.target_channel)

    async def asyncTearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def _service(self, *, client_text: str = "Draft body", enabled_days: dict[str, dict]):
        _build_templates(self.templates_path, prep_channel_id=100, enabled_days=enabled_days)
        return AnnouncementService(
            db_lock=self.db_lock,
            db_conn=self.conn,
            client=_DummyClient(client_text),
            openai_model="gpt-5.1",
            stage_at_least=lambda stage: stage in {"M1", "M2", "M3"},
            recall_memory_func=_recall_none,
            format_memory_for_llm=_fmt_memory,
            utc_iso=lambda dt=None: (dt or datetime.now(timezone.utc)).isoformat(),
            templates_path=str(self.templates_path),
            enabled=True,
            timezone_name="UTC",
            prep_time_local="00:00",
            prep_channel_id=100,
            prep_role_name="",
            dry_run=False,
        )

    async def test_prep_ping_fires_once(self):
        svc = self._service(
            enabled_days={_tomorrow_key(): {"enabled": True, "target_channel_id": 200, "publish_time_local": "23:59"}}
        )
        await svc.run_tick(self.bot)
        await svc.run_tick(self.bot)
        self.assertEqual(len(self.prep_channel.sent), 1)

    async def test_answer_upsert(self):
        svc = self._service(
            enabled_days={_tomorrow_key(): {"enabled": True, "target_channel_id": 200, "publish_time_local": "23:59"}}
        )
        target_date = await svc.resolve_target_date(date_token=None, default_mode="tomorrow", channel_id=None)
        ok, _ = await svc.set_answer(
            target_date_local=target_date,
            question_id="headline",
            answer_text="First",
            actor_user_id=1,
            source_message_id=10,
        )
        self.assertTrue(ok)
        ok, _ = await svc.set_answer(
            target_date_local=target_date,
            question_id="headline",
            answer_text="Second",
            actor_user_id=1,
            source_message_id=11,
        )
        self.assertTrue(ok)
        cycle = await svc.fetch_cycle_by_date(target_date)
        rows = fetch_answers_sync(self.conn, int(cycle["id"]))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["answer_text"], "Second")

    async def test_generate_inserts_todo_for_missing_required(self):
        svc = self._service(
            client_text="Generated draft.",
            enabled_days={
                _tomorrow_key(): {
                    "enabled": True,
                    "target_channel_id": 200,
                    "publish_time_local": "23:59",
                    "questions": [
                        {"id": "headline", "prompt": "headline?", "required": True},
                        {"id": "details", "prompt": "details?", "required": True},
                    ],
                }
            },
        )
        target_date = await svc.resolve_target_date(date_token=None, default_mode="tomorrow", channel_id=None)
        ok, _ = await svc.set_answer(
            target_date_local=target_date,
            question_id="headline",
            answer_text="Headline set",
            actor_user_id=1,
            source_message_id=10,
        )
        self.assertTrue(ok)
        ok, _, draft = await svc.generate_draft(target_date_local=target_date, actor_user_id=1)
        self.assertTrue(ok)
        self.assertIn("TODO(details)", draft or "")

    async def test_approval_gate_enforced(self):
        svc = self._service(
            enabled_days={_tomorrow_key(): {"enabled": True, "target_channel_id": 200, "publish_time_local": "23:59"}}
        )
        target_date = await svc.resolve_target_date(date_token=None, default_mode="tomorrow", channel_id=None)
        ok, _ = await svc.approve(target_date_local=target_date, actor_user_id=1)
        self.assertFalse(ok)
        ok, _ = await svc.set_override(target_date_local=target_date, override_text="Manual text", actor_user_id=1)
        self.assertTrue(ok)
        ok, _ = await svc.approve(target_date_local=target_date, actor_user_id=1)
        self.assertTrue(ok)

    async def test_scheduled_post_exactly_once(self):
        svc = self._service(
            enabled_days={_today_key(): {"enabled": True, "target_channel_id": 200, "publish_time_local": "00:00"}}
        )
        today = await svc.resolve_target_date(date_token=None, default_mode="today", channel_id=None)
        ok, _ = await svc.set_override(target_date_local=today, override_text="Post me once", actor_user_id=1)
        self.assertTrue(ok)
        ok, _ = await svc.approve(target_date_local=today, actor_user_id=1)
        self.assertTrue(ok)
        await svc.run_tick(self.bot)
        await svc.run_tick(self.bot)
        self.assertEqual(len(self.target_channel.sent), 1)
        cycle = await svc.fetch_cycle_by_date(today)
        self.assertEqual(cycle["status"], "posted")

    async def test_done_self_suppresses_publish(self):
        svc = self._service(
            enabled_days={_today_key(): {"enabled": True, "target_channel_id": 200, "publish_time_local": "00:00"}}
        )
        today = await svc.resolve_target_date(date_token=None, default_mode="today", channel_id=None)
        await svc.set_override(target_date_local=today, override_text="Ready", actor_user_id=1)
        await svc.approve(target_date_local=today, actor_user_id=1)
        ok, _ = await svc.mark_done(target_date_local=today, mode="self", actor_user_id=1, link=None, note=None)
        self.assertTrue(ok)
        await svc.run_tick(self.bot)
        self.assertEqual(len(self.target_channel.sent), 0)
        cycle = await svc.fetch_cycle_by_date(today)
        self.assertEqual(cycle["status"], "manual_done")
        self.assertEqual(cycle["completion_path"], "manual_self_posted")

    async def test_done_draft_records_path(self):
        svc = self._service(
            enabled_days={_today_key(): {"enabled": True, "target_channel_id": 200, "publish_time_local": "23:59"}}
        )
        today = await svc.resolve_target_date(date_token=None, default_mode="today", channel_id=None)
        ok, _ = await svc.mark_done(target_date_local=today, mode="draft", actor_user_id=1, link=None, note=None)
        self.assertTrue(ok)
        cycle = await svc.fetch_cycle_by_date(today)
        self.assertEqual(cycle["completion_path"], "manual_draft_posted")

    async def test_undo_done_pre_and_post_cutoff(self):
        svc = self._service(
            enabled_days={_today_key(): {"enabled": True, "target_channel_id": 200, "publish_time_local": "23:59"}}
        )
        today = await svc.resolve_target_date(date_token=None, default_mode="today", channel_id=None)
        await svc.mark_done(target_date_local=today, mode="self", actor_user_id=1, link=None, note=None)
        ok, _ = await svc.undo_done(target_date_local=today, actor_user_id=1)
        self.assertTrue(ok)

        svc2 = self._service(
            enabled_days={_today_key(): {"enabled": True, "target_channel_id": 200, "publish_time_local": "00:00"}}
        )
        today2 = await svc2.resolve_target_date(date_token=None, default_mode="today", channel_id=None)
        await svc2.mark_done(target_date_local=today2, mode="self", actor_user_id=1, link=None, note=None)
        ok, msg = await svc2.undo_done(target_date_local=today2, actor_user_id=1)
        self.assertFalse(ok)
        self.assertIn("cutoff", msg.lower())


class AnnouncementCommandAuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_owner_only_commands_block_non_owner(self):
        try:
            import discord
            from discord.ext import commands
        except ModuleNotFoundError:
            self.skipTest("discord.py not installed")
            return

        from misc.commands.command_deps import CommandDeps
        from misc.commands.command_deps import CommandGates
        from misc.commands.commands_announcements import register as register_announcements

        class StubService:
            async def resolve_target_date(self, **kwargs):
                return "2026-01-01"

        class FakeChannel:
            id = 123

            async def send(self, text):
                return None

        class FakeAuthor:
            id = 99

        class FakeMessage:
            id = 456

        class FakeCtx:
            def __init__(self):
                self.channel = FakeChannel()
                self.author = FakeAuthor()
                self.message = FakeMessage()
                self.sent: list[str] = []

            async def send(self, text):
                self.sent.append(text)

        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        register_announcements(
            bot,
            deps=CommandDeps(
                announcement_service=StubService(),
                send_chunked=lambda channel, text: None,
            ),
            gates=CommandGates(
                in_allowed_channel=lambda ctx: True,
                allowed_channel_ids={123},
                user_is_owner=lambda user: False,
            ),
        )

        for name in ("announce.approve", "announce.done", "announce.undo_done", "announce.post_now"):
            cmd = bot.get_command(name)
            self.assertIsNotNone(cmd)
            ctx = FakeCtx()
            if name == "announce.done":
                await cmd.callback(ctx, raw="")
            else:
                await cmd.callback(ctx, "")
            self.assertTrue(any("owner-only" in s.lower() for s in ctx.sent))


if __name__ == "__main__":
    unittest.main()
