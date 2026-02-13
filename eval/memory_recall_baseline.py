from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from typing import Any

from db.migrate import apply_sqlite_migrations
from memory.store import search_memory_events_sync
from memory.store import search_memory_summaries_sync
from retrieval.fts_query import build_fts_query
from retrieval.service import recall_memory


_STAGE_ORDER = {"M0": 0, "M1": 1, "M2": 2, "M3": 3, "M4": 4, "M5": 5, "M6": 6, "M7": 7}


class _NoopAsyncLock:
    async def __aenter__(self) -> "_NoopAsyncLock":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


def _int_or_default(value: Any, default: int) -> int:
    if value is None:
        return int(default)
    try:
        return int(value)
    except Exception:
        return int(default)


def _safe_json_loads(value: str | None) -> list[Any]:
    if not value:
        return []
    try:
        loaded = json.loads(value)
    except Exception:
        return []
    return loaded if isinstance(loaded, list) else []


def _parse_recall_scope(scope: str | None) -> tuple[str, int | None, int | None]:
    text = (scope or "auto").strip().lower()
    temporal = "auto"
    guild_id: int | None = None
    channel_id: int | None = None
    for tok in text.split():
        if tok in {"hot", "warm", "cold", "auto"}:
            temporal = tok
            continue
        if tok.startswith("guild:"):
            try:
                guild_id = int(tok.split(":", 1)[1])
            except Exception:
                guild_id = None
            continue
        if tok.startswith("channel:"):
            try:
                channel_id = int(tok.split(":", 1)[1])
            except Exception:
                channel_id = None
    return temporal, guild_id, channel_id


def _stage_at_least_factory(current_stage: str):
    current = _STAGE_ORDER.get(str(current_stage or "M3").upper(), _STAGE_ORDER["M3"])

    def _stage_at_least(stage: str) -> bool:
        target = _STAGE_ORDER.get(str(stage or "M0").upper(), _STAGE_ORDER["M0"])
        return target <= current

    return _stage_at_least


def _seed_memory_fixture(conn: sqlite3.Connection, fixture: dict[str, Any]) -> None:
    cur = conn.cursor()

    for event in fixture.get("events", []):
        event_id = int(event["id"])
        tags = [str(t) for t in (event.get("tags") or [])]
        tags_json = json.dumps(tags)
        cur.execute(
            """
            INSERT INTO memory_events (
                id, created_at_utc, created_ts, scope, guild_id, channel_id, channel_name,
                author_id, author_name, text, tags_json, importance, tier, lifecycle, topic_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                str(event.get("created_at_utc") or "2026-02-13T00:00:00+00:00"),
                int(event.get("created_ts") or 1),
                str(event.get("scope") or "global"),
                event.get("guild_id"),
                event.get("channel_id"),
                event.get("channel_name"),
                event.get("author_id"),
                event.get("author_name"),
                str(event.get("text") or ""),
                tags_json,
                _int_or_default(event.get("importance"), 0),
                _int_or_default(event.get("tier"), 1),
                str(event.get("lifecycle") or "active"),
                event.get("topic_id"),
            ),
        )
        cur.execute(
            "INSERT INTO memory_events_fts(rowid, text, tags) VALUES (?, ?, ?)",
            (event_id, str(event.get("text") or ""), " ".join(tags)),
        )

    for summary in fixture.get("summaries", []):
        summary_id = int(summary["id"])
        tags = [str(t) for t in (summary.get("tags") or [])]
        tags_json = json.dumps(tags)
        topic_id = str(summary.get("topic_id") or "general")
        summary_text = str(summary.get("summary_text") or "")
        cur.execute(
            """
            INSERT INTO memory_summaries (
                id, topic_id, summary_type, scope, created_at_utc, updated_at_utc,
                start_ts, end_ts, tags_json, importance, summary_text, lifecycle
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                summary_id,
                topic_id,
                str(summary.get("summary_type") or "topic_gist"),
                str(summary.get("scope") or "global"),
                str(summary.get("created_at_utc") or "2026-02-13T00:00:00+00:00"),
                str(summary.get("updated_at_utc") or "2026-02-13T00:00:00+00:00"),
                int(summary.get("start_ts") or 1),
                int(summary.get("end_ts") or 1),
                tags_json,
                _int_or_default(summary.get("importance"), 1),
                summary_text,
                str(summary.get("lifecycle") or "active"),
            ),
        )
        cur.execute(
            "INSERT INTO memory_summaries_fts(rowid, topic_id, summary_text, tags) VALUES (?, ?, ?, ?)",
            (summary_id, topic_id, summary_text, " ".join(tags)),
        )

    conn.commit()


def load_memory_recall_fixture(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("memory recall fixture must be a JSON object")
    return data


def _evaluate_case(case: dict[str, Any], events: list[dict[str, Any]], summaries: list[dict[str, Any]]) -> dict[str, Any]:
    name = str(case.get("name") or "unnamed")
    observed_event_ids = [int(row.get("id")) for row in events if row.get("id") is not None]
    observed_summary_ids = [int(row.get("id")) for row in summaries if row.get("id") is not None]
    observed_tiers = [_int_or_default(row.get("tier"), 0) for row in events]

    reasons: list[str] = []

    if "expected_event_ids" in case:
        expected = [int(v) for v in case.get("expected_event_ids", [])]
        if observed_event_ids != expected:
            reasons.append(f"expected_event_ids={expected}, observed={observed_event_ids}")

    if "expected_summary_ids" in case:
        expected = [int(v) for v in case.get("expected_summary_ids", [])]
        if observed_summary_ids != expected:
            reasons.append(f"expected_summary_ids={expected}, observed={observed_summary_ids}")

    for forbidden in case.get("unexpected_event_ids", []):
        if int(forbidden) in observed_event_ids:
            reasons.append(f"unexpected_event_id={int(forbidden)}")
    for forbidden in case.get("unexpected_summary_ids", []):
        if int(forbidden) in observed_summary_ids:
            reasons.append(f"unexpected_summary_id={int(forbidden)}")

    min_events = case.get("min_events")
    max_events = case.get("max_events")
    if min_events is not None and len(observed_event_ids) < int(min_events):
        reasons.append(f"min_events={int(min_events)} not met ({len(observed_event_ids)})")
    if max_events is not None and len(observed_event_ids) > int(max_events):
        reasons.append(f"max_events={int(max_events)} exceeded ({len(observed_event_ids)})")

    min_summaries = case.get("min_summaries")
    max_summaries = case.get("max_summaries")
    if min_summaries is not None and len(observed_summary_ids) < int(min_summaries):
        reasons.append(f"min_summaries={int(min_summaries)} not met ({len(observed_summary_ids)})")
    if max_summaries is not None and len(observed_summary_ids) > int(max_summaries):
        reasons.append(f"max_summaries={int(max_summaries)} exceeded ({len(observed_summary_ids)})")

    required_tiers = {int(v) for v in case.get("required_tiers", [])}
    observed_tier_set = set(observed_tiers)
    missing_tiers = sorted(required_tiers - observed_tier_set)
    if missing_tiers:
        reasons.append(f"required_tiers_missing={missing_tiers}")

    forbidden_tiers = {int(v) for v in case.get("forbidden_tiers", [])}
    hit_forbidden = sorted(observed_tier_set.intersection(forbidden_tiers))
    if hit_forbidden:
        reasons.append(f"forbidden_tiers_present={hit_forbidden}")

    return {
        "name": name,
        "passed": len(reasons) == 0,
        "reasons": reasons,
        "observed_event_ids": observed_event_ids,
        "observed_summary_ids": observed_summary_ids,
        "observed_tiers": observed_tiers,
    }


async def run_memory_recall_baseline(fixture: dict[str, Any]) -> dict[str, Any]:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    try:
        apply_sqlite_migrations(conn, os.path.join(os.getcwd(), "migrations"))
        _seed_memory_fixture(conn, fixture)

        stage_name = str(fixture.get("stage") or "M3").upper()
        stage_at_least = _stage_at_least_factory(stage_name)

        def _search_events(_conn, query: str, scope: str, limit: int):
            return search_memory_events_sync(
                _conn,
                query,
                scope,
                int(limit),
                build_fts_query=build_fts_query,
                parse_recall_scope=_parse_recall_scope,
                stage_at_least=stage_at_least,
                safe_json_loads=_safe_json_loads,
            )

        def _search_summaries(_conn, query: str, scope: str, limit: int):
            return search_memory_summaries_sync(
                _conn,
                query,
                scope,
                int(limit),
                build_fts_query=build_fts_query,
                parse_recall_scope=_parse_recall_scope,
                safe_json_loads=_safe_json_loads,
            )

        results: list[dict[str, Any]] = []
        for case in fixture.get("cases", []):
            prompt = str(case.get("prompt") or "")
            scope = str(case.get("scope") or "auto")
            memory_budget = case.get("memory_budget")
            events, summaries = await recall_memory(
                prompt,
                scope,
                memory_budget,
                stage_at_least=stage_at_least,
                db_lock=_NoopAsyncLock(),
                db_conn=conn,
                search_memory_events_sync=_search_events,
                search_memory_summaries_sync=_search_summaries,
            )
            results.append(_evaluate_case(case, events, summaries))

        failed = [r for r in results if not r["passed"]]
        return {
            "stage": stage_name,
            "total": len(results),
            "failed": len(failed),
            "passed": len(failed) == 0,
            "results": results,
        }
    finally:
        conn.close()


async def run_memory_recall_baseline_from_fixture(path: str) -> dict[str, Any]:
    fixture = load_memory_recall_fixture(path)
    return await run_memory_recall_baseline(fixture)


def run_memory_recall_baseline_sync(path: str) -> dict[str, Any]:
    return asyncio.run(run_memory_recall_baseline_from_fixture(path))
