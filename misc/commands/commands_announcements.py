from __future__ import annotations

import re

import discord
from discord.ext import commands
from misc.commands.command_deps import CommandDeps
from misc.commands.command_deps import CommandGates


def _looks_like_url(token: str) -> bool:
    t = (token or "").strip().lower()
    return t.startswith("https://") or t.startswith("http://")


def _parse_done_args(raw: str) -> tuple[str | None, str | None, str | None]:
    text = (raw or "").strip()
    if not text:
        return (None, None, None)

    if "|" in text:
        left, right = text.split("|", 1)
        left = left.strip()
        right = right.strip()
    else:
        left = text
        right = ""

    mode: str | None = None
    link: str | None = None
    pre_note = ""
    tokens = [tok for tok in re.split(r"\s+", left) if tok]
    if tokens and tokens[0].lower() in {"self", "draft"}:
        mode = tokens.pop(0).lower()
    if tokens and _looks_like_url(tokens[0]):
        link = tokens.pop(0)
    if tokens:
        pre_note = " ".join(tokens).strip()

    note = " ".join([s for s in (pre_note, right) if s]).strip() or None
    return (mode, link, note)


def register(
    bot: commands.Bot,
    *,
    deps: CommandDeps,
    gates: CommandGates,
) -> None:
    def in_allowed_channel_or_thread(ctx: commands.Context) -> bool:
        if gates.in_allowed_channel(ctx):
            return True
        ch = getattr(ctx, "channel", None)
        if isinstance(ch, discord.Thread) and ch.parent and int(ch.parent.id) in gates.allowed_channel_ids:
            return True
        return False

    def require_owner(ctx: commands.Context) -> bool:
        if gates.user_is_owner(ctx.author):
            return True
        return False

    @bot.command(name="announce.status")
    async def announce_status(ctx: commands.Context, date_token: str = ""):
        if not in_allowed_channel_or_thread(ctx):
            return
        target_date = await deps.announcement_service.resolve_target_date(
            date_token=date_token,
            default_mode="today",
            channel_id=int(getattr(ctx.channel, "id", 0) or 0),
        )
        out = await deps.announcement_service.get_status_text(target_date_local=target_date)
        await deps.send_chunked(ctx.channel, f"```\n{out[:7000]}\n```")

    @bot.command(name="announce.answers")
    async def announce_answers(ctx: commands.Context, date_token: str = ""):
        if not in_allowed_channel_or_thread(ctx):
            return
        target_date = await deps.announcement_service.resolve_target_date(
            date_token=date_token,
            default_mode="today",
            channel_id=int(getattr(ctx.channel, "id", 0) or 0),
        )
        out = await deps.announcement_service.get_answers_text(target_date_local=target_date)
        await deps.send_chunked(ctx.channel, f"```\n{out[:7000]}\n```")

    @bot.command(name="announce.answer")
    async def announce_answer(ctx: commands.Context, *, raw: str = ""):
        if not in_allowed_channel_or_thread(ctx):
            return
        if "|" not in raw:
            await ctx.send("Usage: `!announce.answer <question_id> | <answer>`")
            return
        qid, answer = [s.strip() for s in raw.split("|", 1)]
        if not qid or not answer:
            await ctx.send("Usage: `!announce.answer <question_id> | <answer>`")
            return
        target_date = await deps.announcement_service.resolve_target_date(
            date_token=None,
            default_mode="tomorrow",
            channel_id=int(getattr(ctx.channel, "id", 0) or 0),
        )
        ok, msg = await deps.announcement_service.set_answer(
            target_date_local=target_date,
            question_id=qid,
            answer_text=answer,
            actor_user_id=int(ctx.author.id),
            source_message_id=int(ctx.message.id),
        )
        await ctx.send(msg if ok else f"Error: {msg}")

    @bot.command(name="announce.generate")
    async def announce_generate(ctx: commands.Context, date_token: str = ""):
        if not in_allowed_channel_or_thread(ctx):
            return
        target_date = await deps.announcement_service.resolve_target_date(
            date_token=date_token or None,
            default_mode="tomorrow",
            channel_id=int(getattr(ctx.channel, "id", 0) or 0),
        )
        ok, msg, draft = await deps.announcement_service.generate_draft(
            target_date_local=target_date,
            actor_user_id=int(ctx.author.id),
        )
        if not ok:
            await ctx.send(f"Error: {msg}")
            return
        await ctx.send(msg)
        if draft:
            await deps.send_chunked(ctx.channel, f"```{chr(10)}{draft[:7000]}{chr(10)}```")

    @bot.command(name="announce.override")
    async def announce_override(ctx: commands.Context, *, raw: str = ""):
        if not in_allowed_channel_or_thread(ctx):
            return
        text = (raw or "").strip()
        if text.startswith("|"):
            text = text[1:].strip()
        if not text:
            await ctx.send("Usage: `!announce.override | <full_text>`")
            return
        target_date = await deps.announcement_service.resolve_target_date(
            date_token=None,
            default_mode="tomorrow",
            channel_id=int(getattr(ctx.channel, "id", 0) or 0),
        )
        ok, msg = await deps.announcement_service.set_override(
            target_date_local=target_date,
            override_text=text,
            actor_user_id=int(ctx.author.id),
        )
        await ctx.send(msg if ok else f"Error: {msg}")

    @bot.command(name="announce.clear_override")
    async def announce_clear_override(ctx: commands.Context, date_token: str = ""):
        if not in_allowed_channel_or_thread(ctx):
            return
        target_date = await deps.announcement_service.resolve_target_date(
            date_token=date_token or None,
            default_mode="tomorrow",
            channel_id=int(getattr(ctx.channel, "id", 0) or 0),
        )
        ok, msg = await deps.announcement_service.set_override(
            target_date_local=target_date,
            override_text=None,
            actor_user_id=int(ctx.author.id),
        )
        await ctx.send(msg if ok else f"Error: {msg}")

    @bot.command(name="announce.approve")
    async def announce_approve(ctx: commands.Context, date_token: str = ""):
        if not in_allowed_channel_or_thread(ctx):
            return
        if not require_owner(ctx):
            await ctx.send("This command is owner-only.")
            return
        target_date = await deps.announcement_service.resolve_target_date(
            date_token=date_token or None,
            default_mode="tomorrow",
            channel_id=int(getattr(ctx.channel, "id", 0) or 0),
        )
        ok, msg = await deps.announcement_service.approve(target_date_local=target_date, actor_user_id=int(ctx.author.id))
        await ctx.send(msg if ok else f"Error: {msg}")

    @bot.command(name="announce.unapprove")
    async def announce_unapprove(ctx: commands.Context, date_token: str = ""):
        if not in_allowed_channel_or_thread(ctx):
            return
        if not require_owner(ctx):
            await ctx.send("This command is owner-only.")
            return
        target_date = await deps.announcement_service.resolve_target_date(
            date_token=date_token or None,
            default_mode="tomorrow",
            channel_id=int(getattr(ctx.channel, "id", 0) or 0),
        )
        ok, msg = await deps.announcement_service.unapprove(target_date_local=target_date, actor_user_id=int(ctx.author.id))
        await ctx.send(msg if ok else f"Error: {msg}")

    @bot.command(name="announce.done")
    async def announce_done(ctx: commands.Context, *, raw: str = ""):
        if not in_allowed_channel_or_thread(ctx):
            return
        if not require_owner(ctx):
            await ctx.send("This command is owner-only.")
            return
        mode, link, note = _parse_done_args(raw)
        target_date = await deps.announcement_service.resolve_target_date(
            date_token=None,
            default_mode="today",
            channel_id=int(getattr(ctx.channel, "id", 0) or 0),
        )
        ok, msg = await deps.announcement_service.mark_done(
            target_date_local=target_date,
            mode=mode,
            actor_user_id=int(ctx.author.id),
            link=link,
            note=note,
        )
        await ctx.send(msg if ok else f"Error: {msg}")

    @bot.command(name="announce.undo_done")
    async def announce_undo_done(ctx: commands.Context, date_token: str = ""):
        if not in_allowed_channel_or_thread(ctx):
            return
        if not require_owner(ctx):
            await ctx.send("This command is owner-only.")
            return
        target_date = await deps.announcement_service.resolve_target_date(
            date_token=date_token or None,
            default_mode="today",
            channel_id=int(getattr(ctx.channel, "id", 0) or 0),
        )
        ok, msg = await deps.announcement_service.undo_done(target_date_local=target_date, actor_user_id=int(ctx.author.id))
        await ctx.send(msg if ok else f"Error: {msg}")

    @bot.command(name="announce.post_now")
    async def announce_post_now(ctx: commands.Context, date_token: str = ""):
        if not in_allowed_channel_or_thread(ctx):
            return
        if not require_owner(ctx):
            await ctx.send("This command is owner-only.")
            return
        target_date = await deps.announcement_service.resolve_target_date(
            date_token=date_token or None,
            default_mode="today",
            channel_id=int(getattr(ctx.channel, "id", 0) or 0),
        )
        ok, msg = await deps.announcement_service.post_now(
            bot=bot,
            target_date_local=target_date,
            actor_user_id=int(ctx.author.id),
        )
        await ctx.send(msg if ok else f"Error: {msg}")

    @bot.command(name="announce.prep_tomorrow_now")
    async def announce_prep_tomorrow_now(ctx: commands.Context):
        if not in_allowed_channel_or_thread(ctx):
            return
        if not require_owner(ctx):
            await ctx.send("This command is owner-only.")
            return
        target_date = await deps.announcement_service.resolve_target_date(
            date_token=None,
            default_mode="tomorrow",
            channel_id=int(getattr(ctx.channel, "id", 0) or 0),
        )
        ok, msg = await deps.announcement_service.prep_now(
            bot=bot,
            target_date_local=target_date,
            actor_user_id=int(ctx.author.id),
        )
        await ctx.send(msg if ok else f"Error: {msg}")
