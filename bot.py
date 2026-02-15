import os
import sqlite3
import asyncio
import json
import re
import time
import hashlib
from datetime import datetime, timezone
import discord
from discord.ext import commands
from openai import OpenAI
from config.defaults import ACCESS_ROLE_KEYWORD
from config.defaults import DEFAULT_ALLOWED_CHANNEL_IDS
from config.defaults import DEFAULT_BACKFILL_LIMIT
from config.defaults import DEFAULT_BACKFILL_PAUSE_EVERY
from config.defaults import DEFAULT_BACKFILL_PAUSE_SECONDS
from config.defaults import DEFAULT_MEMORY_REVIEW_MODE
from config.defaults import DEFAULT_RECENT_CONTEXT_LIMIT
from config.defaults import DEFAULT_RECENT_CONTEXT_LINE_CHARS
from config.defaults import DEFAULT_RECENT_CONTEXT_MAX_CHARS
from config.defaults import DEFAULT_TOPIC_ALLOWLIST
from config.defaults import DRIVING_ROLE_KEYWORD
from config.defaults import DEFAULT_ANNOUNCE_PREP_CHANNEL_ID
from config.defaults import FULL_ACCESS_URL
from config.defaults import LFG_PUBLIC_CHANNEL_ID
from config.defaults import LFG_ROLE_NAME
from config.defaults import LFG_SOURCE_CHANNEL_ID
from config.defaults import MEMBER_ROLE_KEYWORDS
from config.defaults import PADDOCK_LOUNGE_CHANNEL_ID
from config.defaults import RESERVED_KIND_TAGS
from config.defaults import STAGE_RANK
from config.defaults import WELCOME_CHANNEL_ID
from controller.dm_guidelines import load_dm_guidelines
from controller.identity_store import canonical_person_id_sync
from controller.identity_store import dedupe_memory_events_by_id
from controller.identity_store import get_or_create_person_sync
from controller.identity_store import resolve_person_id_sync
from controller.context import (
    classify_context,
    parse_id_set,
    parse_str_set,
    resolve_allowed_channel_ids,
    resolve_channel_groups,
)
from controller.store import (
    fetch_episode_logs_sync,
    get_or_create_context_profile_sync,
    insert_episode_log_sync,
    select_active_controller_config_sync,
    update_latest_dm_draft_evaluation_sync,
    update_latest_dm_draft_feedback_sync,
    upsert_user_profile_last_seen_sync,
)
from db.migrate import apply_sqlite_migrations
from ingestion.service import log_message as log_message_service
from ingestion.store import fetch_last_messages_by_author_sync as fetch_last_messages_by_author_store
from ingestion.store import fetch_latest_messages_sync as fetch_latest_messages_store
from ingestion.store import fetch_messages_since_sync as fetch_messages_since_store
from ingestion.store import fetch_recent_context_sync as fetch_recent_context_store
from ingestion.store import get_backfill_done_sync as get_backfill_done_store
from ingestion.store import insert_message_sync as insert_message_store
from ingestion.store import reset_all_backfill_done_sync as reset_all_backfill_done_store
from ingestion.store import reset_backfill_done_sync as reset_backfill_done_store
from ingestion.store import set_backfill_done_sync as set_backfill_done_store
from jobs.service import maintenance_loop as maintenance_loop_service
from jobs.service import summarize_topic as summarize_topic_service
from jobs.announcements import announcement_loop as announcement_loop_service
from memory.meta_service import apply_policy_enforcement as apply_policy_enforcement_service
from memory.meta_service import format_policy_directive as format_policy_directive_service
from memory.meta_store import resolve_policy_bundle_sync as resolve_policy_bundle_store
from memory.service import extract_json_array as extract_json_array_service
from memory.service import get_topic_candidates as get_topic_candidates_service
from memory.service import remember_event as remember_event_service
from memory.service import safe_extract_json_obj as safe_extract_json_obj_service
from memory.service import suggest_topic_id as suggest_topic_id_service
from memory.store import cleanup_memory_sync as cleanup_memory_store
from memory.store import fetch_latest_memory_events_sync as fetch_latest_memory_events_store
from memory.store import fetch_memory_events_since_sync as fetch_memory_events_since_store
from memory.store import fetch_topic_events_sync as fetch_topic_events_store
from memory.store import get_topic_summary_sync as get_topic_summary_store
from memory.store import insert_memory_event_sync as insert_memory_event_store
from memory.store import list_known_topics_sync as list_known_topics_store
from memory.store import mark_events_summarized_sync as mark_events_summarized_store
from memory.store import search_memory_events_by_tag_sync as search_memory_events_by_tag_store
from memory.store import search_memory_events_sync as search_memory_events_store
from memory.store import search_memory_summaries_sync as search_memory_summaries_store
from memory.store import set_memory_origin_sync as set_memory_origin_store
from memory.store import topic_counts_sync as topic_counts_store
from memory.store import upsert_summary_sync as upsert_summary_store
from misc.runtime_wiring import wire_bot_runtime
from misc.adhoc_modules.announcements_service import AnnouncementService
from misc.adhoc_modules.announcements_service import default_templates_path as announcement_templates_path_default
from misc.adhoc_modules.welcome_panel import build_welcome_panel
from retrieval.service import budget_and_diversify_events as retrieval_budget_and_diversify_events
from retrieval.fts_query import build_fts_query
from retrieval.service import format_memory_events_window as format_memory_events_window_service
from retrieval.service import format_memory_for_llm as format_memory_for_llm_service
from retrieval.service import format_profile_for_llm as format_profile_for_llm_service
from retrieval.service import format_recent_context as format_recent_context_service
from retrieval.service import get_recent_channel_context as get_recent_channel_context_service
from retrieval.service import parse_duration_to_minutes as parse_duration_to_minutes_service
from retrieval.service import recall_memory as recall_memory_service

# See AGENTS.md for complete roadmap and context

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

# Control via env:
#   EPOXY_MEMORY_STAGE = M0 | M1 | M2 | M3   (default: M0)
#   EPOXY_MEMORY_ENABLE_AUTO_CAPTURE = 0/1   (default: 0)
#   EPOXY_MEMORY_ENABLE_AUTO_SUMMARY = 0/1   (default: 0)
#   EPOXY_MEMORY_REVIEW_MODE = off|capture_only|all (default: capture_only)
#
# Notes:
# - “Wire to M3” means: the DB schema + codepaths exist up through M3,
#   but you can keep runtime behavior at M0/M1/M2 with the stage flags.
#
# ---- Memory / staging config (drop-in) ----


# Stage gating (default conservative; set env to enable higher stages)
MEMORY_STAGE = os.getenv("EPOXY_MEMORY_STAGE", "M0").strip().upper()
MEMORY_STAGE_RANK = STAGE_RANK.get(MEMORY_STAGE, 0)

def stage_at_least(stage: str) -> bool:
    return MEMORY_STAGE_RANK >= STAGE_RANK.get(stage.strip().upper(), 0)

# Feature toggles (default OFF; flip via env when testing)
AUTO_CAPTURE = os.getenv("EPOXY_MEMORY_ENABLE_AUTO_CAPTURE", "0").strip() == "1"
AUTO_SUMMARY = os.getenv("EPOXY_MEMORY_ENABLE_AUTO_SUMMARY", "0").strip() == "1"
MEMORY_REVIEW_MODE = os.getenv("EPOXY_MEMORY_REVIEW_MODE", DEFAULT_MEMORY_REVIEW_MODE).strip().lower()
if MEMORY_REVIEW_MODE not in {"off", "capture_only", "all"}:
    print(
        f"[CFG] invalid EPOXY_MEMORY_REVIEW_MODE={MEMORY_REVIEW_MODE!r}; "
        f"falling back to {DEFAULT_MEMORY_REVIEW_MODE!r}"
    )
    MEMORY_REVIEW_MODE = DEFAULT_MEMORY_REVIEW_MODE
BOOTSTRAP_BACKFILL_CAPTURE = os.getenv("EPOXY_BOOTSTRAP_BACKFILL_CAPTURE", "0").strip() == "1"
BOOTSTRAP_CHANNEL_RESET = os.getenv("EPOXY_BOOTSTRAP_CHANNEL_RESET", "0").strip() == "1"


# Topic suggestion (late-M3 ergonomics)
TOPIC_SUGGEST = os.getenv("EPOXY_TOPIC_SUGGEST", "0").strip() == "1"
try:
    TOPIC_MIN_CONF = float(os.getenv("EPOXY_TOPIC_MIN_CONF", "0.85").strip())
except ValueError:
    TOPIC_MIN_CONF = 0.85

# Allowlist behavior:
# - If env var is unset: use default allowlist above.
# - If env var is set to empty/whitespace: treat as "no explicit allowlist" (fallback to known DB topics).
# - Otherwise: parse env var.
_raw = os.getenv("EPOXY_TOPIC_ALLOWLIST")
if _raw is None:
    _TOPIC_ALLOWLIST_RAW = DEFAULT_TOPIC_ALLOWLIST
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
    f"review_mode={MEMORY_REVIEW_MODE} "
    f"topic_suggest={TOPIC_SUGGEST} topic_min_conf={TOPIC_MIN_CONF} "
    f"allowlist={'(db-topics)' if not TOPIC_ALLOWLIST else str(len(TOPIC_ALLOWLIST))+' topics'}"
)
# ---- end config ----


# Railway persistent path (set this to your mounted volume path)
DB_PATH = os.getenv("EPOXY_DB_PATH", "epoxy_memory.db")

client = OpenAI(api_key=OPENAI_API_KEY)

# =========================
# ALLOWED CHANNELS + CONTEXT POLICY
# =========================
ALLOWED_CHANNEL_IDS = resolve_allowed_channel_ids(DEFAULT_ALLOWED_CHANNEL_IDS)
CHANNEL_POLICY_GROUPS = resolve_channel_groups()

OWNER_USER_IDS = parse_id_set(os.getenv("EPOXY_OWNER_USER_IDS", "237008609773486080"))
OWNER_USERNAMES = parse_str_set(os.getenv("EPOXY_OWNER_USERNAMES", "blockwood43"))
FOUNDER_USER_IDS = parse_id_set(os.getenv("EPOXY_FOUNDER_USER_IDS"))
if not FOUNDER_USER_IDS and OWNER_USER_IDS:
    FOUNDER_USER_IDS = set(OWNER_USER_IDS)

ENABLE_EPISODE_LOGGING = os.getenv("EPOXY_ENABLE_EPISODE_LOGGING", "1").strip() == "1"
# New preferred variable:
#   EPOXY_EPISODE_LOG_FILTERS
# Supports caller/context/surface filtering, e.g.:
#   context:dm,context:public,context:member,context:staff,context:leadership
# Backward compatibility:
#   EPOXY_EPISODE_LOG_SURFACES (legacy)
_episode_filters_raw = os.getenv("EPOXY_EPISODE_LOG_FILTERS")
if _episode_filters_raw is None:
    _episode_filters_raw = os.getenv("EPOXY_EPISODE_LOG_SURFACES")
if _episode_filters_raw is None:
    _episode_filters_raw = "context:dm,context:public,context:member,context:staff,context:leadership"
EPISODE_LOG_FILTERS = parse_str_set(_episode_filters_raw)
print(
    f"[CFG] allowed_channels={len(ALLOWED_CHANNEL_IDS)} "
    f"groups(leadership={len(CHANNEL_POLICY_GROUPS['leadership'])}, "
    f"staff={len(CHANNEL_POLICY_GROUPS['staff'])}, "
    f"member={len(CHANNEL_POLICY_GROUPS['member'])}, "
    f"public={len(CHANNEL_POLICY_GROUPS['public'])}) "
    f"owner_ids={len(OWNER_USER_IDS)} founder_ids={len(FOUNDER_USER_IDS)} "
    f"episode_logging={ENABLE_EPISODE_LOGGING} filters={len(EPISODE_LOG_FILTERS)}"
)

# =========================
# ANNOUNCEMENT AUTOMATION
# =========================
ANNOUNCE_ENABLED = os.getenv("EPOXY_ANNOUNCE_ENABLED", "0").strip() == "1"
ANNOUNCE_TIMEZONE = os.getenv("EPOXY_ANNOUNCE_TIMEZONE", "UTC").strip() or "UTC"
ANNOUNCE_PREP_TIME_LOCAL = os.getenv("EPOXY_ANNOUNCE_PREP_TIME_LOCAL", "09:00").strip() or "09:00"
ANNOUNCE_PREP_CHANNEL_ID = int(
    os.getenv("EPOXY_ANNOUNCE_PREP_CHANNEL_ID", str(DEFAULT_ANNOUNCE_PREP_CHANNEL_ID)).strip()
    or str(DEFAULT_ANNOUNCE_PREP_CHANNEL_ID)
)
ANNOUNCE_PREP_ROLE_NAME = os.getenv("EPOXY_ANNOUNCE_PREP_ROLE_NAME", "").strip()
ANNOUNCE_TICK_SECONDS = int(os.getenv("EPOXY_ANNOUNCE_TICK_SECONDS", "30").strip() or "30")
ANNOUNCE_DRY_RUN = os.getenv("EPOXY_ANNOUNCE_DRY_RUN", "0").strip() == "1"
# Deployment note: manage this via EPOXY_ANNOUNCE_TEMPLATES_PATH explicitly.
ANNOUNCE_TEMPLATES_PATH = os.getenv("EPOXY_ANNOUNCE_TEMPLATES_PATH", announcement_templates_path_default())
_RAW_DM_GUIDELINES_PATH = os.getenv("EPOXY_DM_GUIDELINES_PATH")
DM_GUIDELINES_PATH = os.getenv(
    "EPOXY_DM_GUIDELINES_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "dm_guidelines.yml"),
)
DM_GUIDELINES, DM_GUIDELINES_WARNING = load_dm_guidelines(DM_GUIDELINES_PATH)
DM_GUIDELINES_SOURCE = "env_override" if _RAW_DM_GUIDELINES_PATH is not None else "file"
if DM_GUIDELINES_WARNING:
    DM_GUIDELINES_SOURCE = "fallback"

print(
    f"[CFG] announce_enabled={ANNOUNCE_ENABLED} dry_run={ANNOUNCE_DRY_RUN} "
    f"tz={ANNOUNCE_TIMEZONE} prep_time={ANNOUNCE_PREP_TIME_LOCAL} "
    f"prep_channel={ANNOUNCE_PREP_CHANNEL_ID} tick_s={ANNOUNCE_TICK_SECONDS}"
)
if DM_GUIDELINES_WARNING:
    print(
        f"[CFG] dm_guidelines={DM_GUIDELINES.version} "
        f"source={DM_GUIDELINES_SOURCE} path={DM_GUIDELINES_PATH}"
    )
    print(f"[CFG] {DM_GUIDELINES_WARNING}")
else:
    print(
        f"[CFG] dm_guidelines={DM_GUIDELINES.version} "
        f"source={DM_GUIDELINES_SOURCE} path={DM_GUIDELINES_PATH}"
    )

# =========================
# "Seed memories" (Epoxy context pack)
# Edit these freely.
# =========================
SEED_MEMORIES = [
    "Lumeris is a high-trust sim racing and human-development community that values care, precision, and clear models rather than vague vibes.",
    "Brian Lockwood (@blockwood43) leads Lumeris. He has final say on direction and uses systems thinking heavily; clarity beats cleverness.",
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


def _list_schema_migrations_sync(conn: sqlite3.Connection, limit: int = 200) -> list[tuple[str, str, str]]:
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT version, name, applied_at_utc
            FROM schema_migrations
            ORDER BY version DESC
            LIMIT ?
            """,
            (max(1, min(int(limit), 500)),),
        )
        return cur.fetchall()
    except sqlite3.OperationalError:
        return []

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
    repo_root = os.path.dirname(os.path.abspath(__file__))
    migrations_dir = os.path.join(repo_root, "migrations")
    apply_sqlite_migrations(conn, migrations_dir)

    # ---- Schema verification (logs show up in Railway) ----
    try:
        required_messages = ["message_id", "channel_id", "author_id", "created_at_utc", "content"]
        required_controller = [
            ("context_profiles", ["caller_type", "surface", "allowed_capabilities_json"]),
            ("user_profiles", ["person_id", "layer_estimate", "risk_flags_json", "last_seen_at_utc"]),
            ("controller_configs", ["scope", "persona", "depth", "strictness", "intervention_level"]),
            (
                "episode_logs",
                [
                    "timestamp_utc",
                    "context_profile_id",
                    "user_id",
                    "person_id",
                    "controller_config_id",
                    "target_user_id",
                    "target_person_id",
                    "target_display_name",
                    "target_type",
                    "target_confidence",
                    "target_entity_key",
                    "mode_requested",
                    "mode_inferred",
                    "mode_used",
                    "dm_guidelines_version",
                    "dm_guidelines_source",
                    "blocking_collab",
                    "critical_missing_fields_json",
                    "blocking_reason",
                    "draft_version",
                    "draft_variant_id",
                    "prompt_fingerprint",
                ],
            ),
        ]
        required_announcements = [
            (
                "announcement_cycles",
                [
                    "target_date_local",
                    "timezone",
                    "status",
                    "completion_path",
                    "publish_at_utc",
                    "manual_done_link",
                ],
            ),
            (
                "announcement_answers",
                ["cycle_id", "question_id", "answer_text", "answered_by_user_id", "answered_at_utc"],
            ),
            (
                "announcement_audit_log",
                ["cycle_id", "action", "actor_type", "payload_json", "created_at_utc"],
            ),
        ]
        required_events = [
            "updated_at_utc", "last_verified_at_utc", "expiry_at_utc",
            "scope", "type", "title", "confidence", "stability", "lifecycle", "superseded_by",
        ]
        required_summaries = [
            "summary_type", "scope", "covers_event_ids_json",
            "confidence", "stability", "last_verified_at_utc",
            "lifecycle", "tier", "generated_by_model", "prompt_hash", "job_id",
        ]

        ok_m, missing_m = _schema_has_columns(cur, "messages", required_messages)
        ok_e, missing_e = _schema_has_columns(cur, "memory_events", required_events)
        ok_s, missing_s = _schema_has_columns(cur, "memory_summaries", required_summaries)

        print(f"[DB] messages schema OK={ok_m} missing={missing_m}")
        print(f"[DB] memory_events schema OK={ok_e} missing={missing_e}")
        print(f"[DB] memory_summaries schema OK={ok_s} missing={missing_s}")
        for tbl, req in required_controller:
            ok_t, missing_t = _schema_has_columns(cur, tbl, req)
            print(f"[DB] {tbl} schema OK={ok_t} missing={missing_t}")
        for tbl, req in required_announcements:
            ok_t, missing_t = _schema_has_columns(cur, tbl, req)
            print(f"[DB] {tbl} schema OK={ok_t} missing={missing_t}")

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


def subject_person_tag(person_id: int) -> str:
    return f"subject:person:{int(person_id)}"

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

def user_is_member(member: discord.Member) -> bool:
    role_names = [role.name.lower() for role in member.roles]
    for keyword in MEMBER_ROLE_KEYWORDS:
        kw = keyword.lower()
        if any(kw in name for name in role_names):
            return True
    return False


def user_is_owner(user: discord.abc.User) -> bool:
    uid = int(getattr(user, "id", 0) or 0)
    if uid and uid in OWNER_USER_IDS:
        return True
    if OWNER_USER_IDS:
        return False

    names = {
        str(getattr(user, "name", "") or "").strip().lower(),
        str(getattr(user, "global_name", "") or "").strip().lower(),
        str(getattr(user, "display_name", "") or "").strip().lower(),
    }
    # Also include discriminator form ("name#1234") for old-style accounts.
    tag = str(user).strip().lower()
    if tag:
        names.add(tag)
        names.add(tag.split("#", 1)[0])
    return any(n in OWNER_USERNAMES for n in names if n)

def _insert_message_sync(conn: sqlite3.Connection, payload: dict) -> None:
    insert_message_store(conn, payload)

def _insert_memory_event_sync(conn: sqlite3.Connection, payload: dict) -> int:
    return insert_memory_event_store(
        conn,
        payload,
        safe_json_loads=safe_json_loads,
    )

def _mark_events_summarized_sync(conn: sqlite3.Connection, event_ids: list[int]) -> None:
    mark_events_summarized_store(conn, event_ids)

async def recall_profile_for_identity(
    person_id: int | None,
    user_id: int | None,
    limit: int = 6,
) -> list[dict]:
    if not stage_at_least("M1"):
        return []
    lim = max(1, int(limit))
    search_lim = max(lim * 2, lim)

    async with db_lock:
        canonical_person_id: int | None = int(person_id) if person_id is not None else None
        if canonical_person_id is not None:
            canonical_person_id = await asyncio.to_thread(canonical_person_id_sync, db_conn, int(canonical_person_id))

        if canonical_person_id is None and user_id is not None:
            canonical_person_id = await asyncio.to_thread(
                resolve_person_id_sync,
                db_conn,
                "discord",
                str(int(user_id)),
            )

        merged: list[dict] = []
        if canonical_person_id is not None:
            merged.extend(
                await asyncio.to_thread(
                    _search_memory_events_by_tag_sync,
                    db_conn,
                    subject_person_tag(int(canonical_person_id)),
                    "profile",
                    search_lim,
                )
            )
        if user_id is not None:
            merged.extend(
                await asyncio.to_thread(
                    _search_memory_events_by_tag_sync,
                    db_conn,
                    subject_user_tag(int(user_id)),
                    "profile",
                    search_lim,
                )
            )

        return dedupe_memory_events_by_id(merged, limit=lim)


async def recall_profile_for_user(user_id: int, limit: int = 6) -> list[dict]:
    return await recall_profile_for_identity(None, int(user_id), limit=limit)

def _search_memory_events_by_tag_sync(conn, subject_tag: str, kind_tag: str, limit: int) -> list[dict]:
    return search_memory_events_by_tag_store(
        conn,
        subject_tag,
        kind_tag,
        limit,
        safe_json_loads=safe_json_loads,
    )

def _upsert_summary_sync(conn: sqlite3.Connection, payload: dict) -> int:
    return upsert_summary_store(
        conn,
        payload,
        safe_json_loads=safe_json_loads,
    )

def _search_memory_events_sync(conn: sqlite3.Connection, query: str, scope: str, limit: int = 8) -> list[dict]:
    return search_memory_events_store(
        conn,
        query,
        scope,
        limit=limit,
        build_fts_query=build_fts_query,
        parse_recall_scope=parse_recall_scope,
        stage_at_least=stage_at_least,
        safe_json_loads=safe_json_loads,
    )

def _search_memory_summaries_sync(conn: sqlite3.Connection, query: str, scope: str, limit: int = 3) -> list[dict]:
    return search_memory_summaries_store(
        conn,
        query,
        scope,
        limit=limit,
        build_fts_query=build_fts_query,
        parse_recall_scope=parse_recall_scope,
        safe_json_loads=safe_json_loads,
    )

def _resolve_policy_bundle_sync(
    conn: sqlite3.Connection,
    *,
    sensitivity_policy_id: str,
    caller_type: str,
    surface: str,
    limit: int = 20,
) -> dict:
    return resolve_policy_bundle_store(
        conn,
        sensitivity_policy_id=sensitivity_policy_id,
        caller_type=caller_type,
        surface=surface,
        limit=limit,
    )

def _format_policy_directive(policy_bundle: dict, max_chars: int = 550) -> str:
    return format_policy_directive_service(policy_bundle, max_chars=max_chars)

def _apply_policy_enforcement(
    reply: str,
    *,
    policy_bundle: dict,
    author_id: int | None,
    caller_type: str,
    surface: str,
) -> tuple[str, list[str]]:
    return apply_policy_enforcement_service(
        reply,
        policy_bundle=policy_bundle,
        author_id=author_id,
        caller_type=caller_type,
        surface=surface,
    )

def _cleanup_memory_sync(conn: sqlite3.Connection) -> tuple[int, int]:
    return cleanup_memory_store(conn, stage_at_least=stage_at_least)
def _fetch_topic_events_sync(
    conn: sqlite3.Connection,
    topic_id: str,
    scope: str = "auto",
    min_age_days: int = 14,
    max_events: int = 200,
) -> list[dict]:
    return fetch_topic_events_store(
        conn,
        topic_id,
        scope=scope,
        min_age_days=min_age_days,
        max_events=max_events,
        parse_recall_scope=parse_recall_scope,
        safe_json_loads=safe_json_loads,
    )

def _get_topic_summary_sync(
    conn: sqlite3.Connection,
    topic_id: str,
    scope: str = "auto",
    summary_type: str = "topic_gist",
) -> dict | None:
    return get_topic_summary_store(
        conn,
        topic_id,
        scope=scope,
        summary_type=summary_type,
        parse_recall_scope=parse_recall_scope,
        safe_json_loads=safe_json_loads,
    )

def _fetch_latest_memory_events_sync(
    conn: sqlite3.Connection,
    limit: int,
) -> list[tuple[str, str, str, str]]:
    return fetch_latest_memory_events_store(conn, limit)


def _fetch_memory_events_since_sync(
    conn: sqlite3.Connection,
    since_iso_utc: str,
    limit: int,
) -> list[tuple[str, str, str, str]]:
    return fetch_memory_events_since_store(conn, since_iso_utc, limit)

def _format_memory_events_window(rows: list[tuple[str, str, str, str]], max_chars: int = 12000) -> str:
    return format_memory_events_window_service(rows, max_chars=max_chars)

def _fetch_last_messages_by_author_sync(conn, channel_id, before_message_id, author_name_like, limit=1):
    return fetch_last_messages_by_author_store(
        conn,
        channel_id,
        before_message_id,
        author_name_like,
        limit=limit,
    )


def _get_backfill_done_sync(conn: sqlite3.Connection, channel_id: int) -> tuple[bool, str | None]:
    return get_backfill_done_store(conn, channel_id)


def _set_backfill_done_sync(conn: sqlite3.Connection, channel_id: int, iso_utc: str) -> None:
    set_backfill_done_store(conn, channel_id, iso_utc)

BOOTSTRAP_CHANNEL_RESET_ALL = os.getenv("EPOXY_BOOTSTRAP_CHANNEL_RESET_ALL", "0").strip() == "1"

def _reset_all_backfill_done_sync(conn: sqlite3.Connection) -> None:
    reset_all_backfill_done_store(conn)

async def reset_all_backfill_done() -> None:
    async with db_lock:
        await asyncio.to_thread(_reset_all_backfill_done_sync, db_conn)

def _reset_backfill_done_sync(conn: sqlite3.Connection, channel_id: int) -> None:
    reset_backfill_done_store(conn, channel_id)

async def reset_backfill_done(channel_id: int) -> None:
    async with db_lock:
        await asyncio.to_thread(_reset_backfill_done_sync, db_conn, int(channel_id))


def _fetch_recent_context_sync(
    conn: sqlite3.Connection,
    channel_id: int,
    before_message_id: int,
    limit: int
) -> list[tuple[str, str, str]]:
    return fetch_recent_context_store(conn, channel_id, before_message_id, limit)

def _fetch_messages_since_sync(
    conn: sqlite3.Connection,
    channel_id: int,
    since_iso_utc: str,
    limit: int,
) -> list[tuple[str, str, str]]:
    return fetch_messages_since_store(conn, channel_id, since_iso_utc, limit)

def _parse_duration_to_minutes(token: str) -> int | None:
    return parse_duration_to_minutes_service(token)

def _format_recent_context(rows: list[tuple[str, str, str]], max_chars: int, max_line_chars: int) -> str:
    return format_recent_context_service(rows, max_chars, max_line_chars)

async def get_recent_channel_context(channel_id: int, before_message_id: int) -> tuple[str, int]:
    return await get_recent_channel_context_service(
        channel_id,
        before_message_id,
        db_lock=db_lock,
        db_conn=db_conn,
        fetch_recent_context_sync=_fetch_recent_context_sync,
        recent_context_limit=RECENT_CONTEXT_LIMIT,
        recent_context_max_chars=RECENT_CONTEXT_MAX_CHARS,
        max_line_chars=MAX_LINE_CHARS,
    )


def _fetch_latest_messages_sync(
    conn: sqlite3.Connection,
    channel_id: int,
    limit: int,
) -> list[tuple[str, str, str]]:
    return fetch_latest_messages_store(conn, channel_id, limit)


def _set_memory_origin_sync(
    conn: sqlite3.Connection,
    mem_id: int,
    source_channel_id: int | None,
    source_channel_name: str | None,
) -> None:
    set_memory_origin_store(conn, mem_id, source_channel_id, source_channel_name)


async def set_memory_origin(mem_id: int, source_channel_id: int | None, source_channel_name: str | None) -> None:
    async with db_lock:
        await asyncio.to_thread(_set_memory_origin_sync, db_conn, int(mem_id), source_channel_id, source_channel_name)

# =========================
# TOPIC SUGGESTION (late-M3)
# =========================

def _list_known_topics_sync(conn: sqlite3.Connection, limit: int = 200) -> list[str]:
    return list_known_topics_store(conn, limit)


def _topic_counts_sync(conn: sqlite3.Connection, limit: int = 15) -> list[tuple[str, int]]:
    return topic_counts_store(conn, limit)


async def _get_topic_candidates() -> list[str]:
    return await get_topic_candidates_service(
        topic_allowlist=TOPIC_ALLOWLIST,
        db_lock=db_lock,
        db_conn=db_conn,
        list_known_topics_sync=_list_known_topics_sync,
    )


def _safe_extract_json_obj(text: str) -> dict | None:
    return safe_extract_json_obj_service(text)
    
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
    return extract_json_array_service(text)

def _is_valid_topic_id(t: str) -> bool:
    return bool(re.match(r"^[a-z0-9_]{3,24}$", t or ""))


async def _suggest_topic_id(text: str, candidates: list[str]) -> tuple[str | None, float]:
    return await suggest_topic_id_service(
        text,
        candidates,
        topic_suggest=TOPIC_SUGGEST,
        client=client,
        openai_model=OPENAI_MODEL,
    )


async def remember_event(
    *,
    text: str,
    tags: list[str] | None,
    importance: int,
    message: discord.Message | None = None,
    topic_hint: str | None = None,
    source_path: str = "manual_remember",
    owner_override_active: bool = False,
) -> dict | None:
    return await remember_event_service(
        text=text,
        tags=tags,
        importance=importance,
        message=message,
        topic_hint=topic_hint,
        memory_review_mode=MEMORY_REVIEW_MODE,
        source_path=source_path,
        owner_override_active=owner_override_active,
        stage_at_least=stage_at_least,
        normalize_tags=normalize_tags,
        reserved_kind_tags=RESERVED_KIND_TAGS,
        topic_suggest=TOPIC_SUGGEST,
        topic_min_conf=TOPIC_MIN_CONF,
        topic_allowlist=TOPIC_ALLOWLIST,
        db_lock=db_lock,
        db_conn=db_conn,
        list_known_topics_sync=_list_known_topics_sync,
        client=client,
        openai_model=OPENAI_MODEL,
        utc_iso=utc_iso,
        utc_ts=utc_ts,
        infer_tier=infer_tier,
        safe_json_dumps=safe_json_dumps,
        insert_memory_event_sync=_insert_memory_event_sync,
    )

def _budget_and_diversify_events(events: list[dict], scope: str, limit: int = 8) -> list[dict]:
    return retrieval_budget_and_diversify_events(
        events,
        scope,
        stage_at_least=stage_at_least,
        limit=limit,
    )

async def recall_memory(
    prompt: str,
    scope: str | None = None,
    memory_budget: dict | None = None,
) -> tuple[list[dict], list[dict]]:
    return await recall_memory_service(
        prompt,
        scope,
        memory_budget,
        stage_at_least=stage_at_least,
        db_lock=db_lock,
        db_conn=db_conn,
        search_memory_events_sync=_search_memory_events_sync,
        search_memory_summaries_sync=_search_memory_summaries_sync,
    )

def format_memory_for_llm(events: list[dict], summaries: list[dict], max_chars: int = 1700) -> str:
    return format_memory_for_llm_service(events, summaries, max_chars=max_chars)

def format_profile_for_llm(user_blocks: list[tuple[int, str, list[dict]]], max_chars: int = 900) -> str:
    return format_profile_for_llm_service(user_blocks, max_chars=max_chars)

async def summarize_topic(
    topic_id: str,
    *,
    scope: str = "auto",
    summary_type: str = "topic_gist",
    min_age_days: int = 14,
) -> str:
    return await summarize_topic_service(
        topic_id,
        scope=scope,
        summary_type=summary_type,
        min_age_days=min_age_days,
        stage_at_least=stage_at_least,
        db_lock=db_lock,
        db_conn=db_conn,
        get_topic_summary_sync=_get_topic_summary_sync,
        fetch_topic_events_sync=_fetch_topic_events_sync,
        client=client,
        openai_model=OPENAI_MODEL,
        normalize_tags=normalize_tags,
        utc_iso=utc_iso,
        safe_json_dumps=safe_json_dumps,
        upsert_summary_sync=_upsert_summary_sync,
        mark_events_summarized_sync=_mark_events_summarized_sync,
    )

async def maintenance_loop() -> None:
    interval = int(os.getenv("EPOXY_MAINTENANCE_INTERVAL_SECONDS", "3600"))
    min_age_days = int(os.getenv("EPOXY_SUMMARY_MIN_AGE_DAYS", "14"))
    return await maintenance_loop_service(
        stage_at_least=stage_at_least,
        db_lock=db_lock,
        db_conn=db_conn,
        cleanup_memory_sync=_cleanup_memory_sync,
        auto_summary=AUTO_SUMMARY,
        memory_stage=MEMORY_STAGE,
        summarize_topic_func=summarize_topic,
        interval_seconds=interval,
        min_age_days=min_age_days,
    )

async def log_message(message: discord.Message) -> None:
    return await log_message_service(
        message,
        db_lock=db_lock,
        db_conn=db_conn,
        insert_message_sync=_insert_message_sync,
    )

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
# Backfill config
BACKFILL_LIMIT = int(os.getenv("EPOXY_BACKFILL_LIMIT", str(DEFAULT_BACKFILL_LIMIT)))  # per channel, first boot
BACKFILL_PAUSE_EVERY = DEFAULT_BACKFILL_PAUSE_EVERY
BACKFILL_PAUSE_SECONDS = DEFAULT_BACKFILL_PAUSE_SECONDS
RECENT_CONTEXT_LIMIT = int(os.getenv("EPOXY_RECENT_CONTEXT_LIMIT", str(DEFAULT_RECENT_CONTEXT_LIMIT)))
RECENT_CONTEXT_MAX_CHARS = int(os.getenv("EPOXY_RECENT_CONTEXT_CHARS", str(DEFAULT_RECENT_CONTEXT_MAX_CHARS)))
MAX_LINE_CHARS = int(os.getenv("EPOXY_RECENT_CONTEXT_LINE_CHARS", str(DEFAULT_RECENT_CONTEXT_LINE_CHARS)))

def _build_welcome_panel() -> discord.ui.View:
    return build_welcome_panel(
        full_access_url=FULL_ACCESS_URL,
        access_role_keyword=ACCESS_ROLE_KEYWORD,
        driving_role_keyword=DRIVING_ROLE_KEYWORD,
    )

announcement_service = AnnouncementService(
    db_lock=db_lock,
    db_conn=db_conn,
    client=client,
    openai_model=OPENAI_MODEL,
    stage_at_least=stage_at_least,
    recall_memory_func=recall_memory,
    format_memory_for_llm=format_memory_for_llm,
    utc_iso=utc_iso,
    templates_path=ANNOUNCE_TEMPLATES_PATH,
    enabled=ANNOUNCE_ENABLED,
    timezone_name=ANNOUNCE_TIMEZONE,
    prep_time_local=ANNOUNCE_PREP_TIME_LOCAL,
    prep_channel_id=ANNOUNCE_PREP_CHANNEL_ID,
    prep_role_name=ANNOUNCE_PREP_ROLE_NAME,
    dry_run=ANNOUNCE_DRY_RUN,
)

async def announcement_loop() -> None:
    return await announcement_loop_service(
        bot=bot,
        announcement_service=announcement_service,
        interval_seconds=ANNOUNCE_TICK_SECONDS,
    )

wire_bot_runtime(
    bot,
    allowed_channel_ids=ALLOWED_CHANNEL_IDS,
    user_is_owner=user_is_owner,
    fetch_episode_logs_sync=fetch_episode_logs_sync,
    update_latest_dm_draft_feedback_sync=update_latest_dm_draft_feedback_sync,
    update_latest_dm_draft_evaluation_sync=update_latest_dm_draft_evaluation_sync,
    list_schema_migrations_sync=_list_schema_migrations_sync,
    stage_at_least=stage_at_least,
    memory_stage=MEMORY_STAGE,
    memory_stage_rank=MEMORY_STAGE_RANK,
    memory_review_mode=MEMORY_REVIEW_MODE,
    auto_capture=AUTO_CAPTURE,
    auto_summary=AUTO_SUMMARY,
    topic_suggest=TOPIC_SUGGEST,
    topic_min_conf=TOPIC_MIN_CONF,
    topic_allowlist=TOPIC_ALLOWLIST,
    db_lock=db_lock,
    db_conn=db_conn,
    topic_counts_sync=_topic_counts_sync,
    list_known_topics_sync=_list_known_topics_sync,
    get_topic_summary_sync=_get_topic_summary_sync,
    summarize_topic_func=summarize_topic,
    send_chunked=send_chunked,
    normalize_tags=normalize_tags,
    remember_event_func=remember_event,
    infer_scope=infer_scope,
    recall_memory_func=recall_memory,
    format_memory_for_llm=format_memory_for_llm,
    resolve_policy_bundle_sync=_resolve_policy_bundle_sync,
    format_policy_directive_func=_format_policy_directive,
    apply_policy_enforcement_func=_apply_policy_enforcement,
    subject_user_tag=subject_user_tag,
    subject_person_tag=subject_person_tag,
    get_or_create_person_sync=get_or_create_person_sync,
    parse_channel_id_token=_parse_channel_id_token,
    parse_duration_to_minutes=_parse_duration_to_minutes,
    fetch_messages_since_sync=_fetch_messages_since_sync,
    fetch_latest_messages_sync=_fetch_latest_messages_sync,
    fetch_memory_events_since_sync=_fetch_memory_events_since_sync,
    fetch_latest_memory_events_sync=_fetch_latest_memory_events_sync,
    fetch_recent_context_sync=_fetch_recent_context_sync,
    format_recent_context=_format_recent_context,
    format_memory_events_window=_format_memory_events_window,
    extract_json_array=_extract_json_array,
    is_valid_topic_id=_is_valid_topic_id,
    set_memory_origin_func=set_memory_origin,
    client=client,
    openai_model=OPENAI_MODEL,
    max_line_chars=MAX_LINE_CHARS,
    welcome_channel_id=WELCOME_CHANNEL_ID,
    welcome_panel_factory=_build_welcome_panel,
    lfg_source_channel_id=LFG_SOURCE_CHANNEL_ID,
    lfg_public_channel_id=LFG_PUBLIC_CHANNEL_ID,
    paddock_lounge_channel_id=PADDOCK_LOUNGE_CHANNEL_ID,
    lfg_role_name=LFG_ROLE_NAME,
    user_is_member=user_is_member,
    bootstrap_channel_reset_all=BOOTSTRAP_CHANNEL_RESET_ALL,
    bootstrap_channel_reset=BOOTSTRAP_CHANNEL_RESET,
    bootstrap_backfill_capture=BOOTSTRAP_BACKFILL_CAPTURE,
    reset_all_backfill_done_func=reset_all_backfill_done,
    reset_backfill_done_func=reset_backfill_done,
    is_backfill_done_func=is_backfill_done,
    mark_backfill_done_func=mark_backfill_done,
    backfill_limit=BACKFILL_LIMIT,
    backfill_pause_every=BACKFILL_PAUSE_EVERY,
    backfill_pause_seconds=BACKFILL_PAUSE_SECONDS,
    log_message_func=log_message,
    maintenance_loop_func=maintenance_loop,
    get_recent_channel_context_func=get_recent_channel_context,
    fetch_last_messages_by_author_sync=_fetch_last_messages_by_author_sync,
    build_context_pack=build_context_pack,
    classify_context=classify_context,
    founder_user_ids=FOUNDER_USER_IDS,
    channel_policy_groups=CHANNEL_POLICY_GROUPS,
    recall_profile_for_identity_func=recall_profile_for_identity,
    format_profile_for_llm=format_profile_for_llm,
    dm_guidelines=DM_GUIDELINES,
    dm_guidelines_source=DM_GUIDELINES_SOURCE,
    get_or_create_context_profile_sync=get_or_create_context_profile_sync,
    resolve_person_id_sync=resolve_person_id_sync,
    canonical_person_id_sync=canonical_person_id_sync,
    upsert_user_profile_last_seen_sync=upsert_user_profile_last_seen_sync,
    select_active_controller_config_sync=select_active_controller_config_sync,
    utc_iso=utc_iso,
    system_prompt_base=SYSTEM_PROMPT_BASE,
    enable_episode_logging=ENABLE_EPISODE_LOGGING,
    episode_log_filters=EPISODE_LOG_FILTERS,
    insert_episode_log_sync=insert_episode_log_sync,
    recent_context_limit=RECENT_CONTEXT_LIMIT,
    announcement_enabled=ANNOUNCE_ENABLED,
    announcement_service=announcement_service,
    announcement_loop_func=announcement_loop,
)



bot.run(DISCORD_TOKEN)





