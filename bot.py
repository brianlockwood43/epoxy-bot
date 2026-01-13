import os
import sqlite3
import asyncio
import json
import re
import time
from datetime import datetime, timezone
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

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.1")

# =========================
# MEMORY STAGING
# =========================
# Stages:
#   M0: baseline (recent channel context only)
#   M1: persistent event memory + recall
#   M2: temporal tiers (hot/warm/cold) + tier-aware recall/cleanup
#   M3: summaries (topic gists) + optional consolidation jobs
#
# Control via env:
#   EPOXY_MEMORY_STAGE = M0 | M1 | M2 | M3   (default: M0)
#   EPOXY_MEMORY_ENABLE_AUTO_CAPTURE = 0/1   (default: 0)
#   EPOXY_MEMORY_ENABLE_AUTO_SUMMARY = 0/1   (default: 0)
#
# Notes:
# - “Wire to M3” means: the DB schema + codepaths exist up through M3,
#   but you can keep runtime behavior at M0/M1/M2 with the stage flags.
#
MEMORY_STAGE = os.getenv("EPOXY_MEMORY_STAGE", "M1").strip().upper()
STAGE_RANK = {"M0": 0, "M1": 1, "M2": 2, "M3": 3}
MEMORY_STAGE_RANK = STAGE_RANK.get(MEMORY_STAGE, 0)

AUTO_CAPTURE = os.getenv("EPOXY_MEMORY_ENABLE_AUTO_CAPTURE", "0").strip() == "1"
AUTO_SUMMARY = os.getenv("EPOXY_MEMORY_ENABLE_AUTO_SUMMARY", "0").strip() == "1"

# Topic suggestion (late-M3 ergonomics)
# If enabled, Epoxy can suggest a topic_id for memories that lack an explicit topic.
# This is intentionally conservative: it only suggests from an allowlist (or known topics if no allowlist).
TOPIC_SUGGEST = os.getenv("EPOXY_TOPIC_SUGGEST", "0").strip() == "1"
TOPIC_MIN_CONF = float(os.getenv("EPOXY_TOPIC_MIN_CONF", "0.85"))
_TOPIC_ALLOWLIST_RAW = os.getenv("EPOXY_TOPIC_ALLOWLIST", "ops,announcements,community,coaches,workshops,one_on_one,member_support,conflict_resolution,marketing,content,website,pricing,billing,roadmap,infra,bugs,deployments,epoxy_bot,experiments,baby_brain,console_bay,coaching_method,layer_model,telemetry,track_guides").strip()
TOPIC_ALLOWLIST = [t.strip().lower() for t in re.split(r"[;,]+", _TOPIC_ALLOWLIST_RAW) if t.strip()] if _TOPIC_ALLOWLIST_RAW else []
RESERVED_KIND_TAGS = {"decision", "policy", "canon"}

def stage_at_least(stage: str) -> bool:
    return MEMORY_STAGE_RANK >= STAGE_RANK.get(stage.upper(), 0)


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
    1410479714182631474,
    1410479845447565332,
    1408225092189556746,
    1412264637621207071,
    1408224293120380980,
    1412303004224327803,
    1410966350196768809,
    1412327305723777044,
    1412328113152720897,
    1419853202085384323,
    1460014678947135652,
    1450640792346431498,
    1413721242376339527,
    1413721196851237026,
    1419737142803824730,
    1412358211461316698,
}

# =========================
# "Seed memories" (Epoxy context pack)
# Edit these freely.
# =========================
SEED_MEMORIES = [
    "Lumeris is a high-trust sim racing and human-development community that values care, precision, and clear models rather than vague vibes.",
    "Brian Lockwood (@blockwood43) leads Lumeris. He has final say on direction and uses systems thinking heavily; clarity beats cleverness.",
    "Lumeris emerging coaches include Sammy Hendrix (@sammyhendrix), Declan Marsden (@decfactoryracing), Abdulrahman Mahmoud (@oddmanout), and Julian Swanson (@js51). Tom (@tommerrall949) [intentionally keeping last name anonymous] and James (@quantumprism) are not official Lumeris staff, but do have access to some Lumeris Admin channels to help out."
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

DISCORD_MAX_MESSAGE_LEN = 1900  # keep under 2000 hard limit

def chunk_text(text: str, limit: int = DISCORD_MAX_MESSAGE_LEN) -> list[str]:
    text = text or ""
    if len(text) <= limit:
        return [text]

    chunks = []
    remaining = text

    while len(remaining) > limit:
        # Prefer splitting on paragraph, then newline, then space
        split_at = remaining.rfind("\n\n", 0, limit)
        if split_at == -1:
            split_at = remaining.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = remaining.rfind(" ", 0, limit)
        if split_at == -1:
            split_at = limit

        chunk = remaining[:split_at].strip()
        if chunk:
            chunks.append(chunk)

        remaining = remaining[split_at:].strip()

    if remaining:
        chunks.append(remaining)

    return chunks


async def send_chunked(channel: discord.abc.Messageable, text: str) -> None:
    for part in chunk_text(text, DISCORD_MAX_MESSAGE_LEN):
        await channel.send(part)

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


    # Persistent memory events (M1+)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS memory_events (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at_utc     TEXT,
        created_ts         INTEGER,
        guild_id           INTEGER,
        channel_id         INTEGER,
        channel_name       TEXT,
        author_id          INTEGER,
        author_name        TEXT,
        source_message_id  INTEGER,
        text               TEXT NOT NULL,
        tags_json          TEXT,
        importance         INTEGER DEFAULT 0,
        tier               INTEGER DEFAULT 1,
        summarized         INTEGER DEFAULT 0
    )
    """)

    # M3.5 topic suggestion columns (safe migrations for existing DBs)
    for stmt in [
        "ALTER TABLE memory_events ADD COLUMN topic_id TEXT",
        "ALTER TABLE memory_events ADD COLUMN topic_source TEXT DEFAULT 'manual'",
        "ALTER TABLE memory_events ADD COLUMN topic_confidence REAL",
    ]:
        try:
            cur.execute(stmt)
        except Exception:
            pass

    # Best-effort backfill: set topic_id from first tag when possible.
    try:
        cur.execute("UPDATE memory_events SET topic_id = json_extract(tags_json, '$[0]') WHERE (topic_id IS NULL OR topic_id='') AND tags_json IS NOT NULL AND tags_json != '[]'")
    except Exception:
        pass


    # Topic summaries (M3)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS memory_summaries (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        topic_id         TEXT NOT NULL,
        created_at_utc   TEXT,
        updated_at_utc   TEXT,
        start_ts         INTEGER,
        end_ts           INTEGER,
        tags_json        TEXT,
        importance       INTEGER DEFAULT 1,
        summary_text     TEXT NOT NULL
    )
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_mem_events_created_ts ON memory_events(created_ts)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mem_events_tier ON memory_events(tier)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mem_events_importance ON memory_events(importance)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mem_summaries_topic_id ON memory_summaries(topic_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mem_summaries_end_ts ON memory_summaries(end_ts)")

    # FTS indexes (contentless) for fast recall
    # NOTE: we keep rowid aligned with the primary table's id for easy joins.
    cur.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS memory_events_fts
    USING fts5(text, tags, tokenize='unicode61')
    """)
    cur.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS memory_summaries_fts
    USING fts5(topic_id, summary_text, tags, tokenize='unicode61')
    """)

    conn.commit()
    return conn

db_conn = init_db(DB_PATH)
print(f"[DB] Using DB_PATH={DB_PATH}")
print(f"[DB] DB file exists? {os.path.exists(DB_PATH)}")
db_lock = asyncio.Lock()
# =========================
# MEMORY HELPERS
# =========================
def utc_iso(dt: datetime | None = None) -> str:
    dt = dt or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()

def utc_ts(dt: datetime | None = None) -> int:
    dt = dt or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())

def safe_json_dumps(obj) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return "[]"

def safe_json_loads(s: str):
    try:
        return json.loads(s) if s else []
    except Exception:
        return []

def normalize_tags(tags: list[str]) -> list[str]:
    out = []
    for t in (tags or []):
        t = (t or "").strip()
        if not t:
            continue
        # tags are short, slug-ish strings
        t = re.sub(r"[^a-zA-Z0-9_\\-]", "", t)
        if t:
            out.append(t.lower())
    # stable + dedup
    return sorted(set(out))

def infer_tier(created_ts: int) -> int:
    """0=hot (0-24h), 1=warm (1-14d), 2=cold (14-90d), 3=archive (>90d)"""
    age = max(0, int(time.time()) - int(created_ts or 0))
    if age < 86400:
        return 0
    if age < 14 * 86400:
        return 1
    if age < 90 * 86400:
        return 2
    return 3

def build_fts_query(q: str) -> str:
    """Very small, safe-ish FTS5 query builder."""
    q = (q or "").strip()
    if not q:
        return ""
    # Take words; avoid FTS syntax injection
    words = re.findall(r"[A-Za-z0-9_\\-]{3,}", q.lower())
    words = words[:10]
    if not words:
        return ""
    # OR makes recall more forgiving
    return " OR ".join(words)

def infer_scope(prompt: str) -> str:
    p = (prompt or "").lower()
    if any(k in p for k in ["today", "right now", "just now", "in the last hour", "this morning", "tonight"]):
        return "hot"
    if any(k in p for k in ["yesterday", "this week", "recently", "past few days", "last few days", "lately"]):
        return "warm"
    if any(k in p for k in ["months ago", "back when", "back then", "last year", "long ago", "a while ago"]):
        return "cold"
    return "auto"


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

def _insert_memory_event_sync(conn: sqlite3.Connection, payload: dict) -> int:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO memory_events (
            created_at_utc, created_ts,
            guild_id, channel_id, channel_name,
            author_id, author_name,
            source_message_id,
            text, tags_json, importance, tier,
            topic_id, topic_source, topic_confidence,
            summarized
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload["created_at_utc"], payload["created_ts"],
            payload.get("guild_id"), payload.get("channel_id"), payload.get("channel_name"),
            payload.get("author_id"), payload.get("author_name"),
            payload.get("source_message_id"),
            payload["text"],
            payload.get("tags_json", "[]"),
            int(payload.get("importance", 0)),
            int(payload.get("tier", 1)),
            payload.get("topic_id"),
            payload.get("topic_source", "manual"),
            payload.get("topic_confidence"),
            int(payload.get("summarized", 0)),
        )
    )
    mem_id = int(cur.lastrowid)

    # Keep FTS rowid aligned with memory_events.id for easy joins.
    tags_list = safe_json_loads(payload.get("tags_json", "[]"))
    topic_id = (payload.get("topic_id") or "").strip().lower()
    if topic_id and topic_id not in tags_list:
        tags_list = [topic_id] + list(tags_list)
    tags_for_fts = " ".join(tags_list)

    cur.execute(
        "INSERT INTO memory_events_fts(rowid, text, tags) VALUES (?, ?, ?)",
        (mem_id, payload["text"], tags_for_fts)
    )
    conn.commit()
    return mem_id

def _mark_events_summarized_sync(conn: sqlite3.Connection, event_ids: list[int]) -> None:
    if not event_ids:
        return
    cur = conn.cursor()
    cur.execute(
        f"UPDATE memory_events SET summarized = 1 WHERE id IN ({','.join(['?']*len(event_ids))})",
        tuple(event_ids)
    )
    conn.commit()

def _upsert_summary_sync(conn: sqlite3.Connection, payload: dict) -> int:
    """Upsert by (topic_id). Keeps a single rolling summary per topic for now."""
    cur = conn.cursor()
    cur.execute("SELECT id FROM memory_summaries WHERE topic_id = ? ORDER BY id DESC LIMIT 1", (payload["topic_id"],))
    row = cur.fetchone()
    if row:
        sid = int(row[0])
        cur.execute(
            """
            UPDATE memory_summaries
            SET updated_at_utc=?, start_ts=?, end_ts=?, tags_json=?, importance=?, summary_text=?
            WHERE id=?
            """,
            (
                payload["updated_at_utc"],
                payload.get("start_ts"),
                payload.get("end_ts"),
                payload.get("tags_json", "[]"),
                int(payload.get("importance", 1)),
                payload["summary_text"],
                sid,
            )
        )
    else:
        cur.execute(
            """
            INSERT INTO memory_summaries (
                topic_id, created_at_utc, updated_at_utc,
                start_ts, end_ts, tags_json, importance, summary_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["topic_id"],
                payload["created_at_utc"],
                payload["updated_at_utc"],
                payload.get("start_ts"),
                payload.get("end_ts"),
                payload.get("tags_json", "[]"),
                int(payload.get("importance", 1)),
                payload["summary_text"],
            )
        )
        sid = int(cur.lastrowid)

    # Update FTS
    tags_for_fts = " ".join(safe_json_loads(payload.get("tags_json", "[]")))
    cur.execute("DELETE FROM memory_summaries_fts WHERE rowid = ?", (sid,))
    cur.execute(
        "INSERT INTO memory_summaries_fts(rowid, topic_id, summary_text, tags) VALUES (?, ?, ?, ?)",
        (sid, payload["topic_id"], payload["summary_text"], tags_for_fts)
    )

    conn.commit()
    return sid

def _search_memory_events_sync(conn: sqlite3.Connection, query: str, scope: str, limit: int = 8) -> list[dict]:
    fts_q = build_fts_query(query)
    if not fts_q:
        return []

    scope = (scope or "auto").lower()
    if scope == "hot":
        allowed_tiers = (0,)
    elif scope == "warm":
        allowed_tiers = (0, 1)
    elif scope == "cold":
        allowed_tiers = (2,)
    else:
        allowed_tiers = (0, 1, 2, 3)

    cur = conn.cursor()
    # Pull a wider set, then apply our scoring in Python.
    cur.execute(
        """
        SELECT me.id, me.created_at_utc, me.created_ts, me.channel_name, me.author_name,
               me.text, me.tags_json, me.importance, me.tier, me.topic_id, me.topic_source, me.topic_confidence,
               bm25(memory_events_fts) as rank
        FROM memory_events_fts
        JOIN memory_events me ON me.id = memory_events_fts.rowid
        WHERE memory_events_fts MATCH ?
          AND me.tier IN (0,1,2,3)
        LIMIT 60
        """,
        (fts_q,)
    )
    rows = cur.fetchall()

    scored: list[tuple[float, dict]] = []
    now = int(time.time())

    for (mid, created_at_utc, created_ts, channel_name, author_name, text, tags_json, importance, tier, topic_id, topic_source, topic_confidence, rank) in rows:
        tier = int(tier or 1)
        if tier not in allowed_tiers:
            continue
        importance = int(importance or 0)

        # Stage-aware retention: ignore junk that's far past the ladder intent.
        if stage_at_least("M1") and not stage_at_least("M2"):
            # M1: drop normal memories older than 14d
            if importance == 0 and (now - int(created_ts or 0)) > 14 * 86400:
                continue
        if stage_at_least("M2"):
            # M2+: drop normal memories once they pass cold window
            if importance == 0 and tier >= 3:
                continue

        base = -float(rank or 0.0)
        recency_boost = 0.0
        if tier == 0:
            recency_boost = 2.0
        elif tier == 1:
            recency_boost = 1.0
        elif tier == 2:
            recency_boost = 0.25
        else:
            recency_boost = 0.0

        importance_boost = 2.0 if importance == 1 else 0.0

        score = base + recency_boost + importance_boost

        scored.append((score, {
            "id": int(mid),
            "created_at_utc": created_at_utc,
            "created_ts": int(created_ts or 0),
            "channel_name": channel_name,
            "author_name": author_name,
            "text": text,
            "tags": safe_json_loads(tags_json),
            "importance": importance,
            "tier": tier,
        }))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [d for _, d in scored[:limit]]

def _search_memory_summaries_sync(conn: sqlite3.Connection, query: str, limit: int = 3) -> list[dict]:
    fts_q = build_fts_query(query)
    if not fts_q:
        return []
    cur = conn.cursor()
    cur.execute(
        """
        SELECT ms.id, ms.topic_id, ms.updated_at_utc, ms.start_ts, ms.end_ts, ms.tags_json, ms.importance, ms.summary_text,
               bm25(memory_summaries_fts) as rank
        FROM memory_summaries_fts
        JOIN memory_summaries ms ON ms.id = memory_summaries_fts.rowid
        WHERE memory_summaries_fts MATCH ?
        LIMIT 20
        """,
        (fts_q,)
    )
    rows = cur.fetchall()
    out = []
    for (sid, topic_id, updated_at_utc, start_ts, end_ts, tags_json, importance, summary_text, rank) in rows:
        out.append({
            "id": int(sid),
            "topic_id": topic_id,
            "updated_at_utc": updated_at_utc,
            "start_ts": int(start_ts or 0),
            "end_ts": int(end_ts or 0),
            "tags": safe_json_loads(tags_json),
            "importance": int(importance or 1),
            "summary_text": summary_text,
            "rank": float(rank or 0.0),
        })
    # Lower bm25 is better
    out.sort(key=lambda d: d["rank"])
    return out[:limit]

def _cleanup_memory_sync(conn: sqlite3.Connection) -> tuple[int, int]:
    """Returns (events_deleted, summaries_deleted)."""
    cur = conn.cursor()
    now = int(time.time())
    events_deleted = 0
    summaries_deleted = 0

    # Refresh tiers based on current age (M2+ uses tiers heavily)
    cur.execute(
        """
        UPDATE memory_events
        SET tier = CASE
            WHEN (? - created_ts) < 86400 THEN 0
            WHEN (? - created_ts) < 14*86400 THEN 1
            WHEN (? - created_ts) < 90*86400 THEN 2
            ELSE 3
        END
        """,
        (now, now, now)
    )

    if stage_at_least("M1") and not stage_at_least("M2"):
        # M1 retention: normal memories only live 14d
        cur.execute("DELETE FROM memory_events WHERE importance=0 AND created_ts < ?", (now - 14*86400,))
        events_deleted += cur.rowcount
    elif stage_at_least("M2"):
        # M2+ retention: normal memories live through cold window (90d)
        cur.execute("DELETE FROM memory_events WHERE importance=0 AND created_ts < ?", (now - 90*86400,))
        events_deleted += cur.rowcount

    # Prune orphaned FTS rows (safe, cheap enough at our scale)
    cur.execute("DELETE FROM memory_events_fts WHERE rowid NOT IN (SELECT id FROM memory_events)")
    cur.execute("DELETE FROM memory_summaries_fts WHERE rowid NOT IN (SELECT id FROM memory_summaries)")

    conn.commit()
    return events_deleted, summaries_deleted
def _fetch_topic_events_sync(conn: sqlite3.Connection, topic_id: str, min_age_days: int = 14, max_events: int = 200) -> list[dict]:
    topic_id = (topic_id or "").strip().lower()
    if not topic_id:
        return []
    cur = conn.cursor()
    cutoff = int(time.time()) - int(min_age_days) * 86400
    like_pat = f'%"{topic_id}"%'

    cur.execute(
        """
        SELECT id, created_at_utc, created_ts, channel_name, author_name, text, tags_json
        FROM memory_events
        WHERE importance = 1
          AND summarized = 0
          AND created_ts < ?
          AND (
                (topic_id IS NOT NULL AND topic_id = ?)
                OR (tags_json LIKE ?)
              )
        ORDER BY created_ts ASC
        LIMIT ?
        """,
        (cutoff, topic_id, like_pat, int(max_events))
    )
    rows = cur.fetchall()
    out = []
    for (eid, created_at_utc, created_ts, channel_name, author_name, text, tags_json) in rows:
        out.append({
            "id": int(eid),
            "created_at_utc": created_at_utc,
            "created_ts": int(created_ts or 0),
            "channel_name": channel_name,
            "author_name": author_name,
            "text": text,
            "tags": safe_json_loads(tags_json),
        })
    return out

def _get_topic_summary_sync(conn: sqlite3.Connection, topic_id: str) -> dict | None:
    topic_id = (topic_id or "").strip().lower()
    if not topic_id:
        return None
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, topic_id, updated_at_utc, start_ts, end_ts, tags_json, importance, summary_text
        FROM memory_summaries
        WHERE topic_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (topic_id,)
    )
    row = cur.fetchone()
    if not row:
        return None
    sid, topic_id, updated_at_utc, start_ts, end_ts, tags_json, importance, summary_text = row
    return {
        "id": int(sid),
        "topic_id": topic_id,
        "updated_at_utc": updated_at_utc,
        "start_ts": int(start_ts or 0),
        "end_ts": int(end_ts or 0),
        "tags": safe_json_loads(tags_json),
        "importance": int(importance or 1),
        "summary_text": summary_text,
    }



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
def _fetch_recent_context_sync(
    conn: sqlite3.Connection,
    channel_id: int,
    before_message_id: int,
    limit: int
) -> list[tuple[str, str, str]]:
    """
    Returns list of (created_at_utc, author_name, content), newest-first.
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT created_at_utc, author_name, content
        FROM messages
        WHERE channel_id = ?
          AND message_id < ?
          AND content IS NOT NULL
          AND TRIM(content) != ''
        ORDER BY message_id DESC
        LIMIT ?
        """,
        (channel_id, before_message_id, limit)
    )
    return cur.fetchall()


def _format_recent_context(rows: list[tuple[str, str, str]], max_chars: int, max_line_chars: int) -> str:
    """
    rows expected newest-first; formats oldest->newest, truncating to max_chars.
    """
    if not rows:
        return "(no recent context found)"

    # Reverse to chronological
    rows = list(reversed(rows))

    lines: list[str] = []
    total = 0

    for created_at_utc, author_name, content in rows:
        clean = " ".join((content or "").split())  # collapse whitespace/newlines
        if len(clean) > max_line_chars:
            clean = clean[: max_line_chars - 1] + "…"

        # Keep timestamp compact (ISO -> just time if present)
        ts = created_at_utc
        if "T" in created_at_utc:
            # e.g. 2026-01-11T04:24:09.123456 -> 04:24
            try:
                ts = created_at_utc.split("T", 1)[1][:5]
            except Exception:
                ts = created_at_utc

        line = f"[{ts}] {author_name}: {clean}"

        if total + len(line) + 1 > max_chars:
            break

        lines.append(line)
        total += len(line) + 1

    return "\n".join(lines) if lines else "(context truncated to 0 lines)"

async def get_recent_channel_context(channel_id: int, before_message_id: int) -> tuple[str, int]:
    async with db_lock:
        rows = await asyncio.to_thread(
            _fetch_recent_context_sync,
            db_conn,
            channel_id,
            before_message_id,
            RECENT_CONTEXT_LIMIT
        )
    text = _format_recent_context(rows, RECENT_CONTEXT_MAX_CHARS, MAX_LINE_CHARS)
    return text, len(rows)

# =========================
# TOPIC SUGGESTION (late-M3)
# =========================

def _list_known_topics_sync(conn: sqlite3.Connection, limit: int = 200) -> list[str]:
    cur = conn.cursor()
    topics = set()
    try:
        cur.execute("SELECT DISTINCT topic_id FROM memory_events WHERE topic_id IS NOT NULL AND topic_id != '' LIMIT ?", (int(limit),))
        for (t,) in cur.fetchall():
            if t:
                topics.add(str(t).strip().lower())
    except Exception:
        pass
    try:
        cur.execute("SELECT DISTINCT topic_id FROM memory_summaries WHERE topic_id IS NOT NULL AND topic_id != '' LIMIT ?", (int(limit),))
        for (t,) in cur.fetchall():
            if t:
                topics.add(str(t).strip().lower())
    except Exception:
        pass

    # Only keep slug-ish ids
    out = [t for t in topics if re.fullmatch(r"[a-z0-9_\-]{3,}", t)]
    out.sort()
    return out[: int(limit)]


def _topic_counts_sync(conn: sqlite3.Connection, limit: int = 15) -> list[tuple[str, int]]:
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT topic_id, COUNT(*) as n
            FROM memory_events
            WHERE topic_id IS NOT NULL AND topic_id != ''
            GROUP BY topic_id
            ORDER BY n DESC
            LIMIT ?
            """,
            (int(limit),)
        )
        rows = cur.fetchall()
        return [(str(t), int(n)) for (t, n) in rows if t]
    except Exception:
        return []


async def _get_topic_candidates() -> list[str]:
    """Return candidate topic_ids to choose from (allowlist preferred; else known topics)."""
    if TOPIC_ALLOWLIST:
        return list(TOPIC_ALLOWLIST)[:40]
    async with db_lock:
        known = await asyncio.to_thread(_list_known_topics_sync, db_conn, 200)
    return list(known)[:40]


def _safe_extract_json_obj(text: str) -> dict | None:
    if not text:
        return None
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return None
    try:
        import json as _json
        return _json.loads(m.group(0))
    except Exception:
        return None


async def _suggest_topic_id(text: str, candidates: list[str]) -> tuple[str | None, float]:
    """Suggest a topic_id from candidates. Returns (topic_id|None, confidence)."""
    if not (TOPIC_SUGGEST and candidates):
        return (None, 0.0)

    snippet = " ".join((text or "").split())
    if len(snippet) > 600:
        snippet = snippet[:599] + "…"

    cand_pack = ", ".join(candidates[:40])

    sys = (
        "You are a classifier that assigns a short memory snippet to ONE topic_id from a provided list.\n"
        "Return JSON only with keys topic_id and confidence.\n"
        "Rules:\n"
        "- topic_id must be exactly one of the provided candidates, or null if none fit.\n"
        "- confidence is a number from 0 to 1 representing certainty.\n"
        "- Do not include any extra keys or any extra text.\n"
    )

    user = f"Candidates: {cand_pack}\n\nSnippet: {snippet}\n"

    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": sys[:1900]},
                {"role": "user", "content": user[:1900]},
            ],
        )
        raw = (resp.choices[0].message.content or "").strip()
    except Exception:
        return (None, 0.0)

    obj = _safe_extract_json_obj(raw)
    if not isinstance(obj, dict):
        return (None, 0.0)

    topic = obj.get("topic_id")
    conf = obj.get("confidence")
    try:
        conf_f = float(conf)
    except Exception:
        conf_f = 0.0

    if topic is None:
        return (None, max(0.0, min(1.0, conf_f)))

    topic = str(topic).strip().lower()
    cand_set = set([t.lower() for t in candidates])
    if topic not in cand_set:
        return (None, 0.0)

    conf_f = max(0.0, min(1.0, conf_f))
    return (topic, conf_f)


async def remember_event(
    *,
    text: str,
    tags: list[str] | None,
    importance: int,
    message: discord.Message | None = None,
    topic_hint: str | None = None,
) -> dict | None:
    if not stage_at_least("M1"):
        return None

    tags = normalize_tags(tags or [])

    # Explicit topic wins (manual)
    topic_id: str | None = None
    if topic_hint:
        hinted = normalize_tags([topic_hint])
        topic_id = hinted[0] if hinted else None

    # Otherwise, derive from tags: first non-kind tag.
    if not topic_id and tags:
        for t in tags:
            if t and t not in RESERVED_KIND_TAGS:
                topic_id = t
                break

    topic_source = "manual" if topic_id else "none"
    topic_confidence: float | None = None

    # If still no topic, optionally suggest one from allowlist/known topics.
    if not topic_id and TOPIC_SUGGEST:
        candidates = await _get_topic_candidates()
        sug, conf = await _suggest_topic_id(text, candidates)
        if sug and conf >= TOPIC_MIN_CONF:
            topic_id = sug
            topic_source = "suggested"
            topic_confidence = conf
            if topic_id not in tags:
                tags = [topic_id] + tags

    # Always keep kind tags (decision/policy/canon) if present.
    tags = normalize_tags(tags)

    created_dt = None
    guild_id = None
    channel_id = None
    channel_name = None
    author_id = None
    author_name = None
    source_message_id = None

    if message is not None:
        created_dt = message.created_at if message.created_at else None
        guild_id = message.guild.id if message.guild else None
        channel_id = message.channel.id
        channel_name = getattr(message.channel, "name", str(message.channel))
        author_id = message.author.id
        author_name = str(message.author)
        source_message_id = message.id

    created_ts = utc_ts(created_dt) if created_dt else utc_ts()
    tier = infer_tier(created_ts) if stage_at_least("M2") else 1

    payload = {
        "created_at_utc": utc_iso(created_dt) if created_dt else utc_iso(),
        "created_ts": created_ts,
        "guild_id": guild_id,
        "channel_id": channel_id,
        "channel_name": channel_name,
        "author_id": author_id,
        "author_name": author_name,
        "source_message_id": source_message_id,
        "text": (text or "").strip(),
        "tags_json": safe_json_dumps(tags),
        "importance": int(1 if importance else 0),
        "tier": int(tier),
        "topic_id": topic_id,
        "topic_source": topic_source,
        "topic_confidence": topic_confidence,
        "summarized": 0,
    }

    if not payload["text"]:
        return None

    async with db_lock:
        mem_id = await asyncio.to_thread(_insert_memory_event_sync, db_conn, payload)

    return {
        "id": int(mem_id),
        "topic_id": topic_id,
        "topic_source": topic_source,
        "topic_confidence": topic_confidence,
        "tags": tags,
    }

async def recall_memory(prompt: str, scope: str | None = None) -> tuple[list[dict], list[dict]]:
    if not stage_at_least("M1"):
        return ([], [])
    scope = (scope or ("auto" if stage_at_least("M2") else "auto"))
    async with db_lock:
        events = await asyncio.to_thread(_search_memory_events_sync, db_conn, prompt, scope, 8)
        summaries = []
        if stage_at_least("M3"):
            summaries = await asyncio.to_thread(_search_memory_summaries_sync, db_conn, prompt, 3)
    return (events, summaries)

def format_memory_for_llm(events: list[dict], summaries: list[dict], max_chars: int = 1700) -> str:
    if not events and not summaries:
        return "(no relevant persistent memory found)"

    lines: list[str] = []

    if summaries:
        lines.append("Topic summaries:")
        for s in summaries:
            meta = f"[topic={s['topic_id']}] updated={s.get('updated_at_utc','')}"
            lines.append(f"- {meta}\n  {s['summary_text'].strip()}")
        lines.append("")

    if events:
        lines.append("Event memories:")
        for e in events:
            tags = ",".join(e.get("tags") or [])
            when = e.get("created_at_utc") or ""
            ch = e.get("channel_name") or ""
            who = e.get("author_name") or ""
            imp = "!" if int(e.get("importance") or 0) == 1 else ""
            topic = (e.get('topic_id') or '')
            topic_meta = f"topic={topic} " if topic else ''
            lines.append(f"- [{when}] {imp}{who} #{ch} {topic_meta}tags=[{tags}] :: {e['text'].strip()}")

    out = "\n".join(lines).strip()
    return out[:max_chars] if len(out) > max_chars else out

async def summarize_topic(topic_id: str, *, min_age_days: int = 14) -> str:
    """
    M3: consolidate important (importance=1) events for a topic into a rolling summary.
    Topic is currently: a tag string (e.g. 'baseline_week').
    """
    if not stage_at_least("M3"):
        return "Memory stage is not M3; summaries are disabled."

    topic_id = (topic_id or "").strip().lower()
    if not topic_id:
        return "Missing topic_id."

    async with db_lock:
        existing = await asyncio.to_thread(_get_topic_summary_sync, db_conn, topic_id)
        events = await asyncio.to_thread(_fetch_topic_events_sync, db_conn, topic_id, min_age_days, 200)

    if not events:
        if existing:
            return existing["summary_text"]
        return f"No eligible events to summarize for topic '{topic_id}'."

    # Build a compact source pack.
    # Keep the job stable: avoid giant prompts; we want durable gists, not exhaustive logs.
    lines = []
    for e in events:
        when = e.get("created_at_utc") or ""
        who = e.get("author_name") or ""
        txt = " ".join((e.get("text") or "").split())
        if len(txt) > 260:
            txt = txt[:259] + "…"
        lines.append(f"[{when}] {who}: {txt}")
    source_pack = "\\n".join(lines)
    if len(source_pack) > 6500:
        source_pack = source_pack[:6500] + "\\n…(truncated)"

    prior = existing["summary_text"] if existing else ""

    sys = (
        "You are Epoxy's memory consolidator.\\n"
        "Your job: produce a compact, staff-usable topic summary from the event snippets.\\n"
        "Rules:\\n"
        "- Output 3–8 bullet points.\\n"
        "- Prefer decisions, constraints, and stable takeaways.\\n"
        "- Do NOT invent facts. If uncertain, say so.\\n"
        "- Keep it concise and operational.\\n"
    )

    user = (
        f"Topic: {topic_id}\\n\\n"
        f"Existing summary (may be empty):\\n{prior}\\n\\n"
        f"New event snippets to incorporate (chronological):\\n{source_pack}\\n\\n"
        "Return only the updated bullet summary."
    )

    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": sys[:1900]},
                {"role": "user", "content": user[:1900]},
            ],
        )
        summary_text = (resp.choices[0].message.content or "").strip()
        if not summary_text:
            return "Summarizer returned empty output."
    except Exception as e:
        return f"Summarizer error: {e}"

    # Upsert + mark summarized
    start_ts = min(e["created_ts"] for e in events)
    end_ts = max(e["created_ts"] for e in events)
    tags = normalize_tags([topic_id])

    payload = {
        "topic_id": topic_id,
        "created_at_utc": utc_iso(),
        "updated_at_utc": utc_iso(),
        "start_ts": int(start_ts),
        "end_ts": int(end_ts),
        "tags_json": safe_json_dumps(tags),
        "importance": 1,
        "summary_text": summary_text,
    }
    event_ids = [e["id"] for e in events]

    async with db_lock:
        await asyncio.to_thread(_upsert_summary_sync, db_conn, payload)
        await asyncio.to_thread(_mark_events_summarized_sync, db_conn, event_ids)

    return summary_text

async def maintenance_loop() -> None:
    """Periodic cleanup + optional auto-summary."""
    if not stage_at_least("M1"):
        return

    interval = int(os.getenv("EPOXY_MAINTENANCE_INTERVAL_SECONDS", "3600"))
    min_age_days = int(os.getenv("EPOXY_SUMMARY_MIN_AGE_DAYS", "14"))

    while True:
        try:
            async with db_lock:
                deleted_events, _ = await asyncio.to_thread(_cleanup_memory_sync, db_conn)
            if deleted_events:
                print(f"[Memory] cleanup deleted_events={deleted_events} stage={MEMORY_STAGE}")

            if AUTO_SUMMARY and stage_at_least("M3"):
                # Very light auto-summary: summarize a couple topics per run based on unsummarized events.
                cutoff = int(time.time()) - min_age_days * 86400
                async with db_lock:
                    # Count topics based on topic_id for a bounded set.
                    rows = await asyncio.to_thread(
                        lambda c: c.execute(
                            "SELECT topic_id, COUNT(*) as n FROM memory_events WHERE importance=1 AND summarized=0 AND created_ts < ? AND topic_id IS NOT NULL AND topic_id != '' GROUP BY topic_id ORDER BY n DESC LIMIT 2",
                            (cutoff,)
                        ).fetchall(),
                        db_conn
                    )
                topics = [(t, int(n)) for (t, n) in rows if t]

                for topic_id, n in topics:
                    print(f"[Memory] auto-summarizing topic={topic_id} events={n}")
                    _ = await summarize_topic(topic_id, min_age_days=min_age_days)

        except Exception as e:
            print(f"[Memory] maintenance loop error: {e}")

        await asyncio.sleep(max(60, interval))

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

# =========================
# COMMANDS (staff tooling)
# =========================
def _in_allowed_channel(ctx: commands.Context) -> bool:
    try:
        return int(ctx.channel.id) in ALLOWED_CHANNEL_IDS
    except Exception:
        return False

@bot.command(name="memstage")
async def memstage(ctx: commands.Context):
    if not _in_allowed_channel(ctx):
        return
    await ctx.send(
        f"Memory stage: **{MEMORY_STAGE}** (rank={MEMORY_STAGE_RANK}) | "
        f"AUTO_CAPTURE={'1' if AUTO_CAPTURE else '0'} | AUTO_SUMMARY={'1' if AUTO_SUMMARY else '0'}"
    )

@bot.command(name="topics")
async def topics_cmd(ctx: commands.Context, limit: int = 15):
    """List known topics and/or the configured allowlist."""
    if not _in_allowed_channel(ctx):
        return
    lim = max(1, min(int(limit or 15), 30))

    allow = TOPIC_ALLOWLIST
    async with db_lock:
        counts = await asyncio.to_thread(_topic_counts_sync, db_conn, lim)
        known = await asyncio.to_thread(_list_known_topics_sync, db_conn, 200)

    lines = []
    lines.append(f"TOPIC_SUGGEST={'1' if TOPIC_SUGGEST else '0'} | TOPIC_MIN_CONF={TOPIC_MIN_CONF:.2f}")
    if allow:
        lines.append(f"Allowlist ({len(allow)}): {', '.join(allow[:40])}")
    else:
        lines.append("Allowlist: (empty) — suggestions will use known topics only")

    if counts:
        lines.append("")
        lines.append("Top topics by count:")
        for t, n in counts:
            lines.append(f"- {t}: {n}")
    else:
        lines.append("")
        lines.append("No topic counts yet.")

    if (not allow) and known:
        lines.append("")
        lines.append(f"Known topics ({len(known)}): {', '.join(known[:40])}")

    body = "\n".join(lines)
    await send_chunked(ctx.channel, f"```\n{body[:1700]}\n```")

@bot.command(name="remember")
async def remember_cmd(ctx: commands.Context, *, arg: str = ""):
    """
    Manual memory capture. Examples:
      !remember baseline_week,decision | We will run Baseline Week on Feb 1.
      !remember tags=baseline_week,decision importance=1 text=We will ...
      !remember This is important to keep.
    """
    if not _in_allowed_channel(ctx):
        return
    if not stage_at_least("M1"):
        await ctx.send("Memory stage is M0; set EPOXY_MEMORY_STAGE=M1+ to enable persistent memory.")
        return

    raw = (arg or "").strip()
    if not raw:
        await ctx.send("Usage: `!remember <tags> | <text>`  or  `!remember <text>`")
        return

    importance = 1  # explicit remember = important by default
    tags: list[str] = []
    text = raw

    # Key=val format
    if "tags=" in raw or "importance=" in raw or "text=" in raw:
        m_tags = re.search(r"tags=([^\s]+)", raw)
        m_imp = re.search(r"importance=([01])", raw)
        m_text = re.search(r"text=(.+)$", raw)
        if m_tags:
            tags = re.split(r"[;,]+", m_tags.group(1))
        if m_imp:
            importance = int(m_imp.group(1))
        if m_text:
            text = m_text.group(1).strip()
    elif "|" in raw:
        left, right = raw.split("|", 1)
        tags = re.split(r"[,\s]+", left.strip())
        text = right.strip()

    tags = normalize_tags(tags)
    saved = await remember_event(text=text, tags=tags, importance=importance, message=ctx.message)
    if not saved:
        await ctx.send("Nothing saved (empty text).")
        return
    mem_id = saved.get('id')
    topic_id = saved.get('topic_id')
    topic_source = saved.get('topic_source')
    conf = saved.get('topic_confidence')
    conf_txt = f" conf={conf:.2f}" if isinstance(conf, float) else ""
    topic_txt = f" topic={topic_id} ({topic_source}{conf_txt})" if topic_id else " topic=(none)"
    await ctx.send(f"Saved memory #{mem_id} tags={tags} importance={importance}{topic_txt} 🧴")

@bot.command(name="recall")
async def recall_cmd(ctx: commands.Context, *, query: str = ""):
    """Quick memory recall without calling the LLM."""
    if not _in_allowed_channel(ctx):
        return
    if not stage_at_least("M1"):
        await ctx.send("Memory stage is M0; nothing to recall yet.")
        return

    q = (query or "").strip()
    if not q:
        await ctx.send("Usage: `!recall <query>`")
        return

    scope = infer_scope(q) if stage_at_least("M2") else "auto"
    events, summaries = await recall_memory(q, scope=scope)

    pack = format_memory_for_llm(events, summaries, max_chars=1700)
    await send_chunked(ctx.channel, f"```\\n{pack}\\n```")

@bot.command(name="topic")
async def topic_cmd(ctx: commands.Context, topic_id: str = ""):
    """Show the current rolling summary for a topic."""
    if not _in_allowed_channel(ctx):
        return
    if not stage_at_least("M3"):
        await ctx.send("Memory stage is not M3; topic summaries are disabled.")
        return
    topic_id = (topic_id or "").strip().lower()
    if not topic_id:
        await ctx.send("Usage: `!topic <topic_id>`")
        return

    async with db_lock:
        s = await asyncio.to_thread(_get_topic_summary_sync, db_conn, topic_id)
    if not s:
        await ctx.send(f"No summary found for topic '{topic_id}'.")
        return

    pack = f"[topic={s['topic_id']}] updated={s.get('updated_at_utc','')}\\n{s['summary_text']}"
    await send_chunked(ctx.channel, f"```\\n{pack[:1700]}\\n```")

@bot.command(name="summarize")
async def summarize_cmd(ctx: commands.Context, topic_id: str = "", min_age_days: int = 14):
    """Run M3 consolidation for a topic."""
    if not _in_allowed_channel(ctx):
        return
    if not stage_at_least("M3"):
        await ctx.send("Memory stage is not M3; summaries are disabled.")
        return
    topic_id = (topic_id or "").strip().lower()
    if not topic_id:
        await ctx.send("Usage: `!summarize <topic_id> [min_age_days]`")
        return

    await ctx.send(f"Summarizing topic **{topic_id}** (min_age_days={min_age_days})…")
    out = await summarize_topic(topic_id, min_age_days=min_age_days)
    await send_chunked(ctx.channel, f"```\\n{out[:1700]}\\n```")

# Backfill config
BACKFILL_LIMIT = int(os.getenv("EPOXY_BACKFILL_LIMIT", "2000"))  # per channel, first boot
BACKFILL_PAUSE_EVERY = 200
BACKFILL_PAUSE_SECONDS = 0.25
RECENT_CONTEXT_LIMIT = int(os.getenv("EPOXY_RECENT_CONTEXT_LIMIT", "40"))
RECENT_CONTEXT_MAX_CHARS = int(os.getenv("EPOXY_RECENT_CONTEXT_CHARS", "6000"))
MAX_LINE_CHARS = int(os.getenv("EPOXY_RECENT_CONTEXT_LINE_CHARS", "300"))

async def backfill_channel(channel: discord.abc.Messageable) -> None:
    if not hasattr(channel, "id"):
        return

    channel_id = channel.id
    if channel_id not in ALLOWED_CHANNEL_IDS:
        print(f"[Backfill] Skip channel {channel_id}: not in ALLOWED_CHANNEL_IDS")
        return

    if await is_backfill_done(channel_id):
        print(f"[Backfill] Skip channel {channel_id}: already marked done")
        return

    print(f"[Backfill] Starting channel {channel_id} ({getattr(channel, 'name', 'unknown')}) limit={BACKFILL_LIMIT}")

    count = 0
    try:
        # oldest_first=True so inserts happen chronologically
        async for msg in channel.history(limit=BACKFILL_LIMIT, oldest_first=True):
            # Skip OTHER bots, but keep Epoxy's own messages for context coherence
            if msg.author.bot and bot.user and msg.author.id != bot.user.id:
                continue
            await log_message(msg)
            # OPTIONAL: if you want historical auto-capture into memory_events
            await maybe_auto_capture(msg)
            count += 1
            if count % BACKFILL_PAUSE_EVERY == 0:
                await asyncio.sleep(BACKFILL_PAUSE_SECONDS)
    except Exception as e:
        print(f"[Backfill] Error in channel {channel_id}: {e}")
        return

    await mark_backfill_done(channel_id)
    print(f"[Backfill] Done channel {channel_id}. Logged {count} messages.")
async def maybe_auto_capture(message: discord.Message) -> None:
    """Optional heuristics to store high-signal items without manual commands."""
    if not (AUTO_CAPTURE and stage_at_least("M1")):
        return
    content = (message.content or "").strip()
    if not content:
        return

    m = re.match(r"^(decision|policy|canon)\s*(\(([^)]+)\))?\s*:\s*(.+)$", content, flags=re.I)
    if m:
        kind = m.group(1).lower()
        topic = (m.group(3) or "").strip()
        text = (m.group(4) or "").strip()
        tags = [kind]
        if topic:
            tags = [topic] + tags
        await remember_event(text=text, tags=tags, importance=1, message=message, topic_hint=topic if topic else None)
        return

    # Lightweight hashtag style: \"#mem topic_id: ...\"
    m2 = re.match(r"^#mem\s+([a-zA-Z0-9_\\-]{3,})\s*:\s*(.+)$", content)
    if m2:
        topic = m2.group(1).strip().lower()
        text = (m2.group(2) or "").strip()
        await remember_event(text=text, tags=[topic], importance=1, message=message, topic_hint=topic)
        return

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

    # Start background maintenance (cleanup / optional summaries) once per process
    if stage_at_least("M1") and not getattr(bot, "_maintenance_task", None):
        bot._maintenance_task = asyncio.create_task(maintenance_loop())
        print(f"[Memory] maintenance loop started (stage={MEMORY_STAGE})")

@bot.event
async def on_message(message: discord.Message):
    # If it's a bot message, log Epoxy's own messages for context, then stop.
    if message.author.bot:
        if bot.user and message.author.id == bot.user.id:
            if message.channel.id in ALLOWED_CHANNEL_IDS:
                await log_message(message)
        return

    if message.channel.id not in ALLOWED_CHANNEL_IDS:
        return

    await log_message(message)
    await maybe_auto_capture(message)

    # If it's a command, don't also do the mention/LLM response path.
    if (message.content or "").lstrip().startswith("!"):
        await bot.process_commands(message)
        return
    # Only respond if mentioned
    if bot.user and bot.user in message.mentions:
        prompt = message.content.replace(f"<@{bot.user.id}>", "").strip()

        if not prompt:
            await message.channel.send("Yep? 🧴")
            await bot.process_commands(message)
            return

        try:
            MAX_MSG_CONTENT = 1900  # keep safely under the 2000-char hard limit

            recent_context, ctx_rows = await get_recent_channel_context(message.channel.id, message.id)

            # Cap each field individually (the API limit applies per `messages[i].content`)
            context_pack = build_context_pack()
            if len(context_pack) > MAX_MSG_CONTENT:
                context_pack = context_pack[:MAX_MSG_CONTENT]

            if len(recent_context) > MAX_MSG_CONTENT:
                recent_context = recent_context[:MAX_MSG_CONTENT]

            # Also cap the user prompt (just in case someone pastes a novel)
            safe_prompt = prompt[:MAX_MSG_CONTENT] if prompt else ""

            # Persistent memory (M1+) — only included when enabled by stage
            memory_pack = ""
            if stage_at_least("M1"):
                scope = infer_scope(safe_prompt) if stage_at_least("M2") else "auto"
                events, summaries = await recall_memory(safe_prompt, scope=scope)
                memory_pack = format_memory_for_llm(events, summaries, max_chars=MAX_MSG_CONTENT)
                if len(memory_pack) > MAX_MSG_CONTENT:
                    memory_pack = memory_pack[:MAX_MSG_CONTENT]

            print(
                f"[CTX] channel={message.channel.id} rows={ctx_rows} before={message.id} "
                f"ctx_chars={len(recent_context)} pack_chars={len(context_pack)} prompt_chars={len(safe_prompt)} "
                f"mem_chars={len(memory_pack)} stage={MEMORY_STAGE} "
                f"limit={RECENT_CONTEXT_LIMIT}"
            )

            chat_messages = [
                {"role": "system", "content": SYSTEM_PROMPT_BASE[:MAX_MSG_CONTENT]},
                {"role": "system", "content": context_pack},
                {
                    "role": "system",
                    "content": (
                        "Use ONLY the context provided in this request: "
                        "(1) Recent channel context, "
                        "(2) Relevant persistent memory (if provided), and "
                        "(3) Topic summaries (if provided). "
                        "Do not rely on general knowledge. "
                        "If the provided context is insufficient, say so and ask 1 clarifying question."
                    )[:MAX_MSG_CONTENT],
                },
                {
                    "role": "system",
                    "content": f"Recent channel context:\n{recent_context}"[:MAX_MSG_CONTENT],
                },
            ]

            if stage_at_least("M1") and memory_pack:
                chat_messages.append(
                    {
                        "role": "system",
                        "content": f"Relevant persistent memory:\n{memory_pack}"[:MAX_MSG_CONTENT],
                    }
                )

            chat_messages.append({"role": "user", "content": safe_prompt})

            resp = client.chat.completions.create(
                model=OPENAI_MODEL,
                # If you want less bubbly: uncomment temperature line and set low
                # temperature=0.2,
                messages=chat_messages,
            )

            reply = resp.choices[0].message.content or "(no output)"
            print(f"[REPLY] chars={len(reply)} parts={len(chunk_text(reply))}")
            await send_chunked(message.channel, reply)
        except Exception as e:
            print(f"[OpenAI] Error: {e}")
            await message.channel.send("Epoxy hiccuped. Check logs 🧴⚙️")

    await bot.process_commands(message)

bot.run(DISCORD_TOKEN)
