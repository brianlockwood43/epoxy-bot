from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from memory.tagging import extract_kind
from memory.tagging import extract_topics
from memory.tagging import normalize_memory_tags


async def get_topic_candidates(
    *,
    topic_allowlist: list[str],
    db_lock,
    db_conn,
    list_known_topics_sync,
) -> list[str]:
    """Return candidate topic_ids to choose from (allowlist preferred; else known topics)."""
    if topic_allowlist:
        return list(topic_allowlist)[:40]
    async with db_lock:
        known = await asyncio.to_thread(list_known_topics_sync, db_conn, 200)
    return list(known)[:40]


def safe_extract_json_obj(text: str) -> dict | None:
    if not text:
        return None
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def extract_json_array(text: str) -> list[dict]:
    """
    Strict-ish: tries json.loads; if it fails, extracts the first [...] block and loads that.
    """
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
        blob = text[start : end + 1]
        try:
            data = json.loads(blob)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    return []


async def suggest_topic_id(
    text: str,
    candidates: list[str],
    *,
    topic_suggest: bool,
    client,
    openai_model: str,
) -> tuple[str | None, float]:
    """Suggest a topic_id from candidates. Returns (topic_id|None, confidence)."""
    if not (topic_suggest and candidates):
        return (None, 0.0)

    snippet = " ".join((text or "").split())
    if len(snippet) > 600:
        snippet = snippet[:599] + "..."

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
            model=openai_model,
            messages=[
                {"role": "system", "content": sys[:1900]},
                {"role": "user", "content": user[:1900]},
            ],
        )
        raw = (resp.choices[0].message.content or "").strip()
    except Exception:
        return (None, 0.0)

    obj = safe_extract_json_obj(raw)
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
    cand_set = {t.lower() for t in candidates}
    if topic not in cand_set:
        return (None, 0.0)

    conf_f = max(0.0, min(1.0, conf_f))
    return (topic, conf_f)


def resolve_memory_lifecycle(
    *,
    memory_review_mode: str,
    source_path: str,
    owner_override_active: bool,
) -> str:
    mode = (memory_review_mode or "capture_only").strip().lower()
    source = (source_path or "").strip().lower()

    if mode not in {"off", "capture_only", "all"}:
        mode = "capture_only"

    if mode == "off":
        return "active"

    if mode == "capture_only":
        return "active" if source == "manual_remember" else "candidate"

    # mode == "all"
    if source == "manual_remember" and owner_override_active:
        return "active"
    return "candidate"


def normalize_importance_value(raw: Any, *, default: float = 0.5) -> float:
    try:
        value = float(raw)
    except Exception:
        value = float(default)
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return float(value)


async def remember_event(
    *,
    text: str,
    tags: list[str] | None,
    importance: float | int,
    message: Any | None = None,
    topic_hint: str | None = None,
    memory_review_mode: str = "capture_only",
    source_path: str = "manual_remember",
    owner_override_active: bool = False,
    stage_at_least,
    normalize_tags,
    reserved_kind_tags: set[str],
    topic_suggest: bool,
    topic_min_conf: float,
    topic_allowlist: list[str],
    db_lock,
    db_conn,
    list_known_topics_sync,
    client,
    openai_model: str,
    utc_iso,
    utc_ts,
    infer_tier,
    safe_json_dumps,
    insert_memory_event_sync,
) -> dict | None:
    if not stage_at_least("M1"):
        return None

    source_tag = str(source_path or "").strip().lower() or "manual"
    raw_tags = list(tags or [])
    if source_tag:
        raw_tags.append(f"source:{source_tag}")
    tags = normalize_memory_tags(raw_tags, preserve_legacy=True)

    topic_id: str | None = None
    if topic_hint:
        hinted_topics = extract_topics(normalize_memory_tags([topic_hint], preserve_legacy=True))
        topic_id = hinted_topics[0] if hinted_topics else None

    if not topic_id and tags:
        topics = extract_topics(tags)
        topic_id = topics[0] if topics else None

    topic_source = "manual" if topic_id else "none"
    topic_confidence: float | None = None

    if not topic_id and topic_suggest:
        candidates = await get_topic_candidates(
            topic_allowlist=topic_allowlist,
            db_lock=db_lock,
            db_conn=db_conn,
            list_known_topics_sync=list_known_topics_sync,
        )
        sug, conf = await suggest_topic_id(
            text,
            candidates,
            topic_suggest=topic_suggest,
            client=client,
            openai_model=openai_model,
        )
        if sug and conf >= topic_min_conf:
            topic_id = sug
            topic_source = "suggested"
            topic_confidence = conf
            tags = normalize_memory_tags(list(tags) + [f"topic:{topic_id}", topic_id], preserve_legacy=True)

    tags = normalize_memory_tags(tags, preserve_legacy=True)
    memory_type = extract_kind(tags) or "event"

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

    provenance: dict[str, str] = {}
    if source_tag:
        provenance["source"] = source_tag

    if message is not None:
        created_dt = message.created_at if message.created_at else None
        guild_id = message.guild.id if message.guild else None
        logged_from_channel_id = message.channel.id
        logged_from_channel_name = getattr(message.channel, "name", str(message.channel))
        logged_from_message_id = message.id
        channel_id = message.channel.id
        channel_name = getattr(message.channel, "name", str(message.channel))
        source_message_id = message.id
        author_id = message.author.id
        author_name = str(message.author)
        provenance["surface"] = "dm" if message.guild is None else "public_channel"
        provenance["channel_id"] = str(int(message.channel.id))
        provenance["message_id"] = str(int(message.id))
    else:
        provenance["surface"] = "system_job"

    created_ts = utc_ts(created_dt) if created_dt else utc_ts()
    tier = infer_tier(created_ts) if stage_at_least("M2") else 1
    lifecycle = resolve_memory_lifecycle(
        memory_review_mode=memory_review_mode,
        source_path=source_path,
        owner_override_active=owner_override_active,
    )

    payload = {
        "created_at_utc": utc_iso(created_dt) if created_dt else utc_iso(),
        "created_ts": created_ts,
        "scope": (
            f"channel:{int(channel_id)}"
            if channel_id is not None
            else (f"guild:{int(guild_id)}" if guild_id is not None else "global")
        ),
        "guild_id": guild_id,
        "channel_id": channel_id,
        "channel_name": channel_name,
        "source_message_id": source_message_id,
        "logged_from_channel_id": logged_from_channel_id,
        "logged_from_channel_name": logged_from_channel_name,
        "logged_from_message_id": logged_from_message_id,
        "source_channel_id": source_channel_id,
        "source_channel_name": source_channel_name,
        "author_id": author_id,
        "author_name": author_name,
        "type": memory_type,
        "text": (text or "").strip(),
        "tags_json": safe_json_dumps(tags),
        "provenance_json": safe_json_dumps(provenance),
        "importance": normalize_importance_value(importance, default=0.5),
        "tier": int(tier),
        "topic_id": topic_id,
        "topic_source": topic_source,
        "topic_confidence": topic_confidence,
        "summarized": 0,
        "lifecycle": lifecycle,
    }

    if not payload["text"]:
        return None

    async with db_lock:
        mem_id = await asyncio.to_thread(insert_memory_event_sync, db_conn, payload)

    return {
        "id": int(mem_id),
        "lifecycle": lifecycle,
        "topic_id": topic_id,
        "topic_source": topic_source,
        "topic_confidence": topic_confidence,
        "type": memory_type,
        "tags": tags,
    }
