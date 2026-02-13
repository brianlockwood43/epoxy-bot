from __future__ import annotations

import json
import os
import sqlite3
from typing import Any

from db.migrate import apply_sqlite_migrations
from memory.meta_service import apply_policy_enforcement
from memory.meta_service import format_policy_directive
from memory.meta_store import resolve_policy_bundle_sync
from memory.meta_store import upsert_meta_item_sync


def load_controller_policy_fixture(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("controller policy fixture must be a JSON object")
    return data


def _seed_extra_policies(conn: sqlite3.Connection, fixture: dict[str, Any]) -> None:
    for payload in fixture.get("extra_policies", []):
        if not isinstance(payload, dict):
            continue
        upsert_meta_item_sync(conn, payload)


def _evaluate_case(
    case: dict[str, Any],
    *,
    bundle: dict[str, Any],
    directive: str,
    enforced_reply: str,
    clamps: list[str],
    original_reply: str,
) -> dict[str, Any]:
    name = str(case.get("name") or "unnamed")
    reasons: list[str] = []

    min_policy_count = case.get("min_policy_count")
    if min_policy_count is not None and len(bundle.get("policy_ids", [])) < int(min_policy_count):
        reasons.append(
            f"min_policy_count={int(min_policy_count)} not met ({len(bundle.get('policy_ids', []))})"
        )

    for flag in case.get("required_enforcement_flags", []):
        key = str(flag)
        if not bool((bundle.get("enforcement") or {}).get(key)):
            reasons.append(f"required_enforcement_flag_missing={key}")

    observed_clamps = [str(c) for c in clamps]
    for required in case.get("required_clamps", []):
        req = str(required)
        if req not in observed_clamps:
            reasons.append(f"required_clamp_missing={req}")
    for forbidden in case.get("forbidden_clamps", []):
        bad = str(forbidden)
        if bad in observed_clamps:
            reasons.append(f"forbidden_clamp_present={bad}")

    expect_reply_changed = case.get("expect_reply_changed")
    if expect_reply_changed is not None:
        changed = enforced_reply != original_reply
        if bool(expect_reply_changed) != changed:
            reasons.append(f"expect_reply_changed={bool(expect_reply_changed)} observed={changed}")

    for token in case.get("required_substrings", []):
        s = str(token)
        if s not in enforced_reply:
            reasons.append(f"required_substring_missing={s}")
    for token in case.get("forbidden_substrings", []):
        s = str(token)
        if s in enforced_reply:
            reasons.append(f"forbidden_substring_present={s}")

    for token in case.get("directive_must_include", []):
        s = str(token)
        if s not in directive:
            reasons.append(f"directive_missing={s}")

    return {
        "name": name,
        "passed": len(reasons) == 0,
        "reasons": reasons,
        "resolved_policy_ids": list(bundle.get("policy_ids", [])),
        "applied_clamps": observed_clamps,
        "directive": directive,
        "output_reply": enforced_reply,
    }


def run_controller_policy_adherence_baseline(fixture: dict[str, Any]) -> dict[str, Any]:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    try:
        apply_sqlite_migrations(conn, os.path.join(os.getcwd(), "migrations"))
        _seed_extra_policies(conn, fixture)

        results: list[dict[str, Any]] = []
        for case in fixture.get("cases", []):
            sensitivity_policy_id = str(case.get("sensitivity_policy_id") or "policy:default")
            caller_type = str(case.get("caller_type") or "member")
            surface = str(case.get("surface") or "public_channel")
            author_id = case.get("author_id")
            if author_id is not None:
                author_id = int(author_id)
            reply = str(case.get("reply") or "")

            bundle = resolve_policy_bundle_sync(
                conn,
                sensitivity_policy_id=sensitivity_policy_id,
                caller_type=caller_type,
                surface=surface,
            )
            directive = format_policy_directive(bundle, max_chars=1200)
            enforced_reply, clamps = apply_policy_enforcement(
                reply,
                policy_bundle=bundle,
                author_id=author_id,
                caller_type=caller_type,
                surface=surface,
            )
            results.append(
                _evaluate_case(
                    case,
                    bundle=bundle,
                    directive=directive,
                    enforced_reply=enforced_reply,
                    clamps=clamps,
                    original_reply=reply,
                )
            )

        failed = [r for r in results if not r["passed"]]
        return {
            "total": len(results),
            "failed": len(failed),
            "passed": len(failed) == 0,
            "results": results,
        }
    finally:
        conn.close()


def run_controller_policy_adherence_baseline_from_fixture(path: str) -> dict[str, Any]:
    fixture = load_controller_policy_fixture(path)
    return run_controller_policy_adherence_baseline(fixture)

