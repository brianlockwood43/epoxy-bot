from __future__ import annotations

import asyncio
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
    rubric_keys = (
        "tone_fit",
        "de_escalation",
        "agency_respect",
        "boundary_clarity",
        "actionability",
        "context_honesty",
    )
    failure_tag_allow = {
        "too_long",
        "too_vague",
        "too_harsh",
        "too_soft",
        "too_therapyspeak",
        "misses_ask",
        "invents_facts",
    }

    @bot.command(name="episodelogs")
    async def cmd_episodelogs(ctx: commands.Context, limit: int = 20):
        if not gates.in_allowed_channel(ctx):
            return
        if not gates.user_is_owner(ctx.author):
            await ctx.send("This command is owner-only.")
            return

        lim = max(1, min(int(limit or 20), 100))
        async with deps.db_lock:
            rows = await asyncio.to_thread(deps.fetch_episode_logs_sync, deps.db_conn, lim)

        if not rows:
            await ctx.send("No episode logs yet.")
            return

        lines = [f"Episode logs (latest {len(rows)}):"]
        for row in rows:
            ts = row.get("timestamp_utc", "unknown-ts")
            cid = row.get("channel_id")
            uid = row.get("user_id")
            caller = row.get("caller_type", "unknown")
            surface = row.get("surface", "unknown")
            persona = row.get("controller_persona", "guide")
            scope = row.get("controller_scope", "global")
            mem_n = len(row.get("retrieved_memory_ids", []) or [])
            rating = row.get("explicit_rating")
            rating_txt = f" rating={rating}" if rating is not None else ""
            excerpt = " ".join((row.get("input_excerpt") or "").split())
            if len(excerpt) > 90:
                excerpt = excerpt[:89] + "..."
            lines.append(
                f"- #{row.get('id')} {ts} ch={cid} user={uid} {caller}/{surface} "
                f"cfg={persona}@{scope} mem={mem_n}{rating_txt} :: {excerpt}"
            )

        await deps.send_chunked(ctx.channel, "```\n" + "\n".join(lines)[:7000] + "\n```")

    @bot.command(name="dbmigrations")
    async def cmd_dbmigrations(ctx: commands.Context, limit: int = 30):
        if not gates.in_allowed_channel(ctx):
            return
        if not gates.user_is_owner(ctx.author):
            await ctx.send("This command is owner-only.")
            return

        lim = max(1, min(int(limit or 30), 200))
        async with deps.db_lock:
            rows = await asyncio.to_thread(deps.list_schema_migrations_sync, deps.db_conn, lim)

        if not rows:
            await ctx.send("No schema migrations found.")
            return

        lines = [f"Applied schema migrations (latest {len(rows)}):"]
        for version, name, applied_at in rows:
            lines.append(f"- {version}_{name} @ {applied_at}")

        await deps.send_chunked(ctx.channel, "```\n" + "\n".join(lines)[:7000] + "\n```")

    @bot.command(name="dmfeedback")
    async def cmd_dmfeedback(ctx: commands.Context, outcome: str = "", *, note: str = ""):
        if not gates.in_allowed_channel(ctx):
            return
        if not gates.user_is_owner(ctx.author):
            await ctx.send("This command is owner-only.")
            return

        outcome_key = (outcome or "").strip().lower()
        if outcome_key not in {"keep", "edit", "sent", "discard"}:
            await ctx.send("Usage: `!dmfeedback <keep|edit|sent|discard> [note]`")
            return
        if deps.update_latest_dm_draft_feedback_sync is None:
            await ctx.send("DM feedback store function is not configured.")
            return

        async with deps.db_lock:
            row = await asyncio.to_thread(
                deps.update_latest_dm_draft_feedback_sync,
                deps.db_conn,
                user_id=int(ctx.author.id),
                outcome=outcome_key,
                note=(note or "").strip() or None,
            )

        if not row:
            await ctx.send("No recent DM draft episode found for feedback.")
            return

        await ctx.send(
            f"Recorded feedback on episode #{row['episode_id']}: outcome={row['outcome']} rating={row['explicit_rating']}."
        )

    @bot.command(name="dmeval")
    async def cmd_dmeval(ctx: commands.Context, *, raw: str = ""):
        if not gates.in_allowed_channel(ctx):
            return
        if not gates.user_is_owner(ctx.author):
            await ctx.send("This command is owner-only.")
            return
        if deps.update_latest_dm_draft_evaluation_sync is None:
            await ctx.send("DM evaluation store function is not configured.")
            return

        text = (raw or "").strip()
        if not text:
            await ctx.send(
                "Usage: `!dmeval tone_fit=0..2 de_escalation=0..2 agency_respect=0..2 "
                "boundary_clarity=0..2 actionability=0..2 context_honesty=0..2 "
                "[tags=tag1,tag2] [| optional note]`"
            )
            return

        parts = text.split("|", 1)
        score_part = parts[0].strip()
        note = parts[1].strip() if len(parts) > 1 else ""

        token_pattern = re.compile(r"([a-z_]+)\s*=\s*([^\s]+)")
        tokens = {m.group(1).strip().lower(): m.group(2).strip() for m in token_pattern.finditer(score_part)}

        missing = [k for k in rubric_keys if k not in tokens]
        if missing:
            await ctx.send(f"Missing rubric fields: {', '.join(missing)}")
            return

        rubric_scores: dict[str, int] = {}
        for key in rubric_keys:
            try:
                value = int(tokens[key])
            except Exception:
                await ctx.send(f"Invalid score for `{key}`; expected 0, 1, or 2.")
                return
            if value not in {0, 1, 2}:
                await ctx.send(f"Invalid score for `{key}`; expected 0, 1, or 2.")
                return
            rubric_scores[key] = value

        tags_raw = tokens.get("tags") or tokens.get("failure_tags") or ""
        failure_tags: list[str] = []
        if tags_raw:
            for tag in re.split(r"[,;]", tags_raw):
                clean = tag.strip().lower()
                if not clean:
                    continue
                if clean not in failure_tag_allow:
                    await ctx.send(f"Invalid failure tag `{clean}`.")
                    return
                failure_tags.append(clean)

        async with deps.db_lock:
            row = await asyncio.to_thread(
                deps.update_latest_dm_draft_evaluation_sync,
                deps.db_conn,
                user_id=int(ctx.author.id),
                rubric_scores=rubric_scores,
                failure_tags=failure_tags,
                note=note or None,
            )

        if not row:
            await ctx.send("No recent DM draft episode found for evaluation.")
            return

        score_sum = sum(int(v) for v in rubric_scores.values())
        await ctx.send(
            f"Recorded DM eval on episode #{row['episode_id']} (total={score_sum}/12). "
            f"tags={','.join(failure_tags) if failure_tags else '(none)'}"
        )
