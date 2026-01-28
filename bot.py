import os
import sqlite3
import asyncio
import json
import re
import time
import hashlib
from datetime import datetime, timezone, timedelta
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
#   M4: manual meta-memories/narrative and role arcs
#   M5: semi-automatic human-in-loop memories being connected to manual meta-memories/narratives and roles
#   M6: semi-automatic human-in-loop self suggestion of meta-memories/narratives and roles connected to memories
#   M7: fully autonomous creation and management of memories and meta-memories/narratives+roles
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
# ---- Memory / staging config (drop-in) ----
import os
import re

# IDs: right-click channel → Copy ID (with Developer Mode on)
LFG_SOURCE_CHANNEL_ID     = 1465985366908600506  # #looking-for-group-pings
LFG_PUBLIC_CHANNEL_ID     = 1465824527043919986  # #lfg (public)
PADDOCK_LOUNGE_CHANNEL_ID = 1410966350196768809  # #paddock-lounge (members)

LFG_ROLE_NAME   = "Driving Pings"    # opt-in ping role
MEMBER_ROLE_KEYWORDS = ["Discovery", "Mastery"]

# Stage gating (default conservative; set env to enable higher stages)
MEMORY_STAGE = os.getenv("EPOXY_MEMORY_STAGE", "M0").strip().upper()
STAGE_RANK = {"M0": 0, "M1": 1, "M2": 2, "M3": 3}
MEMORY_STAGE_RANK = STAGE_RANK.get(MEMORY_STAGE, 0)

def stage_at_least(stage: str) -> bool:
    return MEMORY_STAGE_RANK >= STAGE_RANK.get(stage.strip().upper(), 0)

# Feature toggles (default OFF; flip via env when testing)
AUTO_CAPTURE = os.getenv("EPOXY_MEMORY_ENABLE_AUTO_CAPTURE", "0").strip() == "1"
AUTO_SUMMARY = os.getenv("EPOXY_MEMORY_ENABLE_AUTO_SUMMARY", "0").strip() == "1"
BOOTSTRAP_BACKFILL_CAPTURE = os.getenv("EPOXY_BOOTSTRAP_BACKFILL_CAPTURE", "0").strip() == "1"
BOOTSTRAP_CHANNEL_RESET = os.getenv("EPOXY_BOOTSTRAP_CHANNEL_RESET", "0").strip() == "1"


# Topic suggestion (late-M3 ergonomics)
TOPIC_SUGGEST = os.getenv("EPOXY_TOPIC_SUGGEST", "0").strip() == "1"
try:
    TOPIC_MIN_CONF = float(os.getenv("EPOXY_TOPIC_MIN_CONF", "0.85").strip())
except ValueError:
    TOPIC_MIN_CONF = 0.85

RESERVED_KIND_TAGS = {"decision", "policy", "canon", "profile", "protocol"}

_DEFAULT_TOPIC_ALLOWLIST = (
    "ops,announcements,community,coaches,workshops,league,one_on_one,"
    "member_support,conflict_resolution,marketing,content,website,pricing,billing,"
    "roadmap,infra,bugs,deployments,epoxy_bot,experiments,baby_brain,"
    "console_bay,coaching_method,layer_model,telemetry,track_guides"
)

# Allowlist behavior:
# - If env var is unset: use default allowlist above.
# - If env var is set to empty/whitespace: treat as "no explicit allowlist" (fallback to known DB topics).
# - Otherwise: parse env var.
_raw = os.getenv("EPOXY_TOPIC_ALLOWLIST")
if _raw is None:
    _TOPIC_ALLOWLIST_RAW = _DEFAULT_TOPIC_ALLOWLIST
else:
    _TOPIC_ALLOWLIST_RAW = _raw.strip()

if not _TOPIC_ALLOWLIST_RAW:
    TOPIC_ALLOWLIST: list[str] = []
else:
    TOPIC_ALLOWLIST = sorted({
        t.strip().lower()
        for t in re.split(r"[,\s;]+", _TOPIC_ALLOWLIST_RAW)
        if t.strip()
    } - RESERVED_KIND_TAGS)

print(
    f"[CFG] stage={MEMORY_STAGE} auto_capture={AUTO_CAPTURE} auto_summary={AUTO_SUMMARY} "
    f"topic_suggest={TOPIC_SUGGEST} topic_min_conf={TOPIC_MIN_CONF} "
    f"allowlist={'(db-topics)' if not TOPIC_ALLOWLIST else str(len(TOPIC_ALLOWLIST))+' topics'}"
)
# ---- end config ----


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

def _safe_table_info(cur, table: str):
    try:
        cur.execute(f"PRAGMA table_info({table})")
        rows = cur.fetchall()
        # rows: (cid, name, type, notnull, dflt_value, pk)
        cols = [r[1] for r in rows]
        return cols
    except Exception as e:
        return [f"<error: {e}>"]

def _schema_has_columns(cur, table: str, required: list[str]) -> tuple[bool, list[str]]:
    cols = set(_safe_table_info(cur, table))
    missing = [c for c in required if c not in cols]
    return (len(missing) == 0, missing)

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


    # Persistent memory events (M1+), upgraded for M3 parity
    cur.execute("""
    CREATE TABLE IF NOT EXISTS memory_events (
        id                     INTEGER PRIMARY KEY AUTOINCREMENT,

        -- core timestamps
        created_at_utc          TEXT,
        created_ts              INTEGER,
        updated_at_utc          TEXT,
        last_verified_at_utc    TEXT,
        expiry_at_utc           TEXT,

        -- scope/provenance
        scope                  TEXT DEFAULT NULL,     -- e.g. global | project:X | thread:Y | channel:<id>
        guild_id               INTEGER,
        channel_id             INTEGER,
        channel_name           TEXT,
        author_id              INTEGER,
        author_name            TEXT,
        source_message_id      INTEGER,

        -- "logged from" provenance (already used by you)
        logged_from_channel_id     INTEGER,
        logged_from_channel_name   TEXT,
        logged_from_message_id     INTEGER,
        source_channel_id          INTEGER,
        source_channel_name        TEXT,

        -- content + tags
        type                   TEXT DEFAULT 'event',  -- event|preference|concept|relationship|policy|instruction|skill|artifact_ref|note
        title                  TEXT DEFAULT NULL,
        text                   TEXT NOT NULL,
        tags_json              TEXT,

        -- quality + lifecycle
        confidence             REAL DEFAULT 0.6,
        stability              TEXT DEFAULT 'medium', -- volatile|medium|stable
        lifecycle              TEXT DEFAULT 'active', -- candidate|active|archived|deprecated|deleted
        superseded_by          INTEGER DEFAULT NULL,

        -- your existing controls
        importance             INTEGER DEFAULT 0,
        tier                   INTEGER DEFAULT 1,
        summarized             INTEGER DEFAULT 0,

        -- topic suggestion (already in your migrations; included here for fresh DBs)
        topic_id               TEXT,
        topic_source           TEXT DEFAULT 'manual',
        topic_confidence       REAL
    )
    """)


    # M3.5 topic suggestion columns (safe migrations for existing DBs)
    for stmt in [
        "ALTER TABLE memory_events ADD COLUMN topic_id TEXT",
        "ALTER TABLE memory_events ADD COLUMN topic_source TEXT DEFAULT 'manual'",
        "ALTER TABLE memory_events ADD COLUMN topic_confidence REAL",
        "ALTER TABLE memory_events ADD COLUMN logged_from_channel_id INTEGER",
        "ALTER TABLE memory_events ADD COLUMN logged_from_channel_name TEXT",
        "ALTER TABLE memory_events ADD COLUMN logged_from_message_id INTEGER",

        "ALTER TABLE memory_events ADD COLUMN source_channel_id INTEGER",
        "ALTER TABLE memory_events ADD COLUMN source_channel_name TEXT",
    ]:
        try:
            cur.execute(stmt)
        except sqlite3.OperationalError:
            pass

    # Best-effort backfill: set topic_id from first tag when possible.
    try:
        cur.execute("UPDATE memory_events SET topic_id = json_extract(tags_json, '$[0]') WHERE (topic_id IS NULL OR topic_id='') AND tags_json IS NOT NULL AND tags_json != '[]'")
    except sqlite3.OperationalError:
        pass

    # =========================
    # M3 parity migrations (safe for existing DBs)
    # =========================
    for stmt in [
        # memory_events upgrades
        "ALTER TABLE memory_events ADD COLUMN updated_at_utc TEXT",
        "ALTER TABLE memory_events ADD COLUMN last_verified_at_utc TEXT",
        "ALTER TABLE memory_events ADD COLUMN expiry_at_utc TEXT",

        "ALTER TABLE memory_events ADD COLUMN scope TEXT",
        "ALTER TABLE memory_events ADD COLUMN type TEXT DEFAULT 'event'",
        "ALTER TABLE memory_events ADD COLUMN title TEXT",
        "ALTER TABLE memory_events ADD COLUMN confidence REAL DEFAULT 0.6",
        "ALTER TABLE memory_events ADD COLUMN stability TEXT DEFAULT 'medium'",
        "ALTER TABLE memory_events ADD COLUMN lifecycle TEXT DEFAULT 'active'",
        "ALTER TABLE memory_events ADD COLUMN superseded_by INTEGER",

        # memory_summaries upgrades
        "ALTER TABLE memory_summaries ADD COLUMN summary_type TEXT DEFAULT 'topic_gist'",
        "ALTER TABLE memory_summaries ADD COLUMN scope TEXT",
        "ALTER TABLE memory_summaries ADD COLUMN covers_event_ids_json TEXT DEFAULT '[]'",
        "ALTER TABLE memory_summaries ADD COLUMN confidence REAL DEFAULT 0.6",
        "ALTER TABLE memory_summaries ADD COLUMN stability TEXT DEFAULT 'medium'",
        "ALTER TABLE memory_summaries ADD COLUMN last_verified_at_utc TEXT",
        "ALTER TABLE memory_summaries ADD COLUMN lifecycle TEXT DEFAULT 'active'",
        "ALTER TABLE memory_summaries ADD COLUMN tier INTEGER DEFAULT 2",
        "ALTER TABLE memory_summaries ADD COLUMN generated_by_model TEXT",
        "ALTER TABLE memory_summaries ADD COLUMN prompt_hash TEXT",
        "ALTER TABLE memory_summaries ADD COLUMN job_id TEXT",
    ]:
        try:
            cur.execute(stmt)
        except sqlite3.OperationalError:
            pass

    # -------------------------
    # Backfills (best-effort)
    # -------------------------
    # 1) updated_at_utc / last_verified_at_utc defaults
    try:
        cur.execute("UPDATE memory_events SET updated_at_utc = created_at_utc WHERE updated_at_utc IS NULL AND created_at_utc IS NOT NULL")
        cur.execute("UPDATE memory_events SET last_verified_at_utc = created_at_utc WHERE last_verified_at_utc IS NULL AND created_at_utc IS NOT NULL")
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute("UPDATE memory_summaries SET last_verified_at_utc = updated_at_utc WHERE last_verified_at_utc IS NULL AND updated_at_utc IS NOT NULL")
        cur.execute("UPDATE memory_summaries SET summary_type = 'topic_gist' WHERE summary_type IS NULL OR summary_type = ''")
    except sqlite3.OperationalError:
        pass

    # 2) scope defaults: keep it simple and deterministic
    #    - if channel_id exists, scope = channel:<id>, else guild:<id>, else global
    try:
        cur.execute("""
            UPDATE memory_events
            SET scope =
                CASE
                    WHEN channel_id IS NOT NULL THEN 'channel:' || channel_id
                    WHEN guild_id IS NOT NULL THEN 'guild:' || guild_id
                    ELSE 'global'
                END
            WHERE scope IS NULL OR scope = ''
        """)
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute("""
            UPDATE memory_summaries
            SET scope =
                CASE
                    WHEN topic_id IS NOT NULL AND topic_id != '' THEN 'topic:' || topic_id
                    ELSE 'global'
                END
            WHERE scope IS NULL OR scope = ''
        """)
    except sqlite3.OperationalError:
        pass

    # 3) type inference from tags (conservative, only sets if currently default/blank)
    #    Adjust mapping later; this is just to avoid everything being "event".
    try:
        cur.execute("""
            UPDATE memory_events
            SET type =
                CASE
                    WHEN tags_json LIKE '%"policy"%' THEN 'policy'
                    WHEN tags_json LIKE '%"protocol"%' THEN 'instruction'
                    WHEN tags_json LIKE '%"profile"%' THEN 'preference'
                    WHEN tags_json LIKE '%"decision"%' THEN 'event'
                    WHEN tags_json LIKE '%"canon"%' THEN 'concept'
                    ELSE 'event'
                END
            WHERE (type IS NULL OR type = '' OR type = 'event')
              AND tags_json IS NOT NULL AND tags_json != ''
        """)
    except sqlite3.OperationalError:
        pass

    # -------------------------
    # Indexes for new fields
    # -------------------------
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mem_events_scope ON memory_events(scope)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mem_events_type ON memory_events(type)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mem_events_lifecycle ON memory_events(lifecycle)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mem_events_last_verified ON memory_events(last_verified_at_utc)")

    cur.execute("CREATE INDEX IF NOT EXISTS idx_mem_summaries_type ON memory_summaries(summary_type)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mem_summaries_scope ON memory_summaries(scope)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mem_summaries_lifecycle ON memory_summaries(lifecycle)")

    # Summaries (M3), upgraded for auditability + multiple summary types
    cur.execute("""
    CREATE TABLE IF NOT EXISTS memory_summaries (
        id                     INTEGER PRIMARY KEY AUTOINCREMENT,

        -- what kind of summary this is
        summary_type           TEXT DEFAULT 'topic_gist',  -- event_digest|topic_gist|decision_log|preference_profile
        scope                  TEXT DEFAULT NULL,         -- same scheme as memory_events.scope

        -- legacy support: topic gists still keyed by topic_id
        topic_id               TEXT,

        -- time bounds and metadata
        created_at_utc          TEXT,
        updated_at_utc          TEXT,
        start_ts                INTEGER,
        end_ts                  INTEGER,

        tags_json              TEXT,
        importance             INTEGER DEFAULT 1,

        -- content
        summary_text           TEXT NOT NULL,

        -- audit + governance
        covers_event_ids_json  TEXT DEFAULT '[]',
        confidence             REAL DEFAULT 0.6,
        stability              TEXT DEFAULT 'medium',
        last_verified_at_utc   TEXT,
        lifecycle              TEXT DEFAULT 'active',
        tier                   INTEGER DEFAULT 2,

        -- generation metadata
        generated_by_model     TEXT,
        prompt_hash            TEXT,
        job_id                 TEXT
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

    # ---- Schema verification (logs show up in Railway) ----
    try:
        required_events = [
            "updated_at_utc", "last_verified_at_utc", "expiry_at_utc",
            "scope", "type", "title", "confidence", "stability", "lifecycle", "superseded_by",
        ]
        required_summaries = [
            "summary_type", "scope", "covers_event_ids_json",
            "confidence", "stability", "last_verified_at_utc",
            "lifecycle", "tier", "generated_by_model", "prompt_hash", "job_id",
        ]

        ok_e, missing_e = _schema_has_columns(cur, "memory_events", required_events)
        ok_s, missing_s = _schema_has_columns(cur, "memory_summaries", required_summaries)

        print(f"[DB] memory_events schema OK={ok_e} missing={missing_e}")
        print(f"[DB] memory_summaries schema OK={ok_s} missing={missing_s}")

        # Optional: dump the full column lists once (useful early on)
        print(f"[DB] memory_events cols: {_safe_table_info(cur, 'memory_events')}")
        print(f"[DB] memory_summaries cols: {_safe_table_info(cur, 'memory_summaries')}")
    except Exception as e:
        print(f"[DB] Schema verification failed: {e}")

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

def subject_user_tag(user_id: int) -> str:
    return f"subject:user:{int(user_id)}"

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

def parse_recall_scope(scope: str | None) -> tuple[str, int | None, int | None]:
    """
    Parse a recall scope string.

    Supported tokens (space- or comma-separated):
      - temporal: hot | warm | cold | auto
      - filters:  channel:<id> | guild:<id>

    Returns: (temporal_scope, guild_id, channel_id)
    """
    scope = (scope or "auto").strip().lower()
    if not scope:
        return ("auto", None, None)

    tokens = re.split(r"[\s,]+", scope)
    temporal = "auto"
    guild_id: int | None = None
    channel_id: int | None = None

    for tok in tokens:
        if tok in ("hot", "warm", "cold", "auto"):
            temporal = tok
            continue
        if tok.startswith("channel:"):
            try:
                channel_id = int(tok.split(":", 1)[1])
            except ValueError:
                channel_id = None
            continue
        if tok.startswith("guild:"):
            try:
                guild_id = int(tok.split(":", 1)[1])
            except ValueError:
                guild_id = None
            continue

    return (temporal, guild_id, channel_id)

def user_has_any_role(member: discord.Member, role_names: list[str]) -> bool:
    return any(role.name in role_names for role in member.roles)


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
            summarized,
            logged_from_channel_id, logged_from_channel_name, logged_from_message_id,
            source_channel_id, source_channel_name
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload["created_at_utc"],
            payload["created_ts"],
            payload.get("guild_id"),
            payload.get("channel_id"),
            payload.get("channel_name"),
            payload.get("author_id"),
            payload.get("author_name"),
            payload.get("source_message_id"),
            payload["text"],
            payload.get("tags_json", "[]"),
            int(payload.get("importance", 0)),
            int(payload.get("tier", 1)),
            payload.get("topic_id"),
            payload.get("topic_source", "none"),
            payload.get("topic_confidence"),
            int(payload.get("summarized", 0)),
            payload.get("logged_from_channel_id"),
            payload.get("logged_from_channel_name"),
            payload.get("logged_from_message_id"),
            payload.get("source_channel_id"),
            payload.get("source_channel_name"),
        ),
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
        (mem_id, payload["text"], tags_for_fts),
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

async def recall_profile_for_user(user_id: int, limit: int = 6) -> list[dict]:
    if not stage_at_least("M1"):
        return []
    tag = subject_user_tag(user_id)
    async with db_lock:
        return await asyncio.to_thread(_search_memory_events_by_tag_sync, db_conn, tag, "profile", limit)

def _search_memory_events_by_tag_sync(conn, subject_tag: str, kind_tag: str, limit: int) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, created_at_utc, channel_name, author_name, text, tags_json, importance, topic_id
        FROM memory_events
        WHERE tags_json LIKE ? AND tags_json LIKE ?
        ORDER BY created_ts DESC
        LIMIT ?
        """,
        (f'%"{subject_tag}"%', f'%"{kind_tag}"%', int(limit)),
    )
    rows = cur.fetchall()
    out = []
    for r in rows:
        out.append({
            "id": r[0],
            "created_at_utc": r[1],
            "channel_name": r[2],
            "author_name": r[3],
            "text": r[4],
            "tags": json.loads(r[5] or "[]"),
            "importance": r[6],
            "topic_id": r[7],
        })
    return out

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

    temporal_scope, guild_id, channel_id = parse_recall_scope(scope)

    if temporal_scope == "hot":
        allowed_tiers = (0,)
    elif temporal_scope == "warm":
        allowed_tiers = (0, 1)
    elif temporal_scope == "cold":
        allowed_tiers = (2,)
    else:
        allowed_tiers = (0, 1, 2, 3)


    cur = conn.cursor()

    # Pull a wider set, then apply our scoring in Python.
    # IMPORTANT: apply allowed tiers at SQL level to reduce junk work.
    tier_placeholders = ",".join("?" for _ in allowed_tiers)

    cur.execute(
        f"""
        SELECT me.id, me.created_at_utc, me.created_ts,
               me.channel_id, me.channel_name,
               me.author_id, me.author_name,
               me.source_message_id,
               me.text, me.tags_json, me.importance, me.tier,
               me.topic_id, me.topic_source, me.topic_confidence,

               me.logged_from_channel_id, me.logged_from_channel_name, me.logged_from_message_id,
               me.source_channel_id, me.source_channel_name,

               bm25(memory_events_fts) as rank
        FROM memory_events_fts
        JOIN memory_events me ON me.id = memory_events_fts.rowid
        WHERE memory_events_fts MATCH ?
        AND me.tier IN ({tier_placeholders})
        AND (? IS NULL OR me.channel_id = ?)
        AND (? IS NULL OR me.guild_id = ?)
        LIMIT 60

        """,
        (fts_q, *allowed_tiers, channel_id, channel_id, guild_id, guild_id),
    )
    rows = cur.fetchall()

    scored: list[tuple[float, dict]] = []
    now = int(time.time())

    for (
        mid, created_at_utc, created_ts,
        channel_id, channel_name,
        author_id, author_name,
        source_message_id,
        text, tags_json, importance, tier,
        topic_id, topic_source, topic_confidence,
        logged_from_channel_id, logged_from_channel_name, logged_from_message_id,
        source_channel_id, source_channel_name,
        rank,
    ) in rows:

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

        scored.append(
            (
                score,
                {
                    "id": int(mid),
                    "created_at_utc": created_at_utc,
                    "created_ts": int(created_ts or 0),

                    # back-compat + utility
                    "channel_id": channel_id,
                    "channel_name": channel_name,
                    "author_id": author_id,
                    "author_name": author_name,
                    "source_message_id": source_message_id,

                    "text": text,
                    "tags": safe_json_loads(tags_json),
                    "importance": importance,
                    "tier": tier,

                    # topic metadata (previously fetched but discarded)
                    "topic_id": topic_id,
                    "topic_source": topic_source,
                    "topic_confidence": topic_confidence,

                    # provenance (new)
                    "logged_from_channel_id": logged_from_channel_id,
                    "logged_from_channel_name": logged_from_channel_name,
                    "logged_from_message_id": logged_from_message_id,
                    "source_channel_id": source_channel_id,
                    "source_channel_name": source_channel_name,
                },
            )
        )

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

def _fetch_latest_memory_events_sync(
    conn: sqlite3.Connection,
    limit: int,
) -> list[tuple[str, str, str, str]]:
    """
    Returns newest-first list of (created_at_utc, author_name, channel_name, text)
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT created_at_utc, author_name, COALESCE(channel_name,''), text
        FROM memory_events
        WHERE text IS NOT NULL AND TRIM(text) != ''
        ORDER BY id DESC
        LIMIT ?
        """,
        (int(limit),),
    )
    return cur.fetchall()


def _fetch_memory_events_since_sync(
    conn: sqlite3.Connection,
    since_iso_utc: str,
    limit: int,
) -> list[tuple[str, str, str, str]]:
    """
    Returns newest-first list of (created_at_utc, author_name, channel_name, text)
    for memory_events with created_at_utc >= since_iso_utc.
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT created_at_utc, author_name, COALESCE(channel_name,''), text
        FROM memory_events
        WHERE created_at_utc >= ?
          AND text IS NOT NULL AND TRIM(text) != ''
        ORDER BY id DESC
        LIMIT ?
        """,
        (since_iso_utc, int(limit)),
    )
    return cur.fetchall()

def _format_memory_events_window(rows: list[tuple[str, str, str, str]], max_chars: int = 12000) -> str:
    if not rows:
        return "(no memory events)"
    rows = list(reversed(rows))  # chronological
    out_lines = []
    total = 0
    for created_at_utc, author_name, channel_name, text in rows:
        ts = created_at_utc
        if ts and "T" in ts:
            try:
                ts = ts.split("T", 1)[1][:5]
            except Exception:
                pass
        ch = channel_name or "unknown-channel"
        who = author_name or "unknown-author"
        clean = " ".join((text or "").split())
        line = f"[{ts}] {who} #{ch} :: {clean}"
        if total + len(line) + 1 > max_chars:
            break
        out_lines.append(line)
        total += len(line) + 1
    return "\n".join(out_lines)

def _fetch_last_messages_by_author_sync(conn, channel_id, before_message_id, author_name_like, limit=1):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT created_at_utc, author_name, content
        FROM messages
        WHERE channel_id = ?
          AND message_id < ?
          AND author_name LIKE ?
          AND content IS NOT NULL
          AND TRIM(content) != ''
        ORDER BY message_id DESC
        LIMIT ?
        """,
        (channel_id, before_message_id, author_name_like, limit),
    )
    return cur.fetchall()


def _get_backfill_done_sync(conn: sqlite3.Connection, channel_id: int) -> tuple[bool, str | None]:
    cur = conn.cursor()
    cur.execute(
        "SELECT backfill_done, last_backfill_at_utc FROM channel_state WHERE channel_id = ? LIMIT 1",
        (int(channel_id),),
    )
    row = cur.fetchone()
    if not row:
        return (False, None)
    return (int(row[0]) == 1, row[1])


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

BOOTSTRAP_CHANNEL_RESET_ALL = os.getenv("EPOXY_BOOTSTRAP_CHANNEL_RESET_ALL", "0").strip() == "1"

def _reset_all_backfill_done_sync(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        "UPDATE channel_state SET backfill_done = 0, last_backfill_at_utc = NULL"
    )
    conn.commit()

async def reset_all_backfill_done() -> None:
    async with db_lock:
        await asyncio.to_thread(_reset_all_backfill_done_sync, db_conn)

def _reset_backfill_done_sync(conn: sqlite3.Connection, channel_id: int) -> None:
    cur = conn.cursor()
    # If a row exists, flip the flag off and clear timestamp.
    cur.execute(
        """
        UPDATE channel_state
        SET backfill_done = 0,
            last_backfill_at_utc = NULL
        WHERE channel_id = ?
        """,
        (int(channel_id),),
    )
    conn.commit()

async def reset_backfill_done(channel_id: int) -> None:
    async with db_lock:
        await asyncio.to_thread(_reset_backfill_done_sync, db_conn, int(channel_id))


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

def _fetch_messages_since_sync(
    conn: sqlite3.Connection,
    channel_id: int,
    since_iso_utc: str,
    limit: int,
) -> list[tuple[str, str, str]]:
    """
    Returns newest-first list of (created_at_utc, author_name, content)
    for messages with created_at_utc >= since_iso_utc.
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT created_at_utc, author_name, content
        FROM messages
        WHERE channel_id = ?
          AND created_at_utc >= ?
          AND content IS NOT NULL
          AND TRIM(content) != ''
        ORDER BY message_id DESC
        LIMIT ?
        """,
        (int(channel_id), since_iso_utc, int(limit)),
    )
    return cur.fetchall()

def _parse_duration_to_minutes(token: str) -> int | None:
    t = (token or "").strip().lower()
    if t in {"hot", "--hot"}:
        return 30  # default hot window
    m = re.match(r"^(\d{1,3})\s*([mh])$", t)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2)
    return n * 60 if unit == "h" else n

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
            # Preserve both head + tail so we keep the "what" and the "so what"
            head_len = int(max_line_chars * 0.65)
            tail_len = max_line_chars - head_len - 3
            head = clean[:head_len].rstrip()
            tail = clean[-tail_len:].lstrip() if tail_len > 0 else ""
            clean = f"{head}…{tail}"

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

def _fetch_latest_messages_sync(
    conn: sqlite3.Connection,
    channel_id: int,
    limit: int,
) -> list[tuple[str, str, str]]:
    """
    Returns newest-first list of (created_at_utc, author_name, content).
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT created_at_utc, author_name, content
        FROM messages
        WHERE channel_id = ?
          AND content IS NOT NULL
          AND TRIM(content) != ''
        ORDER BY message_id DESC
        LIMIT ?
        """,
        (int(channel_id), int(limit)),
    )
    return cur.fetchall()


def _set_memory_origin_sync(
    conn: sqlite3.Connection,
    mem_id: int,
    source_channel_id: int | None,
    source_channel_name: str | None,
) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE memory_events
        SET source_channel_id = ?,
            source_channel_name = ?
        WHERE id = ?
        """,
        (source_channel_id, source_channel_name, int(mem_id)),
    )
    conn.commit()


async def set_memory_origin(mem_id: int, source_channel_id: int | None, source_channel_name: str | None) -> None:
    async with db_lock:
        await asyncio.to_thread(_set_memory_origin_sync, db_conn, int(mem_id), source_channel_id, source_channel_name)

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
    
def _parse_channel_id_token(token: str) -> int | None:
    token = (token or "").strip()
    if not token:
        return None
    # Channel mention: <#1234567890>
    m = re.match(r"^<#!?(\d{8,20})>$", token)
    if m:
        return int(m.group(1))
    # Raw digits
    m2 = re.match(r"^(\d{8,20})$", token)
    if m2:
        return int(m2.group(1))
    return None


def _extract_json_array(text: str) -> list[dict]:
    """
    Strict-ish: tries json.loads; if it fails, extracts the first [...] block and loads that.
    """
    import json

    if not text:
        return []
    text = text.strip()

    try:
        data = json.loads(text)
        return data if isinstance(data, list) else []
    except Exception:
        pass

    # Try to salvage: find outermost [ ... ]
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        blob = text[start : end + 1]
        try:
            data = json.loads(blob)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    return []

def _is_valid_topic_id(t: str) -> bool:
    return bool(re.match(r"^[a-z0-9_]{3,24}$", t or ""))

def _extract_json_array(text: str) -> list[dict]:
    if not text:
        return []
    text = text.strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, list) else []
    except Exception:
        pass

    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        blob = text[start:end+1]
        try:
            data = json.loads(blob)
            return data if isinstance(data, list) else []
        except Exception:
            return []
    return []


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
    logged_from_channel_id = None
    logged_from_channel_name = None
    logged_from_message_id = None

    source_channel_id = None
    source_channel_name = None

    if message is not None:
        created_dt = message.created_at if message.created_at else None
        guild_id = message.guild.id if message.guild else None

        # Where the memory was captured (command / auto-capture)
        logged_from_channel_id = message.channel.id
        logged_from_channel_name = getattr(message.channel, "name", str(message.channel))
        logged_from_message_id = message.id

        # Backward compatible fields (keep for now)
        channel_id = message.channel.id
        channel_name = getattr(message.channel, "name", str(message.channel))
        source_message_id = message.id

        author_id = message.author.id
        author_name = str(message.author)

        # If you don't yet support origin overrides, default origin to "unknown"
        # (or set it equal to logged_from if you prefer).
        source_channel_id = None
        source_channel_name = None

    created_ts = utc_ts(created_dt) if created_dt else utc_ts()
    tier = infer_tier(created_ts) if stage_at_least("M2") else 1

    payload = {
        "created_at_utc": utc_iso(created_dt) if created_dt else utc_iso(),
        "created_ts": created_ts,
        "guild_id": guild_id,

        # Backward compatibility
        "channel_id": channel_id,
        "channel_name": channel_name,
        "source_message_id": source_message_id,

        # New provenance
        "logged_from_channel_id": logged_from_channel_id,
        "logged_from_channel_name": logged_from_channel_name,
        "logged_from_message_id": logged_from_message_id,
        "source_channel_id": source_channel_id,
        "source_channel_name": source_channel_name,

        "author_id": author_id,
        "author_name": author_name,
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

def _budget_and_diversify_events(events: list[dict], scope: str, limit: int = 8) -> list[dict]:
    """
    Apply simple budgets to reduce near-duplicates and keep a healthy mix.

    Deterministic (stable for a given input ordering) so you can test retrieval behavior.
    Enforces tier budgets (hot/warm/cold) in M2+ to prevent cold-memory bleed.
    """
    if not events or int(limit or 0) <= 0:
        return []

    limit = int(limit)

    # Heuristics: keep variety across topic/channel/author while preserving relevance ordering.
    topic_cap = 3
    channel_cap = 4
    author_cap = 3

    # If the user explicitly scoped to a single channel or guild, don't waste budget on that axis.
    # Accept both old ("channel:") and tokenized scopes ("hot channel:123").
    s = (scope or "").strip().lower()
    if ("channel:" in s) or ("guild:" in s):
        channel_cap = limit

    # Tier budgets (0=hot, 1=warm, 2=cold, 3=archive).
    # Default tuned for limit=8 -> 4 hot / 3 warm / 1 cold.
    def _tier_caps(n: int) -> dict[int, int]:
        n = max(1, int(n))
        if n <= 3:
            return {0: n, 1: 0, 2: 0, 3: 0}

        hot = max(1, int(round(n * 0.50)))
        warm = max(0, int(round(n * 0.375)))
        cold = max(0, n - hot - warm)

        # Fix rounding drift deterministically.
        while hot + warm + cold < n:
            warm += 1
        while hot + warm + cold > n:
            if warm > 0:
                warm -= 1
            elif hot > 1:
                hot -= 1
            else:
                cold = max(0, cold - 1)

        return {0: hot, 1: warm, 2: cold, 3: 0}

    caps = _tier_caps(limit) if stage_at_least("M2") else {0: limit, 1: limit, 2: limit, 3: limit}
    tier_counts: dict[int, int] = {}

    def _fp(e: dict) -> str:
        # Events use "text"; keep fallback to "content" for older rows/paths.
        txt = (e.get("text") or e.get("content") or "").strip().lower()
        txt = re.sub(r"\s+", " ", txt)
        return hashlib.sha1(txt.encode("utf-8")).hexdigest()

    seen: set[str] = set()
    topic_counts: dict[str, int] = {}
    channel_counts: dict[str, int] = {}
    author_counts: dict[str, int] = {}

    out: list[dict] = []
    for e in events:
        tier = int(e.get("tier") if e.get("tier") is not None else 1)

        # In M2+, archive is generally noise for recall unless you explicitly fetch it.
        if stage_at_least("M2") and tier >= 3:
            continue

        # Enforce tier budget (only meaningful in M2+).
        if stage_at_least("M2"):
            if tier_counts.get(tier, 0) >= caps.get(tier, 0):
                continue

        fp = _fp(e)
        if fp in seen:
            continue
        seen.add(fp)

        t = (e.get("topic_id") or "").strip()
        c = str(e.get("channel_id") or "")
        a = str(e.get("author_id") or "")

        if t and topic_counts.get(t, 0) >= topic_cap:
            continue
        if c and channel_counts.get(c, 0) >= channel_cap:
            continue
        if a and author_counts.get(a, 0) >= author_cap:
            continue

        out.append(e)

        if stage_at_least("M2"):
            tier_counts[tier] = tier_counts.get(tier, 0) + 1
        if t:
            topic_counts[t] = topic_counts.get(t, 0) + 1
        if c:
            channel_counts[c] = channel_counts.get(c, 0) + 1
        if a:
            author_counts[a] = author_counts.get(a, 0) + 1

        if len(out) >= limit:
            break

    return out

async def recall_memory(prompt: str, scope: str | None = None) -> tuple[list[dict], list[dict]]:
    if not stage_at_least("M1"):
        return ([], [])
    scope = (scope or ("auto" if stage_at_least("M2") else "auto"))
    async with db_lock:
        events = await asyncio.to_thread(_search_memory_events_sync, db_conn, prompt, scope, 40)
        events = _budget_and_diversify_events(events, scope, limit=8)
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

            when = e.get("created_at_utc") or "unknown-date"
            ch = e.get("channel_name") or "unknown-channel"
            who = e.get("author_name") or "unknown-author"
            imp = "!" if int(e.get("importance") or 0) == 1 else ""

            topic = (e.get("topic_id") or "")
            topic_meta = f"topic={topic} " if topic else ""

            # --- Provenance (explicit; never guess) ---
            # logged_from = where Epoxy captured the memory (command/auto-capture channel)
            logged_from_ch = e.get("logged_from_channel_name") or e.get("channel_name") or "unknown-channel"
            logged_from_id = e.get("logged_from_channel_id") or e.get("channel_id")
            logged_from = f"#{logged_from_ch}" if logged_from_ch else "unknown-channel"
            if logged_from_id:
                logged_from = f"{logged_from}({logged_from_id})"

            # origin = where the underlying idea/message originally occurred (if tracked separately)
            origin_ch = e.get("source_channel_name")
            origin_id = e.get("source_channel_id")
            if origin_ch or origin_id:
                origin = f"#{origin_ch or 'unknown-channel'}"
                if origin_id:
                    origin = f"{origin}({origin_id})"
            else:
                origin = "unknown"

            src_msg = e.get("source_message_id")
            src_meta = f" msg={src_msg}" if src_msg else ""

            prov = f"prov=logged_from:{logged_from} origin:{origin}{src_meta} "

            text = (e.get("text") or "").strip()

            lines.append(
                f"- [{when}] {imp}{who} {prov}{topic_meta}tags=[{tags}] :: {text}"
            )

    out = "\n".join(lines).strip()
    return out[:max_chars] if len(out) > max_chars else out

def format_profile_for_llm(user_blocks: list[tuple[int, str, list[dict]]], max_chars: int = 900) -> str:
    """
    user_blocks: [(user_id, display_name, events), ...]
    """
    if not user_blocks:
        return ""

    lines: list[str] = ["Profile notes (curated):"]
    for user_id, display_name, events in user_blocks:
        if not events:
            continue
        lines.append(f"- <@{user_id}> ({display_name}):")
        for e in events:
            when = e.get("created_at_utc") or "unknown-date"
            who = e.get("author_name") or "unknown-author"
            ch = e.get("channel_name") or "unknown-channel"
            txt = (e.get("text") or "").strip()
            if txt:
                lines.append(f"  • [{when}] {who} #{ch} :: {txt}")
        lines.append("")

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
        done, _last = await asyncio.to_thread(_get_backfill_done_sync, db_conn, channel_id)
    return bool(done)

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

@bot.command(name="profile")
async def cmd_profile(ctx, *, raw: str = ""):
    """
    Save a profile memory about a person.
    Usage: !profile @User | text
           !profile 123456789012345678 | text
    """
    if not raw:
        await ctx.send("Usage: !profile @User | text")
        return

    if ctx.channel.id not in ALLOWED_CHANNEL_IDS:
        return

    if "|" not in raw:
        await ctx.send("Usage: !profile @User | text")
        return

    left, text = [s.strip() for s in raw.split("|", 1)]
    if not text:
        await ctx.send("Usage: !profile @User | text")
        return

    user_id = None
    if ctx.message.mentions:
        user_id = ctx.message.mentions[0].id
    else:
        m = re.search(r"\b(\d{8,20})\b", left)
        if m:
            user_id = int(m.group(1))

    if not user_id:
        await ctx.send("Couldn't find a user. Usage: !profile @User | text")
        return

    tags = [subject_user_tag(user_id), "profile"]

    res = await remember_event(
        text=text,
        tags=tags,
        importance=1,
        message=ctx.message,
        topic_hint=None,
    )

    if not res:
        await ctx.send("Profile memory not saved (stage may be < M1).")
        return

    await ctx.send(f"Saved profile memory for <@{user_id}>.")

@bot.command(name="memlast")
async def cmd_memlast(ctx, n: int = 5):
    if ctx.channel.id not in ALLOWED_CHANNEL_IDS:
        return
    async with db_lock:
        rows = await asyncio.to_thread(_debug_last_memories_sync, db_conn, int(n))
    lines = ["Last memories:"] + [f"- #{r['id']} topic={r['topic_id']} tags={r['tags']}\n  {r['text'][:120]}" for r in rows]
    await ctx.send("\n".join(lines)[:1900])

def _debug_last_memories_sync(conn, n: int):
    cur = conn.cursor()
    cur.execute("SELECT id, text, tags_json, topic_id FROM memory_events ORDER BY id DESC LIMIT ?", (int(n),))
    out=[]
    for i,t,tags,topic in cur.fetchall():
        out.append({"id": i, "text": t or "", "tags": __import__("json").loads(tags or "[]"), "topic_id": topic or ""})
    return out

@bot.command(name="memfind")
async def cmd_memfind(ctx, *, q: str):
    if ctx.channel.id not in ALLOWED_CHANNEL_IDS:
        return
    events, summaries = await recall_memory(q, scope="auto")
    txt = format_memory_for_llm(events, summaries, max_chars=1800)
    await ctx.send(f"Recall results for: {q}\n{txt}"[:1900])

# NEED TO ADD channel_state.last_mined_message_id later to enable "mine from last cursor" funtionality
# NEED TO ADD profile referencing via ID, currently profiles are referenced by text and sometimes only first names which will get flimsy later
@bot.command(name="mine")
async def cmd_mine(ctx, *args):
    """
    Mine high-signal memories from the messages table.

    Usage:
      !mine
      !mine <channel_id>
      !mine <#channel>
      !mine <channel_id> <limit>
      !mine <#channel> <limit>

    Optional time-based mode: "hot" / "15m" / "2h" (min 5 min, max 4 hours)

    Example:
      !mine hot
      !mine 45m
      !mine <#channel> hot
      !mine <#channel> 2h

    Notes:
      - Runs from any channel, but will only mine channels in ALLOWED_CHANNEL_IDS.
      - Stores mined items as memory_events via remember_event().
      - Sets origin provenance to the mined channel (source_channel_id/source_channel_name).
    """
    if ctx.channel.id not in ALLOWED_CHANNEL_IDS:
        await ctx.send("This command isn't enabled in this channel.")
        return

    if not stage_at_least("M1"):
        await ctx.send("Memory is not enabled (stage < M1).")
        return

    # Defaults
    target_channel_id = ctx.channel.id
    limit = 200  # default mining window size

    # Parse args: first token may be channel; second may be limit
    if len(args) >= 1:
        maybe_ch = _parse_channel_id_token(args[0])
        if maybe_ch:
            target_channel_id = maybe_ch
            if len(args) >= 2 and str(args[1]).isdigit():
                limit = max(50, min(500, int(args[1])))
        elif str(args[0]).isdigit():
            # could be a limit
            limit = max(50, min(500, int(args[0])))

    if target_channel_id not in ALLOWED_CHANNEL_IDS:
        await ctx.send("That channel is not in Epoxy's allowlist, so I won't mine it.")
        return

    # Resolve channel name for provenance (best effort)
    target_channel_name = None
    ch_obj = bot.get_channel(target_channel_id)
    if ch_obj is None:
        try:
            ch_obj = await bot.fetch_channel(target_channel_id)
        except Exception:
            ch_obj = None
    if ch_obj is not None:
        target_channel_name = getattr(ch_obj, "name", None) or str(ch_obj)

    # Optional time-based mode: "hot" / "15m" / "2h"
    hot_minutes = None
    for a in args:
        hm = _parse_duration_to_minutes(str(a))
        if hm is not None:
            hot_minutes = max(5, min(240, hm))  # clamp 5m..4h
            break

    if hot_minutes is not None:
        since_dt = discord.utils.utcnow() - timedelta(minutes=hot_minutes)
        since_iso = since_dt.isoformat()
        async with db_lock:
            rows = await asyncio.to_thread(
                _fetch_messages_since_sync,
                db_conn,
                target_channel_id,
                since_iso,
                500,  # cap so hot can't explode
            )
        mode_label = f"hot({hot_minutes}m)"
    else:
        async with db_lock:
            rows = await asyncio.to_thread(_fetch_latest_messages_sync, db_conn, target_channel_id, limit)
        mode_label = f"last({limit})"

    if not rows:
        await ctx.send("No messages found to mine for that channel.")
        return


    # Convert to chronological text block (oldest -> newest)
    # Use your existing formatter to keep consistent line shapes.
    window_text = _format_recent_context(rows, max_chars=12000, max_line_chars=350)

    # Build strict extraction prompt
    allowlist = TOPIC_ALLOWLIST[:] if TOPIC_ALLOWLIST else []
    allowlist_str = ", ".join(allowlist) if allowlist else "(none; use null topic_id)"

    extraction_instructions = f"""
You are Epoxy's memory miner.

You will be given a block of Discord messages from ONE channel.
Extract durable, high-signal MEMORY EVENTS only. Do NOT extract chatter unless you are extracting an inside joke, social pattern, or another similar abstraction.

Return a JSON ARRAY ONLY (no markdown, no commentary), with 0-12 items.
Each item must be an object with EXACT keys:
- "text": string (max 240 chars), the memory content written as a standalone statement
- "kind": one of ["decision","policy","canon","profile","proposal","insight","task"]
- "topic_id": either null OR one of this allowlist: [{allowlist_str}]
- "importance": 0 or 1 (1 only if it will matter weeks later)
- "confidence": number 0.0-1.0

Rules:
- Do NOT invent channel names, dates, authors, or message ids. Do NOT include them in "text".
- If you cannot confidently assign a topic_id from allowlist, use null.
- Avoid duplicates / near-duplicates.
- Prefer writing memories in a neutral factual style.
- Only produce "profile" if the text is a stable trait or preference about an individual AND the individual's name appears in the window text.
  For profile items, include the person's name inside "text" (e.g., "Sammy prefers ..."). Still no invented IDs.
""".strip()

    # Call LLM
    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": extraction_instructions[:1900]},
                {"role": "user", "content": f"Channel window:\n{window_text}"[:12000]},
            ],
        )
        raw = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        await ctx.send(f"Mine failed (LLM error): {e}")
        return

    items = _extract_json_array(raw)
    if not items:
        await ctx.send("Mine produced no usable JSON items.")
        return

    # Validate + insert
    allowed_kinds = {"decision","policy","canon","profile","proposal","insight","task"}
    allow_topics = set(TOPIC_ALLOWLIST or [])
    saved = 0
    topics_used: dict[str, int] = {}

    for it in items:
        try:
            text = (it.get("text") or "").strip()
            kind = (it.get("kind") or "").strip().lower()
            topic_id = it.get("topic_id", None)
            importance = int(it.get("importance", 0))
            conf = float(it.get("confidence", 0.0))
        except Exception:
            continue

        if not text:
            continue
        if kind not in allowed_kinds:
            kind = "insight"
        importance = 1 if importance == 1 else 0

        # Topic must be allowlisted or null
        if isinstance(topic_id, str):
            topic_id = topic_id.strip().lower()
            if topic_id not in allow_topics:
                topic_id = None
        else:
            topic_id = None

        # Conservative confidence gate (optional)
        # If you want it stricter, raise this.
        if conf < 0.55:
            continue

        # Build tags: keep kinds, optional topic tag
        tags = [kind]
        if topic_id:
            tags = [topic_id] + tags

        res = await remember_event(
            text=text,
            tags=tags,
            importance=importance,
            message=ctx.message,  # capture location
            topic_hint=topic_id,  # ensures topic_id wins if set
        )
        if not res:
            continue

        # Set origin provenance to the mined channel (not the command channel)
        await set_memory_origin(int(res["id"]), target_channel_id, target_channel_name)

        saved += 1
        if topic_id:
            topics_used[topic_id] = topics_used.get(topic_id, 0) + 1

    topic_summary = ", ".join(f"{k}×{v}" for k, v in sorted(topics_used.items(), key=lambda x: (-x[1], x[0])))
    if not topic_summary:
        topic_summary = "(none)"

    await ctx.send(
        f"🧴⛏️ Mined {len(rows)} msgs ({mode_label}) from <#{target_channel_id}> → saved {saved} memories. Topics: {topic_summary}"
    )

@bot.command(name="ctxpeek")
async def ctxpeek(ctx: commands.Context, n: int = 10):
    if not _in_allowed_channel(ctx):
        return
    n = max(1, min(int(n), 40))
    # Use a huge "before" so we get latest
    before = 2**63 - 1
    async with db_lock:
        rows = await asyncio.to_thread(_fetch_recent_context_sync, db_conn, ctx.channel.id, before, n)
    txt = _format_recent_context(rows, 1900, MAX_LINE_CHARS)
    await ctx.send(f"Recent context ({len(rows)} rows):\n{txt}")

@bot.command(name="topicsuggest")
async def cmd_topicsuggest(ctx, *args):
    """
    Suggest new topic_ids to add to the allowlist based on:
      - recent channel messages (default), or
      - existing saved memory events (mem mode)

    Usage:
      !topicsuggest
      !topicsuggest hot
      !topicsuggest 45m
      !topicsuggest <#channel> hot
      !topicsuggest <#channel> 200

      !topicsuggest mem
      !topicsuggest mem hot
      !topicsuggest mem 2h
    """
    if ctx.channel.id not in ALLOWED_CHANNEL_IDS:
        await ctx.send("This command isn't enabled in this channel.")
        return

    # Mode: messages (default) vs memories
    mode = "messages"
    for a in args:
        if str(a).strip().lower() in {"mem", "memory", "memories"}:
            mode = "memories"
            break

    target_channel_id = ctx.channel.id
    limit = 250

    # Parse args: channel + (hot duration OR limit)
    if len(args) >= 1:
        maybe_ch = _parse_channel_id_token(str(args[0]))
        if maybe_ch:
            target_channel_id = maybe_ch
            if len(args) >= 2 and str(args[1]).isdigit():
                limit = max(50, min(500, int(args[1])))
        elif str(args[0]).isdigit():
            limit = max(50, min(500, int(args[0])))

    if target_channel_id not in ALLOWED_CHANNEL_IDS:
        await ctx.send("That channel is not in Epoxy's allowlist, so I won't analyze it.")
        return

    # duration?
    hot_minutes = None
    for a in args:
        hm = _parse_duration_to_minutes(str(a))
        if hm is not None:
            hot_minutes = max(5, min(240, hm))
            break

    # Resolve channel name (best effort)
    target_channel_name = None
    ch_obj = bot.get_channel(target_channel_id)
    if ch_obj is None:
        try:
            ch_obj = await bot.fetch_channel(target_channel_id)
        except Exception:
            ch_obj = None
    if ch_obj is not None:
        target_channel_name = getattr(ch_obj, "name", None) or str(ch_obj)

    # Fetch window (messages vs memories)
    if mode == "memories":
        if hot_minutes is not None:
            since_dt = discord.utils.utcnow() - timedelta(minutes=hot_minutes)
            since_iso = since_dt.isoformat()
            async with db_lock:
                mem_rows = await asyncio.to_thread(_fetch_memory_events_since_sync, db_conn, since_iso, 400)
            mode_label = f"mem_hot({hot_minutes}m)"
        else:
            async with db_lock:
                mem_rows = await asyncio.to_thread(_fetch_latest_memory_events_sync, db_conn, 300)
            mode_label = "mem_last(300)"

        if not mem_rows:
            await ctx.send("No memory events found to analyze.")
            return

        window_text = _format_memory_events_window(mem_rows, max_chars=12000)
        source_label = "MEMORY EVENTS (already curated)"

    else:
        if hot_minutes is not None:
            since_dt = discord.utils.utcnow() - timedelta(minutes=hot_minutes)
            since_iso = since_dt.isoformat()
            async with db_lock:
                rows = await asyncio.to_thread(_fetch_messages_since_sync, db_conn, target_channel_id, since_iso, 500)
            mode_label = f"msg_hot({hot_minutes}m)"
        else:
            async with db_lock:
                rows = await asyncio.to_thread(_fetch_latest_messages_sync, db_conn, target_channel_id, limit)
            mode_label = f"msg_last({limit})"

        if not rows:
            await ctx.send("No messages found to analyze.")
            return

        window_text = _format_recent_context(rows, max_chars=12000, max_line_chars=450)
        source_label = "RAW MESSAGES (chat log)"

    existing = set(TOPIC_ALLOWLIST or [])
    existing_str = ", ".join(sorted(existing)) if existing else "(none)"

    prompt = f"""
    You are Epoxy's topic curator.

    Goal: propose NEW topic_ids to add to an allowlist for organizing memories.
    You will be given either Discord message logs or memory event entries.

    Return a JSON ARRAY ONLY (no markdown, no commentary), with 0-8 items.
    Each item must have EXACT keys:
    - "topic_id": snake_case string, 3-24 chars, [a-z0-9_], must NOT already exist
    - "label": short human label
    - "why": 1 sentence why this topic is distinct/useful
    - "examples": array of 2-3 short phrases quoted/paraphrased from the window (no invention)
    - "confidence": number 0.0-1.0

    HARD RULES:
    - Do NOT propose any topic_id that is already in: [{existing_str}]
    - Do NOT invent themes not supported by the window.
    - Avoid overly broad topics ("general", "random", "chat").
    - Avoid overly specific topics tied to a single person, single workshop, single document, or single one-off event.
    - Each proposed topic MUST be supported by at least 3 distinct messages/memories in the window.
    - Prefer topics that will still be useful 3+ months from now.

    PREFERRED GRANULARITY (examples of the right size):
    - epoxy_development (build/test/deploy/memory system)
    - workshops (planning/running workshop ideas/format)
    - student_challenges (coaching cases / recurring pain points)
    - coaching_method (methods/models/frameworks)
    - governance_and_comms (ethics/docs/guidelines/vibe/public copy)

    If a candidate feels like a subtopic of one of the above sizes, propose the broader bucket instead.

    Return JSON only.
    """.strip()



    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": prompt[:1900]},
                {"role": "user", "content": (
                    f"Source: {source_label}\n"
                    f"Channel: {target_channel_name or target_channel_id}\n"
                    f"Window:\n{window_text}"
                )[:12000]},
            ],
        )
        raw = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        await ctx.send(f"topicsuggest failed (LLM error): {e}")
        return

    items = _extract_json_array(raw)

    # Validate / filter
    out = []
    for it in items:
        tid = (it.get("topic_id") or "").strip().lower()
        if not _is_valid_topic_id(tid):
            continue
        if tid in existing:
            continue
        conf = float(it.get("confidence", 0.0) or 0.0)
        if conf < 0.55:
            continue
        out.append({
            "topic_id": tid,
            "label": (it.get("label") or "").strip()[:60],
            "why": (it.get("why") or "").strip()[:180],
            "examples": [str(x).strip()[:80] for x in (it.get("examples") or [])][:3],
            "confidence": conf,
        })

    # Deduplicate by topic_id
    seen = set()
    final = []
    for it in out:
        if it["topic_id"] in seen:
            continue
        seen.add(it["topic_id"])
        final.append(it)

    # Reply
    if not final:
        await ctx.send(f"🧴🗂️ Topic suggestions: none (mode={mode_label} in <#{target_channel_id}>)")
        return

    # Human summary + JSON payload for copy/paste
    summary_lines = [f"🧴🗂️ Topic suggestions (mode={mode_label} in <#{target_channel_id}>):"]
    for it in final[:10]:
        ex = "; ".join(it["examples"][:2])
        summary_lines.append(f"- `{it['topic_id']}` ({it['confidence']:.2f}): {it['why']}  e.g. {ex}")

    json_blob = json.dumps(final[:10], indent=2)

    msg = "\n".join(summary_lines)
    await send_chunked(ctx.channel, msg[:1900])
    await send_chunked(ctx.channel, f"```json\n{json_blob}\n```")

@bot.command(name="lfg")
@commands.guild_only()
async def lfg_command(ctx: commands.Context, target: str, *, message: str | None = None):
    """
    Usage:
      !lfg public  [message]  -> ping Driving Ping in #lfg (public)
      !lfg paddock [message]  -> ping Driving Ping in #paddock-lounge
    """

    # 1) Restrict where this command can be used
    if ctx.channel.id != LFG_SOURCE_CHANNEL_ID:
        await ctx.reply(
            "Use this command in the #looking-for-group-pings channel.",
            mention_author=False,
        )
        return

    # 2) Ensure caller is a member (Discovery or Mastery)
    if not isinstance(ctx.author, discord.Member) or not user_has_any_role(ctx.author, MEMBER_ROLE_NAMES):
        await ctx.reply(
            "Only Lumeris members can start LFG pings.",
            mention_author=False,
        )
        return

    # 3) Normalize and validate target
    target = target.lower()
    if target not in ("public", "paddock"):
        await ctx.reply(
            "Usage: `!lfg public <message>` or `!lfg paddock <message>`",
            mention_author=False,
        )
        return

    # 4) Resolve destination channel
    dest_channel_id = LFG_PUBLIC_CHANNEL_ID if target == "public" else PADDOCK_LOUNGE_CHANNEL_ID
    dest_channel = ctx.guild.get_channel(dest_channel_id)
    if dest_channel is None:
        await ctx.reply(
            "I couldn't find the destination channel. Check my channel IDs in the config.",
            mention_author=False,
        )
        return

    # 5) Resolve the opt-in ping role
    ping_role = discord.utils.get(ctx.guild.roles, name=LFG_ROLE_NAME)
    if ping_role is None:
        await ctx.reply(
            f"I couldn't find a role named `{LFG_ROLE_NAME}`. "
            "Create it or update my config.",
            mention_author=False,
        )
        return

    # 6) Build and send the ping
    base = f"{ping_role.mention} — {ctx.author.mention} is looking for a group."
    if message:
        base += f" {message}"

    await dest_channel.send(base)

    # 7) Confirm back in the source channel without extra pings
    await ctx.reply(
        f"LFG ping sent to {dest_channel.mention}.",
        mention_author=False,
    )


# Backfill config
BACKFILL_LIMIT = int(os.getenv("EPOXY_BACKFILL_LIMIT", "2000"))  # per channel, first boot
BACKFILL_PAUSE_EVERY = 200
BACKFILL_PAUSE_SECONDS = 0.25
RECENT_CONTEXT_LIMIT = int(os.getenv("EPOXY_RECENT_CONTEXT_LIMIT", "40"))
RECENT_CONTEXT_MAX_CHARS = int(os.getenv("EPOXY_RECENT_CONTEXT_CHARS", "6000"))
MAX_LINE_CHARS = int(os.getenv("EPOXY_RECENT_CONTEXT_LINE_CHARS", "600"))

async def backfill_channel(channel: discord.abc.Messageable) -> None:
    if not hasattr(channel, "id"):
        return

    channel_id = channel.id
    if channel_id not in ALLOWED_CHANNEL_IDS:
        return

    if BOOTSTRAP_CHANNEL_RESET:
        await reset_backfill_done(channel_id)

    if await is_backfill_done(channel_id):
        return

    print(f"[Backfill] Starting channel {channel_id} ({getattr(channel, 'name', 'unknown')}) "
          f"limit={BACKFILL_LIMIT} bootstrap_capture={BOOTSTRAP_BACKFILL_CAPTURE}")

    count = 0
    captured = 0
    try:
        async for msg in channel.history(limit=BACKFILL_LIMIT, oldest_first=True):
            # Skip other bots but keep Epoxy for context coherence
            if msg.author.bot and bot.user and msg.author.id != bot.user.id:
                continue

            await log_message(msg)

            if BOOTSTRAP_BACKFILL_CAPTURE and stage_at_least("M1"):
                try:
                    # auto-capture only captures decision/policy/canon/#mem patterns by default
                    await maybe_auto_capture(msg)
                    # maybe_auto_capture doesn't return a boolean; if you want counts,
                    # you can add a return value later. For now just track messages processed.
                    captured += 1
                except Exception as e:
                    print(f"[AutoCapture] Error: {e}")

            count += 1
            if count % BACKFILL_PAUSE_EVERY == 0:
                await asyncio.sleep(BACKFILL_PAUSE_SECONDS)
    except Exception as e:
        print(f"[Backfill] Error in channel {channel_id}: {e}")
        return

    await mark_backfill_done(channel_id)
    print(f"[Backfill] Done channel {channel_id}. Logged {count} messages. BootstrapProcessed={captured}")

async def maybe_auto_capture(message: discord.Message) -> None:
    """Optional heuristics to store high-signal items without manual commands."""
    if not (AUTO_CAPTURE and stage_at_least("M1")):
        return
    content = (message.content or "").strip()
    if not content:
        return

    m = re.match(r"^(decision|policy|canon|profile)\s*(\(([^)]+)\))?\s*:\s*(.+)$", content, flags=re.I)
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



@bot.event
async def on_ready():
    print(f"Epoxy is online as {bot.user}")
    if BOOTSTRAP_CHANNEL_RESET_ALL:
        await reset_all_backfill_done()
        print ("[Backfill] Reset ALL backfill_done flags (bootstrap)")
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
    # Ignore channels we don’t care about
    if message.channel.id not in ALLOWED_CHANNEL_IDS:
        return

    # Log Epoxy’s own bot messages (so recent-context includes her questions/answers)
    if message.author.bot:
        if bot.user and message.author.id == bot.user.id:
            await log_message(message)
        return

    # Always log human messages in allowed channels
    await log_message(message)

    # Optional auto-capture of high-signal items into persistent memory
    await maybe_auto_capture(message)

    # Let command processing happen (so !mine/!topicsuggest etc work even without @mention)
    if (message.content or "").lstrip().startswith("!"):
        await bot.process_commands(message)
        return

    # Only respond if mentioned
    if bot.user and bot.user in message.mentions:
        # Strip both <@id> and <@!id>
        prompt = re.sub(rf"<@!?\s*{bot.user.id}\s*>", "", message.content or "").strip()

        if not prompt:
            await message.channel.send("Yep? 🧴")
            await bot.process_commands(message)
            return

        try:
            MAX_MSG_CONTENT = 1900

            # --- Recent context ---
            recent_context, ctx_rows = await get_recent_channel_context(message.channel.id, message.id)

            # Keep the most-recent tail of context if it exceeds budget
            if len(recent_context) > MAX_MSG_CONTENT:
                recent_context = recent_context[-MAX_MSG_CONTENT:]

            # --- Reply anchors (interleaving-safe continuity) ---
            # These let the model bind short replies ("yes", "fun vibe") to the correct last Epoxy question
            anchor_block = ""
            async with db_lock:
                # last Epoxy line before this message
                bot_rows = await asyncio.to_thread(
                    _fetch_last_messages_by_author_sync,
                    db_conn,
                    message.channel.id,
                    message.id,
                    "%Epoxy%",  # adjust if your bot author_name format differs
                    1,
                )
                # last line from same user before this message
                # Use author_id if you have it; name matching is a best-effort fallback.
                user_rows = await asyncio.to_thread(
                    _fetch_last_messages_by_author_sync,
                    db_conn,
                    message.channel.id,
                    message.id,
                    f"%{message.author.name}%",
                    1,
                )

            def _fmt_anchor(rows, label: str) -> str:
                if not rows:
                    return ""
                ts, who, txt = rows[0]
                clean = " ".join((txt or "").split())
                if len(clean) > 420:
                    clean = clean[:419] + "…"
                return f"{label}: [{ts}] {who}: {clean}"

            parts = []
            b = _fmt_anchor(bot_rows, "LAST EPOXY MESSAGE")
            u = _fmt_anchor(user_rows, "LAST MESSAGE FROM THIS USER")
            if b:
                parts.append(b)
            if u:
                parts.append(u)
            if parts:
                anchor_block = (
                    "Reply anchors (use these to interpret short replies like 'yes', 'fun vibe', 'agree'):\n"
                    + "\n".join(parts)
                )
                if len(anchor_block) > MAX_MSG_CONTENT:
                    anchor_block = anchor_block[-MAX_MSG_CONTENT:]

            # --- Packs / prompt ---
            context_pack = build_context_pack()[:MAX_MSG_CONTENT]
            safe_prompt = prompt[:MAX_MSG_CONTENT]

            memory_pack = ""
            if stage_at_least("M1"):
                scope = infer_scope(safe_prompt) if stage_at_least("M2") else "auto"
                events, summaries = await recall_memory(safe_prompt, scope=scope)
                memory_pack = format_memory_for_llm(events, summaries, max_chars=MAX_MSG_CONTENT)
                if len(memory_pack) > MAX_MSG_CONTENT:
                    memory_pack = memory_pack[:MAX_MSG_CONTENT]  # keep head: most relevant first

            print(
                f"[CTX] channel={message.channel.id} rows={ctx_rows} before={message.id} "
                f"ctx_chars={len(recent_context)} pack_chars={len(context_pack)} prompt_chars={len(safe_prompt)} "
                f"mem_chars={len(memory_pack)} stage={MEMORY_STAGE} limit={RECENT_CONTEXT_LIMIT}"
            )

            INSTRUCTIONS = (
                "Use ONLY the context provided in this request: "
                "(1) Recent channel context, "
                "(2) Relevant persistent memory (if provided), and "
                "(3) Topic summaries (if provided). "
                "Do not rely on general knowledge.\n"
                "CRITICAL ATTRIBUTION RULE: Do NOT invent metadata (channel name, user, date, message id, source). "
                "If a detail is not explicitly present, label it as unknown.\n"
                "CORESPONSE/CONTINUITY RULE: If the user reply is short (<= 6 words), interpret it as an answer to "
                "Epoxy's most recent direct question/offer in the recent context unless the user clearly starts a new task.\n"
                "COREFERENCE RULE: If the user uses a pronoun (he/she/they/it/that) and the recent channel context "
                "clearly names a single likely referent in the last 1–3 turns, assume that referent. "
                "Ask a clarifying question ONLY if there are 2+ plausible referents in the last 3 turns.\n"
                "If the provided context is insufficient to answer, say so and ask 1 clarifying question."
            )[:MAX_MSG_CONTENT]

            chat_messages = [
                {"role": "system", "content": SYSTEM_PROMPT_BASE[:MAX_MSG_CONTENT]},
                {"role": "system", "content": context_pack},
                {"role": "system", "content": INSTRUCTIONS},
            ]

            # Insert anchors BEFORE the recent context so the model treats them as routing hints
            if anchor_block:
                chat_messages.append({"role": "system", "content": anchor_block[:MAX_MSG_CONTENT]})

            chat_messages.append(
                {"role": "system", "content": f"Recent channel context:\n{recent_context}"[:MAX_MSG_CONTENT]}
            )

            if stage_at_least("M1") and memory_pack:
                chat_messages.append(
                    {"role": "system", "content": f"Relevant persistent memory:\n{memory_pack}"[:MAX_MSG_CONTENT]}
                )

            chat_messages.append({"role": "user", "content": safe_prompt})

            resp = client.chat.completions.create(model=OPENAI_MODEL, messages=chat_messages)
            reply = resp.choices[0].message.content or "(no output)"
            await send_chunked(message.channel, reply)

        except Exception as e:
            print(f"[OpenAI] Error: {e}")
            await message.channel.send("Epoxy hiccuped. Check logs 🧴⚙️")

    await bot.process_commands(message)



bot.run(DISCORD_TOKEN)
