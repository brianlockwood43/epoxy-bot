from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
import unittest

from db.migrate import apply_sqlite_migrations

try:
    import discord
    from discord.ext import commands
except ModuleNotFoundError:
    discord = None
    commands = None

from memory.lifecycle_service import list_candidate_memories_sync
from memory.store import insert_memory_event_sync
from misc.commands.command_deps import CommandDeps
from misc.commands.command_deps import CommandGates

try:
    from misc.commands.commands_memory import register as register_memory
except ModuleNotFoundError:
    register_memory = None


def _safe_json_loads(raw: str):
    try:
        return json.loads(raw) if raw else []
    except Exception:
        return []


def _insert_memory(
    conn: sqlite3.Connection,
    *,
    lifecycle: str,
    text: str,
    tags: list[str] | None = None,
) -> int:
    payload = {
        "created_at_utc": "2026-02-15T10:00:00+00:00",
        "created_ts": int(time.time()),
        "scope": "global",
        "guild_id": 1,
        "channel_id": 123,
        "channel_name": "ops",
        "author_id": 99,
        "author_name": "tester",
        "source_message_id": 555,
        "lifecycle": lifecycle,
        "text": text,
        "tags_json": json.dumps(tags or []),
        "importance": 1,
        "tier": 1,
        "topic_id": None,
        "topic_source": "manual",
        "topic_confidence": None,
        "summarized": 0,
        "logged_from_channel_id": None,
        "logged_from_channel_name": None,
        "logged_from_message_id": None,
        "source_channel_id": None,
        "source_channel_name": None,
    }
    return insert_memory_event_sync(conn, payload, safe_json_loads=_safe_json_loads)


@unittest.skipIf(discord is None or commands is None or register_memory is None, "discord.py not installed")
class MemoryReviewCommandsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        intents = discord.Intents.none()
        self.bot = commands.Bot(command_prefix="!", intents=intents)
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        apply_sqlite_migrations(self.conn, os.path.join(os.getcwd(), "migrations"))
        self.db_lock = asyncio.Lock()
        self.sent_chunked: list[str] = []
        self.approve_calls: list[dict] = []
        self.reject_calls: list[dict] = []

        async def _send_chunked(_channel, text: str):
            self.sent_chunked.append(str(text))

        def _list_candidates(conn: sqlite3.Connection, limit: int = 20, offset: int = 0):
            return list_candidate_memories_sync(
                conn,
                limit=limit,
                offset=offset,
                safe_json_loads=_safe_json_loads,
            )

        def _approve_sync(_conn, **kwargs):
            self.approve_calls.append(dict(kwargs))
            returned_importance = kwargs.get("importance")
            if returned_importance is None:
                returned_importance = 0.5
            return {
                "id": int(kwargs["memory_id"]),
                "lifecycle": "active",
                "importance": returned_importance,
                "topic_id": kwargs.get("topic_id") or "",
                "tags": kwargs.get("tags") or [],
            }

        def _reject_sync(_conn, **kwargs):
            self.reject_calls.append(dict(kwargs))
            return {
                "id": int(kwargs["memory_id"]),
                "lifecycle": "deprecated",
            }

        self.deps = CommandDeps(
            db_lock=self.db_lock,
            db_conn=self.conn,
            send_chunked=_send_chunked,
            list_candidate_memories_sync=_list_candidates,
            approve_memory_sync=_approve_sync,
            reject_memory_sync=_reject_sync,
            get_or_create_person_sync=lambda _conn, **_kwargs: 42,
        )
        self.gates_owner = CommandGates(
            in_allowed_channel=lambda _ctx: True,
            allowed_channel_ids={123},
            user_is_owner=lambda _user: True,
            user_is_member=lambda _user: True,
        )
        register_memory(
            self.bot,
            deps=self.deps,
            gates=self.gates_owner,
        )

    async def asyncTearDown(self):
        await self.bot.close()
        self.conn.close()

    def _ctx(self):
        class FakeChannel:
            id = 123

        class FakeGuild:
            id = 1

        class FakeAuthor:
            id = 999

        class FakeMessage:
            id = 321
            mentions: list = []

        class FakeCtx:
            channel = FakeChannel()
            guild = FakeGuild()
            author = FakeAuthor()
            message = FakeMessage()

            def __init__(self):
                self.sent: list[str] = []

            async def send(self, text: str):
                self.sent.append(str(text))

        return FakeCtx()

    async def test_owner_gate_blocks_review_commands_for_non_owner(self):
        bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
        register_memory(
            bot,
            deps=self.deps,
            gates=CommandGates(
                in_allowed_channel=lambda _ctx: True,
                allowed_channel_ids={123},
                user_is_owner=lambda _user: False,
                user_is_member=lambda _user: True,
            ),
        )

        ctx = self._ctx()
        await bot.get_command("memreview").callback(ctx, 20)
        self.assertTrue(any("owner-only" in msg.lower() for msg in ctx.sent))

        ctx = self._ctx()
        await bot.get_command("memapprove").callback(ctx, raw="1")
        self.assertTrue(any("owner-only" in msg.lower() for msg in ctx.sent))

        ctx = self._ctx()
        await bot.get_command("memreject").callback(ctx, raw="1")
        self.assertTrue(any("owner-only" in msg.lower() for msg in ctx.sent))
        await bot.close()

    async def test_memreview_lists_candidate_items_only(self):
        candidate_id = _insert_memory(self.conn, lifecycle="candidate", text="candidate text")
        _insert_memory(self.conn, lifecycle="active", text="active text")

        ctx = self._ctx()
        await self.bot.get_command("memreview").callback(ctx, 20)
        rendered = "\n".join(self.sent_chunked)
        self.assertIn(f"#{candidate_id}", rendered)
        self.assertNotIn("active text", rendered)

    async def test_memapprove_parses_args_and_calls_service(self):
        ctx = self._ctx()
        await self.bot.get_command("memapprove").callback(
            ctx,
            raw="15 tags=ops,decision topic=governance importance=3 note=looks good",
        )
        self.assertEqual(len(self.approve_calls), 1)
        call = self.approve_calls[0]
        self.assertEqual(int(call["memory_id"]), 15)
        self.assertEqual(int(call["actor_person_id"]), 42)
        self.assertEqual(call["tags"], ["ops", "decision"])
        self.assertEqual(call["topic_id"], "governance")
        self.assertAlmostEqual(float(call["importance"]), 0.75, places=6)
        self.assertEqual(call["note"], "looks good")
        self.assertTrue(any("Approved memory #15" in msg for msg in ctx.sent))

    async def test_memapprove_accepts_float_importance(self):
        ctx = self._ctx()
        await self.bot.get_command("memapprove").callback(ctx, raw="15 importance=0.9")
        self.assertEqual(len(self.approve_calls), 1)
        call = self.approve_calls[0]
        self.assertAlmostEqual(float(call["importance"]), 0.9, places=6)

    async def test_memapprove_default_importance_when_omitted(self):
        ctx = self._ctx()
        await self.bot.get_command("memapprove").callback(ctx, raw="15")
        self.assertEqual(len(self.approve_calls), 1)
        call = self.approve_calls[0]
        self.assertIsNone(call["importance"])
        self.assertTrue(any("importance=0.50" in msg for msg in ctx.sent))

    async def test_memapprove_rejects_invalid_importance(self):
        ctx = self._ctx()
        await self.bot.get_command("memapprove").callback(ctx, raw="15 importance=abc")
        self.assertEqual(len(self.approve_calls), 0)
        self.assertTrue(any("importance" in msg.lower() for msg in ctx.sent))

    async def test_memreject_parses_reason_and_calls_service(self):
        ctx = self._ctx()
        await self.bot.get_command("memreject").callback(ctx, raw="23 reason=duplicate")
        self.assertEqual(len(self.reject_calls), 1)
        call = self.reject_calls[0]
        self.assertEqual(int(call["memory_id"]), 23)
        self.assertEqual(int(call["actor_person_id"]), 42)
        self.assertEqual(call["reason"], "duplicate")
        self.assertTrue(any("lifecycle=deprecated" in msg for msg in ctx.sent))


if __name__ == "__main__":
    unittest.main()
