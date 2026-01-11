import os
import sqlite3
import asyncio
import discord
from discord.ext import commands
from openai import OpenAI

# =========================
# ENV
# =========================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not DISCORD_TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN env var")
if not OPENAI_API_KEY:
    raise RuntimeError("Missing OPENAI_API_KEY env var")

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Railway persistent path (set this to your mounted volume path)
DB_PATH = os.getenv("EPOXY_DB_PATH", "epoxy_memory.db")

client = OpenAI(api_key=OPENAI_API_KEY)

# =========================
# ALLOWED CHANNELS
# =========================
ALLOWED_CHANNEL_IDS = {
    1458572717585600524,
    1408194344351039580,
    1458572555823616173,
    1458572511204610048,
    1458572485095325747,
    1458572462760394824,
    1458572425754316811,
    1458572343264936145,
    1458716574260133948,
    1407828560177004566,
}

# =========================
# "Seed memories" (Epoxy context pack)
# Edit these freely.
# =========================
SEED_MEMORIES = [
    "Lumeris is a high-trust sim racing and human-development community that values care, precision, and clear models rather than vague vibes.",
    "Brian leads Lumeris. He has final say on direction and uses systems thinking heavily; clarity beats cleverness.",
    "Inside jokes/language: 'glue eater', 'brain glue', 'epoxy'. Glue = deep nerding on models AND playfully acting dumb; epoxy = high quality glue = the connective tissue that keeps systems coherent. Jokes are welcome as long as responses stay precise and helpful.",
    "Epoxy should default to: helpful, playful, grounded, and explicitly ask clarifying questions when a request is underspecified.",
    "Epoxy only speaks when mentioned, but she can 'listen' (log and learn patterns) in whitelisted staff channels.",
    "When giving advice, prefer: principle-level framing → 2–3 concrete next actions → optional deeper dive on request.",
    "Epoxy should pay attention to patterns across channels (recurring questions, themes, pain points) and can surface them gently to staff: 'I've seen a few people ask about X this week...'",
    "Lumeris teaches from an 'Awareness Model': a system for how drivers and humans develop over layers (L1–L5), generativity, and regulation.",
    "Epoxy should NOT try to invent new theory about the Awareness Model; stay consistent with the official docs and Brian/coach explanations.",
    "Default public-friendly explanation: 'The Awareness Model is Lumeris' map of how drivers grow from early awareness to deep, automatic understanding, across layers like L1–L5.'",
    'If someone asks for deep Awareness Model details, Epoxy should either (1) give a short summary and point to the official doc/workshop, or (2) retrieve from the vector DB and summarize, if available.',
    "Brian is a high-context founder with limited bandwidth. When he asks for help, Epoxy should keep answers concise, highlight tradeoffs, and, when useful, offer 2–3 clear options plus a default recommendation.",
    "When Brian (or staff) show 'glue mode'—lots of ideas and excitement—Epoxy should help by capturing the ideas, then nudging toward one small, realistic next step instead of expanding scope.",
    "Epoxy is not a therapist. If conversations drift into deep emotional processing or personal crisis, she should respond with care but gently encourage 1:1 coaching, personal support, or other appropriate spaces rather than trying to do emotional work herself.",
    "Epoxy is allowed to name overload gently (e.g., 'this sounds like a lot at once; want to pick one move for this week?') and can occasionally suggest rest or timeboxing when Brian/staff are clearly overextended.",
    "Playfulness style: light, warm teasing and self-aware jokes (especially about glue/brainrot), never mocking someone's skill, struggles, or vulnerabilities. Avoid sarcasm that could be read as contempt.",
    "Epoxy should 'punch up, not down': it's okay to gently tease Brian/coaches as lovable glue-eaters or over-thinkers, but never shame or dogpile members, especially newer or struggling drivers.",
    "No intimacy-coded or flirty playfulness in public/server contexts. Epoxy's default is friendly staff energy: collegial, safe, and slightly goofy, not personal or overly intimate.",
]


SYSTEM_PROMPT_BASE = """
You are Epoxy, the Lumeris staff assistant. You primarily live in the Lumeris Discord server.

Core identity:
- Helpful, playful, and precise.
- Support staff, not the star of the show.
- Organizational "glue": you help hold information, processes, and people together.

Core behavior:
- Prefer clarity over performative cleverness.
- Be calm under stress and keep your tone warm, casual, and clear.
- Default to concise answers: short answer first, then deeper detail if asked.
- Ask simple, explicit clarifying questions when a request is underspecified.

Channel & relationship rules:
- Respect channel context: staff channels can handle more internal language; public/member channels should stay accessible and avoid leaking private info.
- Brian and other coaches have final say. You support their decisions and never speak over or "overrule" them.
- If a member disagrees with a coach, you can reframe, clarify, or suggest questions they can bring back to the coach, but you do not take sides.

Actions & honesty:
- Do NOT pretend to take real-world actions. You can draft messages, announcements, or plans, but you cannot actually send emails/DMs, change settings, or modify systems.
- Be honest about your limits and uncertainty. If you are not sure about a policy, timeline, or fact, say so and suggest checking announcements, docs, or asking staff.

Safety:
- Follow general safety rules: no self-harm encouragement, no instructions for serious harm or illegal activity.
- For medical, legal, or financial topics, you may give general information but always remind users to consult qualified professionals.

Knowledge & context:
- You only know what is in the current conversation plus any explicit "seed memories" or logs you are given.
- You do not have magical live access to all Lumeris data; your model of Lumeris is based on past conversations, shared docs, and observed patterns.
- Phrase pattern observations humbly: "From what I've seen recently..." and invite correction.

Your job is to keep Lumeris conversations and operations coherent, kind, and effective, one small helpful response at a time.
""".strip()

def build_context_pack() -> str:
    # Keep it compact; this is the always-on primer.
    lines = "\n".join(f"- {m}" for m in SEED_MEMORIES)
    return f"Context pack (seed memories):\n{lines}"

# =========================
# SQLITE
# =========================
def init_db(db_path: str) -> sqlite3.Connection:
    # check_same_thread=False because discord.py event loop + to_thread usage
    conn = sqlite3.connect(db_path, check_same_thread=False)
    cur = conn.cursor()

    # Performance + safety defaults
    cur.execute("PRAGMA journal_mode=WAL;")
    cur.execute("PRAGMA synchronous=NORMAL;")

    # Message log (deduped by message_id)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        message_id      INTEGER PRIMARY KEY,
        guild_id        INTEGER,
        guild_name      TEXT,
        channel_id      INTEGER,
        channel_name    TEXT,
        author_id       INTEGER,
        author_name     TEXT,
        created_at_utc  TEXT,
        content         TEXT,
        attachments     TEXT
    )
    """)

    # Channel backfill state
    cur.execute("""
    CREATE TABLE IF NOT EXISTS channel_state (
        channel_id INTEGER PRIMARY KEY,
        backfill_done INTEGER DEFAULT 0,
        last_backfill_at_utc TEXT
    )
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_channel_id ON messages(channel_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_author_id ON messages(author_id)")

    conn.commit()
    return conn

db_conn = init_db(DB_PATH)
print(f"[DB] Using DB_PATH={DB_PATH}")
print(f"[DB] DB file exists? {os.path.exists(DB_PATH)}")
db_lock = asyncio.Lock()

def _insert_message_sync(conn: sqlite3.Connection, payload: dict) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR IGNORE INTO messages (
            message_id, guild_id, guild_name,
            channel_id, channel_name,
            author_id, author_name,
            created_at_utc, content, attachments
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload["message_id"],
            payload["guild_id"], payload["guild_name"],
            payload["channel_id"], payload["channel_name"],
            payload["author_id"], payload["author_name"],
            payload["created_at_utc"],
            payload["content"],
            payload["attachments"],
        )
    )
    conn.commit()

def _get_backfill_done_sync(conn: sqlite3.Connection, channel_id: int) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT backfill_done FROM channel_state WHERE channel_id = ?", (channel_id,))
    row = cur.fetchone()
    return bool(row and row[0] == 1)

def _set_backfill_done_sync(conn: sqlite3.Connection, channel_id: int, iso_utc: str) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO channel_state (channel_id, backfill_done, last_backfill_at_utc)
        VALUES (?, 1, ?)
        ON CONFLICT(channel_id) DO UPDATE SET
            backfill_done=1,
            last_backfill_at_utc=excluded.last_backfill_at_utc
        """,
        (channel_id, iso_utc)
    )
    conn.commit()

async def log_message(message: discord.Message) -> None:
    attachments = ""
    if message.attachments:
        attachments = " | ".join(a.url for a in message.attachments if a.url)

    guild = message.guild
    payload = {
        "message_id": message.id,
        "guild_id": guild.id if guild else None,
        "guild_name": guild.name if guild else None,
        "channel_id": message.channel.id,
        "channel_name": getattr(message.channel, "name", str(message.channel)),
        "author_id": message.author.id,
        "author_name": str(message.author),
        "created_at_utc": message.created_at.isoformat() if message.created_at else "",
        "content": message.content or "",
        "attachments": attachments,
    }

    async with db_lock:
        # run sync sqlite write off the event loop
        await asyncio.to_thread(_insert_message_sync, db_conn, payload)

async def is_backfill_done(channel_id: int) -> bool:
    async with db_lock:
        return await asyncio.to_thread(_get_backfill_done_sync, db_conn, channel_id)

async def mark_backfill_done(channel_id: int) -> None:
    iso_utc = discord.utils.utcnow().isoformat()
    async with db_lock:
        await asyncio.to_thread(_set_backfill_done_sync, db_conn, channel_id, iso_utc)

# =========================
# DISCORD BOT
# =========================
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Backfill config
BACKFILL_LIMIT = int(os.getenv("EPOXY_BACKFILL_LIMIT", "2000"))  # per channel, first boot
BACKFILL_PAUSE_EVERY = 200
BACKFILL_PAUSE_SECONDS = 0.25

async def backfill_channel(channel: discord.abc.Messageable) -> None:
    if not hasattr(channel, "id"):
        return

    channel_id = channel.id
    if channel_id not in ALLOWED_CHANNEL_IDS:
        return

    if await is_backfill_done(channel_id):
        return

    print(f"[Backfill] Starting channel {channel_id} ({getattr(channel, 'name', 'unknown')}) limit={BACKFILL_LIMIT}")

    count = 0
    try:
        # oldest_first=True so inserts happen chronologically
        async for msg in channel.history(limit=BACKFILL_LIMIT, oldest_first=True):
            if msg.author.bot:
                continue
            await log_message(msg)
            count += 1
            if count % BACKFILL_PAUSE_EVERY == 0:
                await asyncio.sleep(BACKFILL_PAUSE_SECONDS)
    except Exception as e:
        print(f"[Backfill] Error in channel {channel_id}: {e}")
        return

    await mark_backfill_done(channel_id)
    print(f"[Backfill] Done channel {channel_id}. Logged {count} messages.")

@bot.event
async def on_ready():
    print(f"Epoxy is online as {bot.user}")
    # One-time backfill for each allowed channel (only if not already done in DB)
    for channel_id in ALLOWED_CHANNEL_IDS:
        ch = bot.get_channel(channel_id)
        if ch is None:
            # Not cached yet; try fetching
            try:
                ch = await bot.fetch_channel(channel_id)
            except Exception as e:
                print(f"[Backfill] Could not fetch channel {channel_id}: {e}")
                continue
        await backfill_channel(ch)

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if message.channel.id not in ALLOWED_CHANNEL_IDS:
        return

    # Always log in allowed channels
    await log_message(message)

    # Only respond if mentioned
    if bot.user and bot.user in message.mentions:
        prompt = message.content.replace(f"<@{bot.user.id}>", "").strip()

        if not prompt:
            await message.channel.send("Yep? 🧴")
            await bot.process_commands(message)
            return

        try:
            resp = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT_BASE},
                    {"role": "system", "content": build_context_pack()},
                    {"role": "user", "content": prompt},
                ],
            )
            reply = resp.choices[0].message.content or "(no output)"
            await message.channel.send(reply)
        except Exception as e:
            print(f"[OpenAI] Error: {e}")
            await message.channel.send("Epoxy hiccuped. Check logs 🧴⚙️")

    await bot.process_commands(message)

bot.run(DISCORD_TOKEN)
