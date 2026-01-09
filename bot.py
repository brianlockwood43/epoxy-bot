import os
import discord
from discord.ext import commands
from openai import OpenAI

# ENV
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not DISCORD_TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN env var")
if not OPENAI_API_KEY:
    raise RuntimeError("Missing OPENAI_API_KEY env var")

client = OpenAI(api_key=OPENAI_API_KEY)

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

SYSTEM_PROMPT = "You are Epoxy, the Lumeris staff assistant. Be helpful, playful, and precise."

@bot.event
async def on_ready():
    print(f"Epoxy is online as {bot.user}")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # Only respond if mentioned
    if bot.user and bot.user in message.mentions:
        prompt = message.content.replace(f"<@{bot.user.id}>", "").strip()

        # Avoid replying to empty mentions like "@Epoxy"
        if not prompt:
            await message.channel.send("Yep? 🧴")
            await bot.process_commands(message)
            return

        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            reply = resp.choices[0].message.content or "(no output)"
            await message.channel.send(reply)

        except Exception as e:
            # Keep it simple: log + small user-facing note
            print(f"OpenAI error: {e}")
            await message.channel.send("Epoxy hiccuped. Check logs 🧴⚙️")

    await bot.process_commands(message)

bot.run(DISCORD_TOKEN)

