from __future__ import annotations

import asyncio
import re
import time


def _canonical_summary_scope(scope: str | None) -> str:
    text = (scope or "").strip().lower()
    if not text:
        return "global"

    channel_match = re.search(r"\bchannel:(\d{1,20})\b", text)
    if channel_match:
        return f"channel:{int(channel_match.group(1))}"

    guild_match = re.search(r"\bguild:(\d{1,20})\b", text)
    if guild_match:
        return f"guild:{int(guild_match.group(1))}"

    return "global"


async def summarize_topic(
    topic_id: str,
    *,
    scope: str = "auto",
    summary_type: str = "topic_gist",
    min_age_days: int = 14,
    stage_at_least,
    db_lock,
    db_conn,
    get_topic_summary_sync,
    fetch_topic_events_sync,
    client,
    openai_model: str,
    normalize_tags,
    utc_iso,
    safe_json_dumps,
    upsert_summary_sync,
    mark_events_summarized_sync,
) -> str:
    if not stage_at_least("M3"):
        return "Memory stage is not M3; summaries are disabled."

    topic_id = (topic_id or "").strip().lower()
    if not topic_id:
        return "Missing topic_id."
    summary_type = (summary_type or "").strip() or "topic_gist"
    scope = (scope or "auto").strip() or "auto"

    async with db_lock:
        existing = await asyncio.to_thread(get_topic_summary_sync, db_conn, topic_id, scope, summary_type)
        events = await asyncio.to_thread(fetch_topic_events_sync, db_conn, topic_id, scope, min_age_days, 200)

    if not events:
        if existing:
            return existing["summary_text"]
        return f"No eligible events to summarize for topic '{topic_id}'."

    lines = []
    for e in events:
        when = e.get("created_at_utc") or ""
        who = e.get("author_name") or ""
        txt = " ".join((e.get("text") or "").split())
        if len(txt) > 260:
            txt = txt[:259] + "..."
        lines.append(f"[{when}] {who}: {txt}")
    source_pack = "\\n".join(lines)
    if len(source_pack) > 6500:
        source_pack = source_pack[:6500] + "\\n...(truncated)"

    prior = existing["summary_text"] if existing else ""
    sys = (
        "You are Epoxy's memory consolidator.\\n"
        "Your job: produce a compact, staff-usable topic summary from the event snippets.\\n"
        "Rules:\\n"
        "- Output 3-8 bullet points.\\n"
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
            model=openai_model,
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

    start_ts = min(e["created_ts"] for e in events)
    end_ts = max(e["created_ts"] for e in events)
    tags = normalize_tags([topic_id])
    payload = {
        "topic_id": topic_id,
        "scope": _canonical_summary_scope(scope),
        "summary_type": summary_type,
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
        await asyncio.to_thread(upsert_summary_sync, db_conn, payload)
        await asyncio.to_thread(mark_events_summarized_sync, db_conn, event_ids)

    return summary_text


async def maintenance_loop(
    *,
    stage_at_least,
    db_lock,
    db_conn,
    cleanup_memory_sync,
    auto_summary: bool,
    memory_stage: str,
    summarize_topic_func,
    interval_seconds: int = 3600,
    min_age_days: int = 14,
) -> None:
    if not stage_at_least("M1"):
        return

    while True:
        try:
            async with db_lock:
                transitioned_events, transitioned_summaries = await asyncio.to_thread(cleanup_memory_sync, db_conn)
            if transitioned_events or transitioned_summaries:
                print(
                    "[Memory] cleanup transitions "
                    f"events={transitioned_events} summaries={transitioned_summaries} stage={memory_stage}"
                )

            if auto_summary and stage_at_least("M3"):
                cutoff = int(time.time()) - min_age_days * 86400
                async with db_lock:
                    rows = await asyncio.to_thread(
                        lambda c: c.execute(
                            "SELECT topic_id, COUNT(*) as n FROM memory_events "
                            "WHERE importance=1 AND summarized=0 AND created_ts < ? "
                            "AND COALESCE(lifecycle, 'active')='active' "
                            "AND topic_id IS NOT NULL AND topic_id != '' "
                            "GROUP BY topic_id ORDER BY n DESC LIMIT 2",
                            (cutoff,),
                        ).fetchall(),
                        db_conn,
                    )
                topics = [(t, int(n)) for (t, n) in rows if t]
                for topic_id, n in topics:
                    print(f"[Memory] auto-summarizing topic={topic_id} events={n}")
                    _ = await summarize_topic_func(topic_id, min_age_days=min_age_days)

        except Exception as e:
            print(f"[Memory] maintenance loop error: {e}")

        await asyncio.sleep(max(60, int(interval_seconds)))
