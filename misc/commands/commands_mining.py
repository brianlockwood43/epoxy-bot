from __future__ import annotations

import asyncio
import json
from datetime import timedelta

import discord
from discord.ext import commands
from memory.tagging import normalize_memory_tags
from misc.commands.command_deps import CommandDeps
from misc.commands.command_deps import CommandGates


def register(
    bot: commands.Bot,
    *,
    deps: CommandDeps,
    gates: CommandGates,
) -> None:
    @bot.command(name="mine")
    async def cmd_mine(ctx, *args):
        if ctx.channel.id not in gates.allowed_channel_ids:
            await ctx.send("This command isn't enabled in this channel.")
            return

        if not deps.stage_at_least("M1"):
            await ctx.send("Memory is not enabled (stage < M1).")
            return

        target_channel_id = ctx.channel.id
        limit = 200

        if len(args) >= 1:
            maybe_ch = deps.parse_channel_id_token(args[0])
            if maybe_ch:
                target_channel_id = maybe_ch
                if len(args) >= 2 and str(args[1]).isdigit():
                    limit = max(50, min(500, int(args[1])))
            elif str(args[0]).isdigit():
                limit = max(50, min(500, int(args[0])))

        if target_channel_id not in gates.allowed_channel_ids:
            await ctx.send("That channel is not in Epoxy's allowlist, so I won't mine it.")
            return

        target_channel_name = None
        ch_obj = bot.get_channel(target_channel_id)
        if ch_obj is None:
            try:
                ch_obj = await bot.fetch_channel(target_channel_id)
            except Exception:
                ch_obj = None
        if ch_obj is not None:
            target_channel_name = getattr(ch_obj, "name", None) or str(ch_obj)

        hot_minutes = None
        for a in args:
            hm = deps.parse_duration_to_minutes(str(a))
            if hm is not None:
                hot_minutes = max(5, min(240, hm))
                break

        if hot_minutes is not None:
            since_dt = discord.utils.utcnow() - timedelta(minutes=hot_minutes)
            since_iso = since_dt.isoformat()
            async with deps.db_lock:
                rows = await asyncio.to_thread(
                    deps.fetch_messages_since_sync,
                    deps.db_conn,
                    target_channel_id,
                    since_iso,
                    500,
                )
            mode_label = f"hot({hot_minutes}m)"
        else:
            async with deps.db_lock:
                rows = await asyncio.to_thread(deps.fetch_latest_messages_sync, deps.db_conn, target_channel_id, limit)
            mode_label = f"last({limit})"

        if not rows:
            await ctx.send("No messages found to mine for that channel.")
            return

        window_text = deps.format_recent_context(rows, max_chars=12000, max_line_chars=350)
        allowlist = deps.topic_allowlist[:] if deps.topic_allowlist else []
        allowlist_str = ", ".join(allowlist) if allowlist else "(none; use null topic_id)"

        extraction_instructions = f"""
You are Epoxy's memory miner.

You will be given a block of Discord messages from ONE channel.
Extract durable, high-signal MEMORY EVENTS only. Do NOT extract chatter unless you are extracting an inside joke, social pattern, or another similar abstraction.

Return a JSON ARRAY ONLY (no markdown, no commentary), with 0-12 items.
Each item must be an object with EXACT keys:
- "text": string (max 240 chars), the memory content written as a standalone statement
- "kind": one of ["decision","policy","canon","profile","proposal","insight","task"]
- "topic_id": either null OR one of this allowlist: [{allowlist_str}]
- "importance": 0 or 1 (1 only if it will matter weeks later)
- "confidence": number 0.0-1.0

Rules:
- Do NOT invent channel names, dates, authors, or message ids. Do NOT include them in "text".
- If you cannot confidently assign a topic_id from allowlist, use null.
- Avoid duplicates / near-duplicates.
- Prefer writing memories in a neutral factual style.
- Only produce "profile" if the text is a stable trait or preference about an individual AND the individual's name appears in the window text.
  For profile items, include the person's name inside "text" (e.g., "Sammy prefers ..."). Still no invented IDs.
""".strip()

        try:
            resp = deps.client.chat.completions.create(
                model=deps.openai_model,
                messages=[
                    {"role": "system", "content": extraction_instructions[:1900]},
                    {"role": "user", "content": f"Channel window:\n{window_text}"[:12000]},
                ],
            )
            raw = (resp.choices[0].message.content or "").strip()
        except Exception as e:
            await ctx.send(f"Mine failed (LLM error): {e}")
            return

        items = deps.extract_json_array(raw)
        if not items:
            await ctx.send("Mine produced no usable JSON items.")
            return

        allowed_kinds = {"decision", "policy", "canon", "profile", "proposal", "insight", "task"}
        allow_topics = set(deps.topic_allowlist or [])
        saved = 0
        topics_used: dict[str, int] = {}

        for it in items:
            try:
                text = (it.get("text") or "").strip()
                kind = (it.get("kind") or "").strip().lower()
                topic_id = it.get("topic_id", None)
                importance = int(it.get("importance", 0))
                conf = float(it.get("confidence", 0.0))
            except Exception:
                continue

            if not text:
                continue
            if kind not in allowed_kinds:
                kind = "insight"
            importance = 1 if importance == 1 else 0

            if isinstance(topic_id, str):
                topic_id = topic_id.strip().lower()
                if topic_id not in allow_topics:
                    topic_id = None
            else:
                topic_id = None

            if conf < 0.55:
                continue

            tags = normalize_memory_tags([kind], preserve_legacy=True)
            if topic_id:
                tags = normalize_memory_tags([topic_id] + tags, preserve_legacy=True)

            res = await deps.remember_event_func(
                text=text,
                tags=tags,
                importance=importance,
                message=ctx.message,
                topic_hint=topic_id,
                source_path="mining",
            )
            if not res:
                continue

            await deps.set_memory_origin_func(int(res["id"]), target_channel_id, target_channel_name)

            saved += 1
            if topic_id:
                topics_used[topic_id] = topics_used.get(topic_id, 0) + 1

        topic_summary = ", ".join(f"{k}x{v}" for k, v in sorted(topics_used.items(), key=lambda x: (-x[1], x[0])))
        if not topic_summary:
            topic_summary = "(none)"

        await ctx.send(
            f"Mined {len(rows)} msgs ({mode_label}) from <#{target_channel_id}> -> saved {saved} memories. Topics: {topic_summary}"
        )

    @bot.command(name="ctxpeek")
    async def ctxpeek(ctx: commands.Context, n: int = 10):
        if not gates.in_allowed_channel(ctx):
            return
        n = max(1, min(int(n), 40))
        before = 2**63 - 1
        async with deps.db_lock:
            rows = await asyncio.to_thread(deps.fetch_recent_context_sync, deps.db_conn, ctx.channel.id, before, n)
        txt = deps.format_recent_context(rows, 1900, deps.max_line_chars)
        await ctx.send(f"Recent context ({len(rows)} rows):\n{txt}")

    @bot.command(name="topicsuggest")
    async def cmd_topicsuggest(ctx, *args):
        if ctx.channel.id not in gates.allowed_channel_ids:
            await ctx.send("This command isn't enabled in this channel.")
            return

        mode = "messages"
        for a in args:
            if str(a).strip().lower() in {"mem", "memory", "memories"}:
                mode = "memories"
                break

        target_channel_id = ctx.channel.id
        limit = 250

        if len(args) >= 1:
            maybe_ch = deps.parse_channel_id_token(str(args[0]))
            if maybe_ch:
                target_channel_id = maybe_ch
                if len(args) >= 2 and str(args[1]).isdigit():
                    limit = max(50, min(500, int(args[1])))
            elif str(args[0]).isdigit():
                limit = max(50, min(500, int(args[0])))

        if target_channel_id not in gates.allowed_channel_ids:
            await ctx.send("That channel is not in Epoxy's allowlist, so I won't analyze it.")
            return

        hot_minutes = None
        for a in args:
            hm = deps.parse_duration_to_minutes(str(a))
            if hm is not None:
                hot_minutes = max(5, min(240, hm))
                break

        target_channel_name = None
        ch_obj = bot.get_channel(target_channel_id)
        if ch_obj is None:
            try:
                ch_obj = await bot.fetch_channel(target_channel_id)
            except Exception:
                ch_obj = None
        if ch_obj is not None:
            target_channel_name = getattr(ch_obj, "name", None) or str(ch_obj)

        if mode == "memories":
            if hot_minutes is not None:
                since_dt = discord.utils.utcnow() - timedelta(minutes=hot_minutes)
                since_iso = since_dt.isoformat()
                async with deps.db_lock:
                    mem_rows = await asyncio.to_thread(deps.fetch_memory_events_since_sync, deps.db_conn, since_iso, 400)
                mode_label = f"mem_hot({hot_minutes}m)"
            else:
                async with deps.db_lock:
                    mem_rows = await asyncio.to_thread(deps.fetch_latest_memory_events_sync, deps.db_conn, 300)
                mode_label = "mem_last(300)"

            if not mem_rows:
                await ctx.send("No memory events found to analyze.")
                return

            window_text = deps.format_memory_events_window(mem_rows, max_chars=12000)
            source_label = "MEMORY EVENTS (already curated)"
        else:
            if hot_minutes is not None:
                since_dt = discord.utils.utcnow() - timedelta(minutes=hot_minutes)
                since_iso = since_dt.isoformat()
                async with deps.db_lock:
                    rows = await asyncio.to_thread(deps.fetch_messages_since_sync, deps.db_conn, target_channel_id, since_iso, 500)
                mode_label = f"msg_hot({hot_minutes}m)"
            else:
                async with deps.db_lock:
                    rows = await asyncio.to_thread(deps.fetch_latest_messages_sync, deps.db_conn, target_channel_id, limit)
                mode_label = f"msg_last({limit})"

            if not rows:
                await ctx.send("No messages found to analyze.")
                return

            window_text = deps.format_recent_context(rows, max_chars=12000, max_line_chars=450)
            source_label = "RAW MESSAGES (chat log)"

        existing = set(deps.topic_allowlist or [])
        existing_str = ", ".join(sorted(existing)) if existing else "(none)"

        prompt = f"""
You are Epoxy's topic curator.

Goal: propose NEW topic_ids to add to an allowlist for organizing memories.
You will be given either Discord message logs or memory event entries.

Return a JSON ARRAY ONLY (no markdown, no commentary), with 0-8 items.
Each item must have EXACT keys:
- "topic_id": snake_case string, 3-24 chars, [a-z0-9_], must NOT already exist
- "label": short human label
- "why": 1 sentence why this topic is distinct/useful
- "examples": array of 2-3 short phrases quoted/paraphrased from the window (no invention)
- "confidence": number 0.0-1.0

HARD RULES:
- Do NOT propose any topic_id that is already in: [{existing_str}]
- Do NOT invent themes not supported by the window.
- Avoid overly broad topics ("general", "random", "chat").
- Avoid overly specific topics tied to a single person, single workshop, single document, or single one-off event.
- Each proposed topic MUST be supported by at least 3 distinct messages/memories in the window.
- Prefer topics that will still be useful 3+ months from now.

PREFERRED GRANULARITY (examples of the right size):
- epoxy_development (build/test/deploy/memory system)
- workshops (planning/running workshop ideas/format)
- student_challenges (coaching cases / recurring pain points)
- coaching_method (methods/models/frameworks)
- governance_and_comms (ethics/docs/guidelines/vibe/public copy)

If a candidate feels like a subtopic of one of the above sizes, propose the broader bucket instead.

Return JSON only.
""".strip()

        try:
            resp = deps.client.chat.completions.create(
                model=deps.openai_model,
                messages=[
                    {"role": "system", "content": prompt[:1900]},
                    {
                        "role": "user",
                        "content": (
                            f"Source: {source_label}\n"
                            f"Channel: {target_channel_name or target_channel_id}\n"
                            f"Window:\n{window_text}"
                        )[:12000],
                    },
                ],
            )
            raw = (resp.choices[0].message.content or "").strip()
        except Exception as e:
            await ctx.send(f"topicsuggest failed (LLM error): {e}")
            return

        items = deps.extract_json_array(raw)

        out = []
        for it in items:
            tid = (it.get("topic_id") or "").strip().lower()
            if not deps.is_valid_topic_id(tid):
                continue
            if tid in existing:
                continue
            conf = float(it.get("confidence", 0.0) or 0.0)
            if conf < 0.55:
                continue
            out.append(
                {
                    "topic_id": tid,
                    "label": (it.get("label") or "").strip()[:60],
                    "why": (it.get("why") or "").strip()[:180],
                    "examples": [str(x).strip()[:80] for x in (it.get("examples") or [])][:3],
                    "confidence": conf,
                }
            )

        seen = set()
        final = []
        for it in out:
            if it["topic_id"] in seen:
                continue
            seen.add(it["topic_id"])
            final.append(it)

        if not final:
            await ctx.send(f"Topic suggestions: none (mode={mode_label} in <#{target_channel_id}>)")
            return

        summary_lines = [f"Topic suggestions (mode={mode_label} in <#{target_channel_id}>):"]
        for it in final[:10]:
            ex = "; ".join(it["examples"][:2])
            summary_lines.append(f"- `{it['topic_id']}` ({it['confidence']:.2f}): {it['why']}  e.g. {ex}")

        json_blob = json.dumps(final[:10], indent=2)
        msg = "\n".join(summary_lines)
        await deps.send_chunked(ctx.channel, msg[:1900])
        await deps.send_chunked(ctx.channel, f"```json\n{json_blob}\n```")
