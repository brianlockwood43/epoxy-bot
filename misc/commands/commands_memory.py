from __future__ import annotations

import asyncio
import json
import re

from discord.ext import commands
from memory.lifecycle_service import MemoryLifecycleError
from misc.commands.command_deps import CommandDeps
from misc.commands.command_deps import CommandGates


IMPORTANCE_TIER_MAP: dict[int, float] = {
    0: 0.0,
    1: 0.25,
    2: 0.5,
    3: 0.75,
    4: 1.0,
}


def _shorten(text: str, limit: int) -> str:
    clean = " ".join((text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 3)] + "..."


def _parse_memapprove_importance(raw_value: str) -> float:
    token = str(raw_value or "").strip()
    if not token:
        raise ValueError("importance token is empty")

    if re.fullmatch(r"[+-]?\d+", token):
        as_int = int(token)
        if 0 <= as_int <= 4:
            return float(IMPORTANCE_TIER_MAP[as_int])

    try:
        as_float = float(token)
    except Exception as exc:
        raise ValueError("invalid importance") from exc

    if as_float < 0.0:
        return 0.0
    if as_float > 1.0:
        return 1.0
    return float(as_float)


def _parse_memapprove_args(raw: str) -> tuple[int, list[str] | None, str | None, float | None, str | None, str | None]:
    text = (raw or "").strip()
    if not text:
        return (
            0,
            None,
            None,
            None,
            None,
            "Usage: `!memapprove <id> [tags=...] [topic=...] [importance=<0..4 or 0.0..1.0>] [note=...]`",
        )

    parts = text.split(maxsplit=1)
    try:
        memory_id = int(parts[0])
    except Exception:
        return (0, None, None, None, None, "First argument must be a memory id integer.")

    tail = parts[1] if len(parts) > 1 else ""
    tags: list[str] | None = None
    topic_id: str | None = None
    importance: float | None = None
    note: str | None = None

    m_tags = re.search(r"(?:^|\s)tags=([^\s]+)", tail)
    if m_tags:
        tags = [t.strip() for t in re.split(r"[;,]+", m_tags.group(1)) if t.strip()]

    m_topic = re.search(r"(?:^|\s)topic=([^\s]+)", tail)
    if m_topic:
        raw_topic = str(m_topic.group(1) or "").strip()
        topic_id = raw_topic or None

    m_imp = re.search(r"(?:^|\s)importance=([^\s]+)", tail)
    if m_imp:
        raw_imp = str(m_imp.group(1) or "").strip()
        try:
            importance = _parse_memapprove_importance(raw_imp)
        except ValueError:
            return (
                0,
                None,
                None,
                None,
                None,
                "Invalid `importance`; expected tier `0..4` or float `0.0..1.0`.",
            )

    m_note = re.search(r"(?:^|\s)note=(.+)$", tail)
    if m_note:
        note = str(m_note.group(1) or "").strip() or None

    return (memory_id, tags, topic_id, importance, note, None)


def _parse_memreject_args(raw: str) -> tuple[int, str | None, str | None]:
    text = (raw or "").strip()
    if not text:
        return (0, None, "Usage: `!memreject <id> [reason=...]`")

    parts = text.split(maxsplit=1)
    try:
        memory_id = int(parts[0])
    except Exception:
        return (0, None, "First argument must be a memory id integer.")

    tail = parts[1] if len(parts) > 1 else ""
    if not tail:
        return (memory_id, None, None)

    m_reason = re.search(r"(?:^|\s)reason=(.+)$", tail)
    if not m_reason:
        return (0, None, "Usage: `!memreject <id> [reason=...]`")
    reason = str(m_reason.group(1) or "").strip() or None
    return (memory_id, reason, None)


def register(
    bot: commands.Bot,
    *,
    deps: CommandDeps,
    gates: CommandGates,
) -> None:
    def _compose_scope_tokens(ctx: commands.Context, temporal_scope: str) -> str:
        temporal = (temporal_scope or "auto").strip().lower()
        if temporal not in {"hot", "warm", "cold", "auto"}:
            temporal = "auto"
        tokens = [temporal]
        try:
            if getattr(ctx, "channel", None) is not None and getattr(ctx.channel, "id", None) is not None:
                tokens.append(f"channel:{int(ctx.channel.id)}")
        except Exception:
            pass
        try:
            if getattr(ctx, "guild", None) is not None and getattr(ctx.guild, "id", None) is not None:
                tokens.append(f"guild:{int(ctx.guild.id)}")
        except Exception:
            pass
        return " ".join(tokens)

    @bot.command(name="memstage")
    async def memstage(ctx: commands.Context):
        if not gates.in_allowed_channel(ctx):
            return
        await ctx.send(
            f"Memory stage: **{deps.memory_stage}** (rank={deps.memory_stage_rank}) | "
            f"AUTO_CAPTURE={'1' if deps.auto_capture else '0'} | AUTO_SUMMARY={'1' if deps.auto_summary else '0'} | "
            f"REVIEW_MODE={deps.memory_review_mode}"
        )

    @bot.command(name="memreview")
    async def memreview_cmd(ctx: commands.Context, limit: int = 20):
        if not gates.in_allowed_channel(ctx):
            return
        if not gates.user_is_owner(ctx.author):
            await ctx.send("This command is owner-only.")
            return
        if deps.list_candidate_memories_sync is None:
            await ctx.send("Memory review service is not configured.")
            return

        lim = max(1, min(int(limit or 20), 100))
        async with deps.db_lock:
            rows = await asyncio.to_thread(
                deps.list_candidate_memories_sync,
                deps.db_conn,
                lim,
                0,
            )

        if not rows:
            await ctx.send("No candidate memories in review queue.")
            return

        lines = [f"Candidate memories (latest {len(rows)}):"]
        for row in rows:
            mem_id = int(row.get("id", 0))
            created = str(row.get("created_at_utc") or "?")
            scope = str(row.get("scope") or "global")
            importance = float(row.get("importance") or 0.0)
            topic = str(row.get("topic_id") or "-")
            text = _shorten(str(row.get("text") or ""), 80)
            lines.append(
                f"- #{mem_id} [{created}] scope={scope} imp={importance:.2f} topic={topic} :: {text}"
            )
        await deps.send_chunked(ctx.channel, "```\n" + "\n".join(lines)[:7000] + "\n```")

    @bot.command(name="memapprove")
    async def memapprove_cmd(ctx: commands.Context, *, raw: str = ""):
        if not gates.in_allowed_channel(ctx):
            return
        if not gates.user_is_owner(ctx.author):
            await ctx.send("This command is owner-only.")
            return
        if deps.approve_memory_sync is None or deps.get_or_create_person_sync is None:
            await ctx.send("Memory review service is not configured.")
            return

        memory_id, tags, topic_id, importance, note, parse_err = _parse_memapprove_args(raw)
        if parse_err:
            await ctx.send(parse_err)
            return

        person_origin = f"discord:{int(ctx.guild.id)}" if getattr(ctx, "guild", None) is not None else "discord:dm"
        try:
            async with deps.db_lock:
                actor_person_id = await asyncio.to_thread(
                    deps.get_or_create_person_sync,
                    deps.db_conn,
                    platform="discord",
                    external_id=str(int(ctx.author.id)),
                    origin=person_origin,
                    label="discord_user_id",
                )
                updated = await asyncio.to_thread(
                    deps.approve_memory_sync,
                    deps.db_conn,
                    memory_id=int(memory_id),
                    actor_person_id=int(actor_person_id),
                    tags=tags,
                    topic_id=topic_id,
                    importance=importance,
                    note=note,
                )
        except MemoryLifecycleError as exc:
            if exc.code == "not_found":
                await ctx.send(f"Memory #{int(memory_id)} not found.")
                return
            if exc.code == "not_candidate":
                await ctx.send(f"Memory #{int(memory_id)} must be `candidate` before approval.")
                return
            await ctx.send(f"Approve failed: {exc}")
            return
        except Exception as exc:
            await ctx.send(f"Approve failed: {exc}")
            return

        applied_bits = []
        if tags is not None:
            applied_bits.append(f"tags={updated.get('tags', [])}")
        if topic_id is not None:
            applied_bits.append(f"topic={updated.get('topic_id') or '(none)'}")
        applied_bits.append(f"importance={float(updated.get('importance') or 0.0):.2f}")
        if note is not None:
            applied_bits.append("note=updated")
        applied_txt = "; ".join(applied_bits) if applied_bits else "(no metadata edits)"

        await ctx.send(
            f"Approved memory #{int(updated.get('id') or memory_id)} -> lifecycle=active. {applied_txt}"
        )

    @bot.command(name="memreject")
    async def memreject_cmd(ctx: commands.Context, *, raw: str = ""):
        if not gates.in_allowed_channel(ctx):
            return
        if not gates.user_is_owner(ctx.author):
            await ctx.send("This command is owner-only.")
            return
        if deps.reject_memory_sync is None or deps.get_or_create_person_sync is None:
            await ctx.send("Memory review service is not configured.")
            return

        memory_id, reason, parse_err = _parse_memreject_args(raw)
        if parse_err:
            await ctx.send(parse_err)
            return

        person_origin = f"discord:{int(ctx.guild.id)}" if getattr(ctx, "guild", None) is not None else "discord:dm"
        try:
            async with deps.db_lock:
                actor_person_id = await asyncio.to_thread(
                    deps.get_or_create_person_sync,
                    deps.db_conn,
                    platform="discord",
                    external_id=str(int(ctx.author.id)),
                    origin=person_origin,
                    label="discord_user_id",
                )
                updated = await asyncio.to_thread(
                    deps.reject_memory_sync,
                    deps.db_conn,
                    memory_id=int(memory_id),
                    actor_person_id=int(actor_person_id),
                    reason=reason,
                )
        except MemoryLifecycleError as exc:
            if exc.code == "not_found":
                await ctx.send(f"Memory #{int(memory_id)} not found.")
                return
            if exc.code == "not_candidate":
                await ctx.send(f"Memory #{int(memory_id)} must be `candidate` before rejection.")
                return
            await ctx.send(f"Reject failed: {exc}")
            return
        except Exception as exc:
            await ctx.send(f"Reject failed: {exc}")
            return

        await ctx.send(
            f"Rejected memory #{int(updated.get('id') or memory_id)} -> lifecycle=deprecated."
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
        force_active = 0
        tags: list[str] = []
        text = raw

        if "tags=" in raw or "importance=" in raw or "text=" in raw or "force_active=" in raw:
            m_tags = re.search(r"tags=([^\s]+)", raw)
            m_imp = re.search(r"importance=([01])", raw)
            m_force = re.search(r"force_active=([01])", raw)
            m_text = re.search(r"text=(.+)$", raw)
            if m_tags:
                tags = re.split(r"[;,]+", m_tags.group(1))
            if m_imp:
                importance = int(m_imp.group(1))
            if m_force:
                force_active = int(m_force.group(1))
            if m_text:
                text = m_text.group(1).strip()
        elif "|" in raw:
            left, right = raw.split("|", 1)
            tags = re.split(r"[,\s]+", left.strip())
            text = right.strip()

        if force_active == 1 and not gates.user_is_owner(ctx.author):
            await ctx.send("`force_active=1` is owner-only.")
            return

        tags = deps.normalize_tags(tags)
        saved = await deps.remember_event_func(
            text=text,
            tags=tags,
            importance=importance,
            message=ctx.message,
            source_path="manual_remember",
            owner_override_active=(force_active == 1),
        )
        if not saved:
            await ctx.send("Nothing saved (empty text).")
            return
        mem_id = saved.get("id")
        lifecycle = str(saved.get("lifecycle") or "active")
        topic_id = saved.get("topic_id")
        topic_source = saved.get("topic_source")
        conf = saved.get("topic_confidence")
        conf_txt = f" conf={conf:.2f}" if isinstance(conf, float) else ""
        topic_txt = f" topic={topic_id} ({topic_source}{conf_txt})" if topic_id else " topic=(none)"
        await ctx.send(f"Saved memory #{mem_id} lifecycle={lifecycle} tags={tags} importance={importance}{topic_txt}")

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

        temporal_scope = deps.infer_scope(q) if deps.stage_at_least("M2") else "auto"
        scope = _compose_scope_tokens(ctx, temporal_scope)
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

        scope = _compose_scope_tokens(ctx, "auto")
        async with deps.db_lock:
            summary = await asyncio.to_thread(deps.get_topic_summary_sync, deps.db_conn, topic_id, scope, "topic_gist")
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

        scope = _compose_scope_tokens(ctx, "auto")
        await ctx.send(f"Summarizing topic **{topic_id}** (min_age_days={min_age_days})...")
        out = await deps.summarize_topic_func(topic_id, scope=scope, summary_type="topic_gist", min_age_days=min_age_days)
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

        person_origin = f"discord:{int(ctx.guild.id)}" if getattr(ctx, "guild", None) is not None else "discord:dm"
        async with deps.db_lock:
            person_id = await asyncio.to_thread(
                deps.get_or_create_person_sync,
                deps.db_conn,
                platform="discord",
                external_id=str(int(user_id)),
                origin=person_origin,
                label="discord_user_id",
            )
        tags = [deps.subject_person_tag(int(person_id)), deps.subject_user_tag(user_id), "profile"]
        res = await deps.remember_event_func(
            text=text,
            tags=tags,
            importance=1,
            message=ctx.message,
            topic_hint=None,
            source_path="manual_profile",
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
        scope = _compose_scope_tokens(ctx, "auto")
        events, summaries = await deps.recall_memory_func(q, scope=scope)
        txt = deps.format_memory_for_llm(events, summaries, max_chars=1800)
        await ctx.send(f"Recall results for: {q}\n{txt}"[:1900])
