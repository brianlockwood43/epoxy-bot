from __future__ import annotations

import asyncio
import hashlib
import re


def _coerce_nonneg_int(value: object, default: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = int(default)
    return max(0, parsed)


def normalize_memory_budget(memory_budget: dict | None, *, stage_at_least) -> tuple[dict[int, int], int, int, int]:
    """
    Convert controller memory_budget to concrete retrieval limits.

    Returns:
      (tier_caps, event_limit, summary_limit, event_search_limit)
    """
    defaults = {"hot": 4, "warm": 3, "cold": 1, "summaries": 2}
    raw = memory_budget if isinstance(memory_budget, dict) else {}

    hot = _coerce_nonneg_int(raw.get("hot"), defaults["hot"])
    warm = _coerce_nonneg_int(raw.get("warm"), defaults["warm"])
    cold = _coerce_nonneg_int(raw.get("cold"), defaults["cold"])
    summaries = _coerce_nonneg_int(raw.get("summaries"), defaults["summaries"])

    tier_caps = {0: hot, 1: warm, 2: cold, 3: 0}
    event_limit = hot + warm + cold
    if event_limit <= 0:
        event_limit = defaults["hot"] + defaults["warm"] + defaults["cold"]

    summary_limit = summaries if stage_at_least("M3") else 0
    event_search_limit = max(20, event_limit * 5)
    return (tier_caps, event_limit, summary_limit, event_search_limit)


def budget_and_diversify_events(
    events: list[dict],
    scope: str,
    *,
    stage_at_least,
    limit: int = 8,
    tier_caps: dict[int, int] | None = None,
) -> list[dict]:
    """
    Apply simple budgets to reduce near-duplicates and keep a healthy mix.

    Deterministic (stable for a given input ordering) so you can test retrieval behavior.
    Enforces tier budgets (hot/warm/cold) in M2+ to prevent cold-memory bleed.
    """
    if not events or int(limit or 0) <= 0:
        return []

    limit = int(limit)
    topic_cap = 3
    channel_cap = 4
    author_cap = 3

    s = (scope or "").strip().lower()
    if ("channel:" in s) or ("guild:" in s):
        channel_cap = limit

    def _tier_caps(n: int) -> dict[int, int]:
        n = max(1, int(n))
        if n <= 3:
            return {0: n, 1: 0, 2: 0, 3: 0}

        hot = max(1, int(round(n * 0.50)))
        warm = max(0, int(round(n * 0.375)))
        cold = max(0, n - hot - warm)

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

    if stage_at_least("M2") and tier_caps is not None:
        caps = {
            0: max(0, int(tier_caps.get(0, 0))),
            1: max(0, int(tier_caps.get(1, 0))),
            2: max(0, int(tier_caps.get(2, 0))),
            3: max(0, int(tier_caps.get(3, 0))),
        }
    else:
        caps = _tier_caps(limit) if stage_at_least("M2") else {0: limit, 1: limit, 2: limit, 3: limit}
    tier_counts: dict[int, int] = {}

    def _fp(e: dict) -> str:
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
        if stage_at_least("M2") and tier >= 3:
            continue

        if stage_at_least("M2") and tier_counts.get(tier, 0) >= caps.get(tier, 0):
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


async def recall_memory(
    prompt: str,
    scope: str | None = None,
    memory_budget: dict | None = None,
    *,
    stage_at_least,
    db_lock,
    db_conn,
    search_memory_events_sync,
    search_memory_summaries_sync,
) -> tuple[list[dict], list[dict]]:
    if not stage_at_least("M1"):
        return ([], [])

    scope = (scope or ("auto" if stage_at_least("M2") else "auto"))
    tier_caps, event_limit, summary_limit, event_search_limit = normalize_memory_budget(
        memory_budget,
        stage_at_least=stage_at_least,
    )
    async with db_lock:
        events = await asyncio.to_thread(search_memory_events_sync, db_conn, prompt, scope, event_search_limit)
        events = budget_and_diversify_events(
            events,
            scope,
            stage_at_least=stage_at_least,
            limit=event_limit,
            tier_caps=tier_caps,
        )
        summaries = []
        if stage_at_least("M3") and summary_limit > 0:
            summaries = await asyncio.to_thread(search_memory_summaries_sync, db_conn, prompt, scope, summary_limit)
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
            who = e.get("author_name") or "unknown-author"
            try:
                importance_value = float(e.get("importance") or 0.0)
            except Exception:
                importance_value = 0.0
            imp = "!" if importance_value >= 0.75 else ""
            topic = (e.get("topic_id") or "")
            topic_meta = f"topic={topic} " if topic else ""

            logged_from_ch = e.get("logged_from_channel_name") or e.get("channel_name") or "unknown-channel"
            logged_from_id = e.get("logged_from_channel_id") or e.get("channel_id")
            logged_from = f"#{logged_from_ch}" if logged_from_ch else "unknown-channel"
            if logged_from_id:
                logged_from = f"{logged_from}({logged_from_id})"

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
            lines.append(f"- [{when}] {imp}{who} {prov}{topic_meta}tags=[{tags}] :: {text}")

    out = "\n".join(lines).strip()
    return out[:max_chars] if len(out) > max_chars else out


def format_profile_for_llm(user_blocks: list[tuple[int, str, list[dict]]], max_chars: int = 900) -> str:
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
                lines.append(f"  - [{when}] {who} #{ch} :: {txt}")
        lines.append("")

    out = "\n".join(lines).strip()
    return out[:max_chars] if len(out) > max_chars else out


def format_memory_events_window(rows: list[tuple[str, str, str, str]], max_chars: int = 12000) -> str:
    if not rows:
        return "(no memory events)"
    rows = list(reversed(rows))
    out_lines = []
    total = 0
    for created_at_utc, author_name, channel_name, text in rows:
        ts = created_at_utc
        if ts and "T" in ts:
            try:
                ts = ts.split("T", 1)[1][:5]
            except Exception:
                pass
        channel = channel_name or "unknown-channel"
        who = author_name or "unknown-author"
        clean = " ".join((text or "").split())
        line = f"[{ts}] {who} #{channel} :: {clean}"
        if total + len(line) + 1 > max_chars:
            break
        out_lines.append(line)
        total += len(line) + 1
    return "\n".join(out_lines)


def parse_duration_to_minutes(token: str) -> int | None:
    value = (token or "").strip().lower()
    if value in {"hot", "--hot"}:
        return 30
    match = re.match(r"^(\d{1,3})\s*([mh])$", value)
    if not match:
        return None
    n = int(match.group(1))
    unit = match.group(2)
    return n * 60 if unit == "h" else n


def format_recent_context(rows: list[tuple[str, str, str]], max_chars: int, max_line_chars: int) -> str:
    if not rows:
        return "(no recent context found)"

    rows = list(reversed(rows))
    lines: list[str] = []
    total = 0

    for created_at_utc, author_name, content in rows:
        clean = " ".join((content or "").split())

        if len(clean) > max_line_chars:
            head_len = int(max_line_chars * 0.65)
            tail_len = max_line_chars - head_len - 3
            head = clean[:head_len].rstrip()
            tail = clean[-tail_len:].lstrip() if tail_len > 0 else ""
            clean = f"{head}...{tail}"

        ts = created_at_utc
        if "T" in created_at_utc:
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


async def get_recent_channel_context(
    channel_id: int,
    before_message_id: int,
    *,
    db_lock,
    db_conn,
    fetch_recent_context_sync,
    recent_context_limit: int,
    recent_context_max_chars: int,
    max_line_chars: int,
) -> tuple[str, int]:
    async with db_lock:
        rows = await asyncio.to_thread(
            fetch_recent_context_sync,
            db_conn,
            channel_id,
            before_message_id,
            recent_context_limit,
        )
    text = format_recent_context(rows, recent_context_max_chars, max_line_chars)
    return text, len(rows)
