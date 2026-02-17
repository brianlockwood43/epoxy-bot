from __future__ import annotations

from discord.ext import commands
from misc.commands.command_deps import CommandDeps
from misc.commands.command_deps import CommandGates


def register(
    bot: commands.Bot,
    *,
    deps: CommandDeps,
    gates: CommandGates,
) -> None:
    if deps.music_service is None:
        return

    service = deps.music_service

    async def _ensure_enabled(ctx: commands.Context) -> bool:
        reason = service.disabled_reason()
        if reason:
            await ctx.send(f"Music is disabled: {reason}.")
            return False
        return True

    async def _ensure_music_channel(ctx: commands.Context) -> bool:
        channel_id = int(getattr(ctx.channel, "id", 0) or 0)
        if not service.in_music_text_channel(channel_id):
            await ctx.send(f"Music commands are only available in <#{int(service.text_channel_id)}>.")
            return False
        return True

    async def _ensure_operator(ctx: commands.Context) -> bool:
        if service.is_operator(int(ctx.author.id)):
            return True
        await ctx.send("This music command is operator-only.")
        return False

    async def _ensure_music_access(ctx: commands.Context) -> bool:
        if not await _ensure_enabled(ctx):
            return False
        if not await _ensure_music_channel(ctx):
            return False
        return True

    @bot.command(name="music.start")
    @commands.guild_only()
    async def music_start(ctx: commands.Context):
        if not await _ensure_music_access(ctx):
            return
        if not await _ensure_operator(ctx):
            return
        ok, msg = await service.start(bot=bot, guild=ctx.guild, actor_user_id=int(ctx.author.id))
        await ctx.send(msg if ok else f"Error: {msg}")

    @bot.command(name="music.stop")
    @commands.guild_only()
    async def music_stop(ctx: commands.Context):
        if not await _ensure_music_access(ctx):
            return
        if not await _ensure_operator(ctx):
            return
        ok, msg = await service.stop(actor_user_id=int(ctx.author.id))
        await ctx.send(msg if ok else f"Error: {msg}")

    @bot.command(name="music.skip")
    @commands.guild_only()
    async def music_skip(ctx: commands.Context):
        if not await _ensure_music_access(ctx):
            return
        if not await _ensure_operator(ctx):
            return
        ok, msg = await service.skip(actor_user_id=int(ctx.author.id))
        await ctx.send(msg if ok else f"Error: {msg}")

    @bot.command(name="music.pause")
    @commands.guild_only()
    async def music_pause(ctx: commands.Context):
        if not await _ensure_music_access(ctx):
            return
        if not await _ensure_operator(ctx):
            return
        ok, msg = await service.pause(actor_user_id=int(ctx.author.id))
        await ctx.send(msg if ok else f"Error: {msg}")

    @bot.command(name="music.resume")
    @commands.guild_only()
    async def music_resume(ctx: commands.Context):
        if not await _ensure_music_access(ctx):
            return
        if not await _ensure_operator(ctx):
            return
        ok, msg = await service.resume(actor_user_id=int(ctx.author.id))
        await ctx.send(msg if ok else f"Error: {msg}")

    @bot.command(name="music.clearqueue")
    async def music_clearqueue(ctx: commands.Context):
        if not await _ensure_music_access(ctx):
            return
        if not await _ensure_operator(ctx):
            return
        ok, msg = await service.clear_queue(actor_user_id=int(ctx.author.id))
        await ctx.send(msg if ok else f"Error: {msg}")

    @bot.command(name="music.forcequeue")
    async def music_forcequeue(ctx: commands.Context, *, youtube_url: str = ""):
        if not await _ensure_music_access(ctx):
            return
        if not await _ensure_operator(ctx):
            return
        ok, msg = await service.queue_youtube(
            raw_url=youtube_url,
            submitted_by_user_id=int(ctx.author.id),
            force=True,
        )
        await ctx.send(msg if ok else f"Error: {msg}")

    @bot.command(name="music.queue")
    async def music_queue(ctx: commands.Context, *, youtube_url: str = ""):
        if not await _ensure_music_access(ctx):
            return
        ok, msg = await service.queue_youtube(
            raw_url=youtube_url,
            submitted_by_user_id=int(ctx.author.id),
            force=False,
        )
        await ctx.send(msg if ok else f"Error: {msg}")

    @bot.command(name="music.queue_list")
    async def music_queue_list(ctx: commands.Context, limit: int = 10):
        if not await _ensure_music_access(ctx):
            return
        text = await service.queue_list_text(limit=max(1, min(int(limit or 10), 50)))
        await deps.send_chunked(ctx.channel, f"```\n{text[:7000]}\n```")

    @bot.command(name="music.now")
    async def music_now(ctx: commands.Context):
        if not await _ensure_music_access(ctx):
            return
        text = await service.now_text()
        await deps.send_chunked(ctx.channel, f"```\n{text[:7000]}\n```")

    @bot.command(name="music.status")
    async def music_status(ctx: commands.Context):
        if not await _ensure_enabled(ctx):
            return
        # status is useful even outside the music text channel for operators
        channel_id = int(getattr(ctx.channel, "id", 0) or 0)
        if not service.in_music_text_channel(channel_id) and not gates.user_is_owner(ctx.author):
            await ctx.send(f"Music status is visible in <#{int(service.text_channel_id)}> or for owners.")
            return
        text = await service.status_text()
        await deps.send_chunked(ctx.channel, f"```\n{text[:7000]}\n```")
