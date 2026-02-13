from __future__ import annotations

import discord


def message_in_allowed_channels(message: discord.Message, allowed_channel_ids: set[int]) -> bool:
    # DMs are intentionally allowed for mention-driven copilot behavior.
    if getattr(message, "guild", None) is None:
        return True

    channel_id = int(getattr(message.channel, "id", 0) or 0)
    if channel_id in allowed_channel_ids:
        return True
    # thread: allow if parent is allowed
    if isinstance(message.channel, discord.Thread) and message.channel.parent:
        return int(message.channel.parent.id) in allowed_channel_ids
    return False
