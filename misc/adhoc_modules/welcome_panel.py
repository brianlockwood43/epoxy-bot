from __future__ import annotations

import discord


def find_role_by_keyword(guild: discord.Guild, keyword: str) -> discord.Role | None:
    keyword = keyword.lower()
    for role in guild.roles:
        if keyword in role.name.lower():
            return role
    return None


def build_welcome_panel(
    *,
    full_access_url: str,
    access_role_keyword: str,
    driving_role_keyword: str,
) -> discord.ui.View:
    class WelcomePanel(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)
            self.add_item(
                discord.ui.Button(
                    label="Get full access",
                    style=discord.ButtonStyle.link,
                    url=full_access_url,
                )
            )

        @discord.ui.button(
            label="Access the server",
            style=discord.ButtonStyle.secondary,
            custom_id="welcome_access",
        )
        async def access_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            guild = interaction.guild
            if guild is None:
                return

            role = find_role_by_keyword(guild, access_role_keyword)
            if role is None:
                await interaction.response.send_message(
                    "I can't find the access role. Ask Brian to fix my config.",
                    ephemeral=True,
                )
                return

            member = interaction.user
            if not isinstance(member, discord.Member):
                await interaction.response.send_message(
                    "This only works inside the server.",
                    ephemeral=True,
                )
                return

            if role in member.roles:
                await member.remove_roles(role, reason="Welcome panel: remove access")
                await interaction.response.send_message(
                    "Access role removed. Your view will be limited again.",
                    ephemeral=True,
                )
            else:
                await member.add_roles(role, reason="Welcome panel: grant access")
                await interaction.response.send_message(
                    "Access granted.\n\n"
                    "Hi, I'm **Epoxy** - the little brain running in the background of Lumeris.\n"
                    "I'm still under heavy development, but my job is to help you learn faster, "
                    "find good practice, and make this place easier to navigate.\n\n"
                    "For now, your access role is set and more channels should have just unlocked.\n"
                    "Over time, I'll learn to do things like:\n"
                    "- surface useful resources for whatever you're working on\n"
                    "- help schedule and ping practice groups\n"
                    "- give you smart feedback based on your sessions and questions\n\n"
                    "If you get lost or need help, just ask - our community tends to be happy to help.\n"
                    "Soon, you'll be able to ask me questions, too. I just need to get a little smarter first.\n"
                    "Welcome in, and I'm looking forward to working with you soon!",
                    ephemeral=True,
                )

        @discord.ui.button(
            label="Driving Pings",
            style=discord.ButtonStyle.secondary,
            custom_id="welcome_driving",
        )
        async def driving_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            guild = interaction.guild
            if guild is None:
                return

            role = find_role_by_keyword(guild, driving_role_keyword)
            if role is None:
                await interaction.response.send_message(
                    "I can't find the Driving Ping role. Ask Brian to fix my config.",
                    ephemeral=True,
                )
                return

            member = interaction.user
            if not isinstance(member, discord.Member):
                await interaction.response.send_message(
                    "This only works inside the server.",
                    ephemeral=True,
                )
                return

            if role in member.roles:
                await member.remove_roles(role, reason="Welcome panel: disable driving pings")
                await interaction.response.send_message(
                    "Driving Pings disabled. You won't get race notifications.",
                    ephemeral=True,
                )
            else:
                await member.add_roles(role, reason="Welcome panel: enable driving pings")
                await interaction.response.send_message(
                    "Driving Pings enabled.",
                    ephemeral=True,
                )

    return WelcomePanel()
