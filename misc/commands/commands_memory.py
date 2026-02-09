from __future__ import annotations

import asyncio
import json
import re

from discord.ext import commands
from misc.commands.command_deps import CommandDeps
from misc.commands.command_deps import CommandGates


def register(
    bot: commands.Bot,
    *,
    deps: CommandDeps,
    gates: CommandGates,
) -> None:
    @bot.command(name="memstage")
    async def memstage(ctx: commands.Context):
        if not gates.in_allowed_channel(ctx):
            return
        await ctx.send(
            f"Memory stage: **{deps.memory_stage}** (rank={deps.memory_stage_rank}) | "
            f"AUTO_CAPTURE={'1' if deps.auto_capture else '0'} | AUTO_SUMMARY={'1' if deps.auto_summary else '0'}"
        )

    @bot.command(name="topics")
    async def topics_cmd(ctx: commands.Context, limit: int = 15):
        if not gates.in_allowed_channel(ctx):
            return
        lim = max(1, min(int(limit or 15), 30))

        allow = deps.topic_allowlist
        async with deps.db_lock:
            counts = await asyncio.to_thread(deps.topic_counts_sync, deps.db_conn, lim)
            known = await asyncio.to_thread(deps.list_known_topics_sync, deps.db_conn, 200)

        lines = []
        lines.append(f"TOPIC_SUGGEST={'1' if deps.topic_suggest else '0'} | TOPIC_MIN_CONF={deps.topic_min_conf:.2f}")
        if allow:
            lines.append(f"Allowlist ({len(allow)}): {', '.join(allow[:40])}")
        else:
            lines.append("Allowlist: (empty) - suggestions will use known topics only")

        if counts:
            lines.append("")
            lines.append("Top topics by count:")
            for topic_id, count in counts:
                lines.append(f"- {topic_id}: {count}")
        else:
            lines.append("")
            lines.append("No topic counts yet.")

        if (not allow) and known:
            lines.append("")
            lines.append(f"Known topics ({len(known)}): {', '.join(known[:40])}")

        body = "\n".join(lines)
        await deps.send_chunked(ctx.channel, f"```\n{body[:1700]}\n```")

    @bot.command(name="remember")
    async def remember_cmd(ctx: commands.Context, *, arg: str = ""):
        if not gates.in_allowed_channel(ctx):
            return
        if not deps.stage_at_least("M1"):
            await ctx.send("Memory stage is M0; set EPOXY_MEMORY_STAGE=M1+ to enable persistent memory.")
            return

        raw = (arg or "").strip()
        if not raw:
            await ctx.send("Usage: `!remember <tags> | <text>`  or  `!remember <text>`")
            return

        importance = 1
        tags: list[str] = []
        text = raw

        if "tags=" in raw or "importance=" in raw or "text=" in raw:
            m_tags = re.search(r"tags=([^\s]+)", raw)
            m_imp = re.search(r"importance=([01])", raw)
            m_text = re.search(r"text=(.+)$", raw)
            if m_tags:
                tags = re.split(r"[;,]+", m_tags.group(1))
            if m_imp:
                importance = int(m_imp.group(1))
            if m_text:
                text = m_text.group(1).strip()
        elif "|" in raw:
            left, right = raw.split("|", 1)
            tags = re.split(r"[,\s]+", left.strip())
            text = right.strip()

        tags = deps.normalize_tags(tags)
        saved = await deps.remember_event_func(text=text, tags=tags, importance=importance, message=ctx.message)
        if not saved:
            await ctx.send("Nothing saved (empty text).")
            return
        mem_id = saved.get("id")
        topic_id = saved.get("topic_id")
        topic_source = saved.get("topic_source")
        conf = saved.get("topic_confidence")
        conf_txt = f" conf={conf:.2f}" if isinstance(conf, float) else ""
        topic_txt = f" topic={topic_id} ({topic_source}{conf_txt})" if topic_id else " topic=(none)"
        await ctx.send(f"Saved memory #{mem_id} tags={tags} importance={importance}{topic_txt} 🧴")

    @bot.command(name="recall")
    async def recall_cmd(ctx: commands.Context, *, query: str = ""):
        if not gates.in_allowed_channel(ctx):
            return
        if not deps.stage_at_least("M1"):
            await ctx.send("Memory stage is M0; nothing to recall yet.")
            return

        q = (query or "").strip()
        if not q:
            await ctx.send("Usage: `!recall <query>`")
            return

        scope = deps.infer_scope(q) if deps.stage_at_least("M2") else "auto"
        events, summaries = await deps.recall_memory_func(q, scope=scope)

        pack = deps.format_memory_for_llm(events, summaries, max_chars=1700)
        await deps.send_chunked(ctx.channel, f"```\n{pack}\n```")

    @bot.command(name="topic")
    async def topic_cmd(ctx: commands.Context, topic_id: str = ""):
        if not gates.in_allowed_channel(ctx):
            return
        if not deps.stage_at_least("M3"):
            await ctx.send("Memory stage is not M3; topic summaries are disabled.")
            return
        topic_id = (topic_id or "").strip().lower()
        if not topic_id:
            await ctx.send("Usage: `!topic <topic_id>`")
            return

        async with deps.db_lock:
            summary = await asyncio.to_thread(deps.get_topic_summary_sync, deps.db_conn, topic_id)
        if not summary:
            await ctx.send(f"No summary found for topic '{topic_id}'.")
            return

        pack = f"[topic={summary['topic_id']}] updated={summary.get('updated_at_utc','')}\n{summary['summary_text']}"
        await deps.send_chunked(ctx.channel, f"```\n{pack[:1700]}\n```")

    @bot.command(name="summarize")
    async def summarize_cmd(ctx: commands.Context, topic_id: str = "", min_age_days: int = 14):
        if not gates.in_allowed_channel(ctx):
            return
        if not deps.stage_at_least("M3"):
            await ctx.send("Memory stage is not M3; summaries are disabled.")
            return
        topic_id = (topic_id or "").strip().lower()
        if not topic_id:
            await ctx.send("Usage: `!summarize <topic_id> [min_age_days]`")
            return

        await ctx.send(f"Summarizing topic **{topic_id}** (min_age_days={min_age_days})...")
        out = await deps.summarize_topic_func(topic_id, min_age_days=min_age_days)
        await deps.send_chunked(ctx.channel, f"```\n{out[:1700]}\n```")

    @bot.command(name="profile")
    async def cmd_profile(ctx, *, raw: str = ""):
        if not raw:
            await ctx.send("Usage: !profile @User | text")
            return
        if ctx.channel.id not in gates.allowed_channel_ids:
            return
        if "|" not in raw:
            await ctx.send("Usage: !profile @User | text")
            return

        left, text = [s.strip() for s in raw.split("|", 1)]
        if not text:
            await ctx.send("Usage: !profile @User | text")
            return

        user_id = None
        if ctx.message.mentions:
            user_id = ctx.message.mentions[0].id
        else:
            m = re.search(r"\b(\d{8,20})\b", left)
            if m:
                user_id = int(m.group(1))

        if not user_id:
            await ctx.send("Couldn't find a user. Usage: !profile @User | text")
            return

        tags = [deps.subject_user_tag(user_id), "profile"]
        res = await deps.remember_event_func(
            text=text,
            tags=tags,
            importance=1,
            message=ctx.message,
            topic_hint=None,
        )

        if not res:
            await ctx.send("Profile memory not saved (stage may be < M1).")
            return

        await ctx.send(f"Saved profile memory for <@{user_id}>.")

    def _debug_last_memories_sync(conn, n: int):
        cur = conn.cursor()
        cur.execute("SELECT id, text, tags_json, topic_id FROM memory_events ORDER BY id DESC LIMIT ?", (int(n),))
        out = []
        for memory_id, text, tags, topic_id in cur.fetchall():
            out.append(
                {
                    "id": memory_id,
                    "text": text or "",
                    "tags": json.loads(tags or "[]"),
                    "topic_id": topic_id or "",
                }
            )
        return out

    @bot.command(name="memlast")
    async def cmd_memlast(ctx, n: int = 5):
        if ctx.channel.id not in gates.allowed_channel_ids:
            return
        async with deps.db_lock:
            rows = await asyncio.to_thread(_debug_last_memories_sync, deps.db_conn, int(n))
        lines = ["Last memories:"] + [f"- #{r['id']} topic={r['topic_id']} tags={r['tags']}\n  {r['text'][:120]}" for r in rows]
        await ctx.send("\n".join(lines)[:1900])

    @bot.command(name="memfind")
    async def cmd_memfind(ctx, *, q: str):
        if ctx.channel.id not in gates.allowed_channel_ids:
            return
        events, summaries = await deps.recall_memory_func(q, scope="auto")
        txt = deps.format_memory_for_llm(events, summaries, max_chars=1800)
        await ctx.send(f"Recall results for: {q}\n{txt}"[:1900])
