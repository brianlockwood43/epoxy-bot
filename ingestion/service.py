from __future__ import annotations

import asyncio
import re
from typing import Any

from memory.tagging import normalize_memory_tags


async def log_message(
    message: Any,
    *,
    db_lock,
    db_conn,
    insert_message_sync,
) -> None:
    attachments = ""
    if getattr(message, "attachments", None):
        attachments = " | ".join(a.url for a in message.attachments if a.url)

    guild = message.guild
    payload = {
        "message_id": message.id,
        "guild_id": guild.id if guild else None,
        "guild_name": guild.name if guild else None,
        "channel_id": message.channel.id,
        "channel_name": getattr(message.channel, "name", str(message.channel)),
        "author_id": message.author.id,
        "author_name": str(message.author),
        "created_at_utc": message.created_at.isoformat() if message.created_at else "",
        "content": message.content or "",
        "attachments": attachments,
    }

    async with db_lock:
        await asyncio.to_thread(insert_message_sync, db_conn, payload)


async def maybe_auto_capture(
    message: Any,
    *,
    auto_capture: bool,
    stage_at_least,
    remember_event_func,
) -> None:
    if not (auto_capture and stage_at_least("M1")):
        return
    content = (message.content or "").strip()
    if not content:
        return

    m = re.match(r"^(decision|policy|canon|profile)\s*(\(([^)]+)\))?\s*:\s*(.+)$", content, flags=re.I)
    if m:
        kind = m.group(1).lower()
        topic = (m.group(3) or "").strip()
        text = (m.group(4) or "").strip()
        tags = normalize_memory_tags([kind], preserve_legacy=True)
        if topic:
            tags = normalize_memory_tags([topic] + tags, preserve_legacy=True)
        await remember_event_func(
            text=text,
            tags=tags,
            importance=1,
            message=message,
            topic_hint=topic if topic else None,
            source_path="auto_capture",
        )
        return

    m2 = re.match(r"^#mem\s+([a-zA-Z0-9_\-]{3,})\s*:\s*(.+)$", content)
    if m2:
        topic = m2.group(1).strip().lower()
        text = (m2.group(2) or "").strip()
        await remember_event_func(
            text=text,
            tags=normalize_memory_tags([topic], preserve_legacy=True),
            importance=1,
            message=message,
            topic_hint=topic,
            source_path="auto_capture",
        )
        return


async def backfill_channel(
    channel: Any,
    *,
    allowed_channel_ids: set[int],
    bootstrap_channel_reset: bool,
    reset_backfill_done_func,
    is_backfill_done_func,
    backfill_limit: int,
    bootstrap_backfill_capture: bool,
    stage_at_least,
    log_message_func,
    maybe_auto_capture_func,
    backfill_pause_every: int,
    backfill_pause_seconds: float,
    bot_user: Any | None,
    mark_backfill_done_func,
) -> None:
    if not hasattr(channel, "id"):
        return

    channel_id = channel.id
    if channel_id not in allowed_channel_ids:
        return

    if bootstrap_channel_reset:
        await reset_backfill_done_func(channel_id)

    if await is_backfill_done_func(channel_id):
        return

    print(
        f"[Backfill] Starting channel {channel_id} ({getattr(channel, 'name', 'unknown')}) "
        f"limit={backfill_limit} bootstrap_capture={bootstrap_backfill_capture}"
    )

    count = 0
    captured = 0
    try:
        async for msg in channel.history(limit=backfill_limit, oldest_first=True):
            if msg.author.bot and bot_user and msg.author.id != bot_user.id:
                continue

            await log_message_func(msg)

            if bootstrap_backfill_capture and stage_at_least("M1"):
                try:
                    await maybe_auto_capture_func(msg)
                    captured += 1
                except Exception as e:
                    print(f"[AutoCapture] Error: {e}")

            count += 1
            if count % max(1, int(backfill_pause_every)) == 0:
                await asyncio.sleep(float(backfill_pause_seconds))
    except Exception as e:
        print(f"[Backfill] Error in channel {channel_id}: {e}")
        return

    await mark_backfill_done_func(channel_id)
    print(f"[Backfill] Done channel {channel_id}. Logged {count} messages. BootstrapProcessed={captured}")
