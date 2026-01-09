import os
import discord
from discord.ext import commands
import openai

# ENV
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

openai.api_key = OPENAI_API_KEY

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Epoxy is online as {bot.user}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Only respond if mentioned
    if bot.user in message.mentions:
        prompt = message.content.replace(f"<@{bot.user.id}>", "").strip()

        response = openai.ChatCompletion.create(
            model="gpt-5.1-chat-latest", 
            messages=[
                {"role": "system", "content": "You are Epoxy, the Lumeris staff assistant. Be helpful, playful, and precise."},
                {"role": "user", "content": prompt}
            ]
        )

        reply = response.choices[0].message.content
        await message.channel.send(reply)

    await bot.process_commands(message)

bot.run(DISCORD_TOKEN)
