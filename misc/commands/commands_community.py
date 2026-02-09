from __future__ import annotations

import discord
from discord.ext import commands
from misc.commands.command_deps import CommandDeps
from misc.commands.command_deps import CommandGates


def register(
    bot: commands.Bot,
    *,
    deps: CommandDeps,
    gates: CommandGates,
) -> None:
    @bot.command(name="setup_welcome_panel")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def setup_welcome_panel(ctx: commands.Context):
        if ctx.channel.id != deps.welcome_channel_id:
            await ctx.reply(
                "Run this in the designated welcome channel.",
                mention_author=False,
            )
            return

        embed = discord.Embed(
            title="Welcome to Lumeris",
            description=(
                "- **Access the server**\n"
                "Unlock the main community channels once you're ready to look around.\n\n"
                "- **Get full access**\n"
                "Opens our external page where you can become a full Lumeris member.\n\n"
                "- **Driving pings**\n"
                "Opt in to casual race notifications when members are looking for a group."
            ),
            colour=discord.Colour.orange(),
        )

        view = deps.welcome_panel_factory()
        await ctx.send(embed=embed, view=view)
        await ctx.reply("Welcome panel posted.", mention_author=False)

    @bot.command(name="lfg")
    @commands.guild_only()
    async def lfg_command(ctx: commands.Context, target: str, *, message: str | None = None):
        if ctx.channel.id != deps.lfg_source_channel_id:
            await ctx.reply(
                "Use this command in the #looking-for-group-pings channel.",
                mention_author=False,
            )
            return

        if not isinstance(ctx.author, discord.Member) or not gates.user_is_member(ctx.author):
            await ctx.reply(
                "Only Lumeris members can start LFG pings.",
                mention_author=False,
            )
            return

        target = target.lower()
        if target not in ("public", "members"):
            await ctx.reply(
                "Usage: `!lfg public <message>` or `!lfg members <message>`",
                mention_author=False,
            )
            return

        dest_channel_id = deps.lfg_public_channel_id if target == "public" else deps.paddock_lounge_channel_id
        dest_channel = ctx.guild.get_channel(dest_channel_id)
        if dest_channel is None:
            await ctx.reply(
                "I couldn't find the destination channel. Check my channel IDs in the config.",
                mention_author=False,
            )
            return

        ping_role = discord.utils.get(ctx.guild.roles, name=deps.lfg_role_name)
        if ping_role is None:
            await ctx.reply(
                f"I couldn't find a role named `{deps.lfg_role_name}`. "
                "Create it or update my config.",
                mention_author=False,
            )
            return

        base = f"{ping_role.mention} - {ctx.author.mention} is looking for a group."
        if message:
            base += f" {message}"

        await dest_channel.send(base)
        await ctx.reply(
            f"LFG ping sent to {dest_channel.mention}.",
            mention_author=False,
        )
