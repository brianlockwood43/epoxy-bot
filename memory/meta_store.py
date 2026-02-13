from __future__ import annotations

import json
import sqlite3
from typing import Any


_PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _dumps(value: Any, fallback: str) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return fallback


def upsert_meta_item_sync(conn: sqlite3.Connection, payload: dict[str, Any]) -> int:
    cur = conn.cursor()
    kind = str(payload.get("kind") or "").strip().lower()
    if kind not in {"narrative", "policy"}:
        raise ValueError("kind must be 'narrative' or 'policy'")

    name = (payload.get("name") or "").strip() or None
    statement = (payload.get("statement") or "").strip() or None
    scope = (payload.get("scope") or "").strip() or "global"
    lifecycle = (payload.get("lifecycle") or "").strip() or "active"
    priority = (payload.get("priority") or "").strip().lower() or "medium"
    applies_to = (payload.get("applies_to") or "").strip() or None
    conflict_rule = (payload.get("conflict_resolution_rule") or "").strip() or None
    confidence = float(payload.get("confidence") or 0.6)
    stability = (payload.get("stability") or "").strip() or "medium"
    now_iso = str(payload.get("updated_at_utc") or payload.get("created_at_utc") or "")

    signals_json = _dumps(payload.get("signals", []), "[]")
    implications_json = _dumps(payload.get("implications", []), "[]")
    evidence_json = _dumps(payload.get("evidence", []), "[]")

    item_id = payload.get("id")
    if item_id is not None:
        cur.execute(
            """
            UPDATE meta_items
            SET kind=?, name=?, statement=?, priority=?, applies_to=?, scope=?,
                evidence_json=?, confidence=?, stability=?, lifecycle=?,
                conflict_resolution_rule=?, signals_json=?, implications_json=?, updated_at_utc=?
            WHERE id=?
            """,
            (
                kind,
                name,
                statement,
                priority,
                applies_to,
                scope,
                evidence_json,
                confidence,
                stability,
                lifecycle,
                conflict_rule,
                signals_json,
                implications_json,
                now_iso,
                int(item_id),
            ),
        )
        conn.commit()
        return int(item_id)

    cur.execute(
        """
        SELECT id
        FROM meta_items
        WHERE kind=?
          AND COALESCE(scope, 'global') = COALESCE(?, 'global')
          AND COALESCE(name, '') = COALESCE(?, '')
          AND COALESCE(statement, '') = COALESCE(?, '')
          AND COALESCE(lifecycle, 'active') = 'active'
        ORDER BY id DESC
        LIMIT 1
        """,
        (kind, scope, name, statement),
    )
    existing = cur.fetchone()
    if existing:
        meta_id = int(existing[0])
        cur.execute(
            """
            UPDATE meta_items
            SET priority=?, applies_to=?, evidence_json=?, confidence=?, stability=?,
                lifecycle=?, conflict_resolution_rule=?, signals_json=?, implications_json=?, updated_at_utc=?
            WHERE id=?
            """,
            (
                priority,
                applies_to,
                evidence_json,
                confidence,
                stability,
                lifecycle,
                conflict_rule,
                signals_json,
                implications_json,
                now_iso,
                meta_id,
            ),
        )
        conn.commit()
        return meta_id

    cur.execute(
        """
        INSERT INTO meta_items (
            kind, name, statement, priority, applies_to, scope,
            evidence_json, confidence, stability, lifecycle,
            conflict_resolution_rule, signals_json, implications_json,
            created_at_utc, updated_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            kind,
            name,
            statement,
            priority,
            applies_to,
            scope,
            evidence_json,
            confidence,
            stability,
            lifecycle,
            conflict_rule,
            signals_json,
            implications_json,
            str(payload.get("created_at_utc") or now_iso),
            now_iso,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def insert_link_sync(conn: sqlite3.Connection, payload: dict[str, Any]) -> int:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO memory_links (
            from_ref, to_ref, relation, weight, confidence, created_by, lifecycle, created_at_utc, updated_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(payload.get("from_ref") or ""),
            str(payload.get("to_ref") or ""),
            str(payload.get("relation") or "supports"),
            float(payload.get("weight") or 1.0),
            float(payload.get("confidence") or 0.6),
            str(payload.get("created_by") or "system"),
            str(payload.get("lifecycle") or "active"),
            str(payload.get("created_at_utc") or ""),
            str(payload.get("updated_at_utc") or payload.get("created_at_utc") or ""),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def list_meta_items_sync(
    conn: sqlite3.Connection,
    *,
    kind: str | None = None,
    scope: str | None = None,
    lifecycle: str = "active",
    limit: int = 50,
) -> list[dict[str, Any]]:
    cur = conn.cursor()
    clauses = ["1=1"]
    params: list[Any] = []
    if kind:
        clauses.append("kind = ?")
        params.append(str(kind).strip().lower())
    if scope:
        clauses.append("COALESCE(scope, 'global') = COALESCE(?, 'global')")
        params.append(str(scope).strip())
    if lifecycle:
        clauses.append("COALESCE(lifecycle, 'active') = ?")
        params.append(str(lifecycle).strip())
    params.append(int(limit))
    cur.execute(
        f"""
        SELECT id, kind, name, statement, priority, applies_to, scope, evidence_json, confidence, stability,
               lifecycle, conflict_resolution_rule, signals_json, implications_json, created_at_utc, updated_at_utc
        FROM meta_items
        WHERE {' AND '.join(clauses)}
        ORDER BY id DESC
        LIMIT ?
        """,
        tuple(params),
    )
    rows = cur.fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "id": int(row[0]),
                "kind": row[1],
                "name": row[2],
                "statement": row[3],
                "priority": row[4],
                "applies_to": row[5],
                "scope": row[6],
                "evidence": _loads(row[7], []),
                "confidence": float(row[8] or 0.0),
                "stability": row[9],
                "lifecycle": row[10],
                "conflict_resolution_rule": row[11],
                "signals": _loads(row[12], []),
                "implications": _loads(row[13], []),
                "created_at_utc": row[14],
                "updated_at_utc": row[15],
            }
        )
    return out


def resolve_policy_bundle_sync(
    conn: sqlite3.Connection,
    *,
    sensitivity_policy_id: str,
    caller_type: str,
    surface: str,
    limit: int = 20,
) -> dict[str, Any]:
    policy_scope = (sensitivity_policy_id or "").strip() or "policy:default"
    caller_scope = f"caller_type:{(caller_type or '').strip() or 'member'}"
    surface_scope = f"surface:{(surface or '').strip() or 'public_channel'}"
    scopes = [policy_scope, caller_scope, surface_scope, "global", "policy:default"]

    cur = conn.cursor()
    scope_placeholders = ",".join("?" for _ in scopes)
    cur.execute(
        f"""
        SELECT id, statement, priority, applies_to, scope, conflict_resolution_rule, confidence
        FROM meta_items
        WHERE kind = 'policy'
          AND COALESCE(lifecycle, 'active') = 'active'
          AND COALESCE(scope, 'global') IN ({scope_placeholders})
        ORDER BY id DESC
        LIMIT ?
        """,
        (*scopes, int(limit)),
    )
    rows = cur.fetchall()

    policies: list[dict[str, Any]] = []
    for row in rows:
        policies.append(
            {
                "id": int(row[0]),
                "statement": str(row[1] or "").strip(),
                "priority": str(row[2] or "medium").strip().lower(),
                "applies_to": str(row[3] or "").strip().lower(),
                "scope": str(row[4] or "global").strip(),
                "conflict_resolution_rule": str(row[5] or "").strip().lower(),
                "confidence": float(row[6] or 0.0),
            }
        )

    def _priority_rank(policy: dict[str, Any]) -> int:
        return _PRIORITY_ORDER.get(str(policy.get("priority") or "medium"), 9)

    policies.sort(key=_priority_rank)

    enforcement = {
        "no_cross_member_private_disclosure": False,
        "redact_discord_mentions_in_member_context": False,
    }
    for policy in policies:
        rule = str(policy.get("conflict_resolution_rule") or "")
        if "no_cross_member_private_disclosure" in rule:
            enforcement["no_cross_member_private_disclosure"] = True
        if "redact_discord_mentions_in_member_context" in rule:
            enforcement["redact_discord_mentions_in_member_context"] = True

    return {
        "policy_scope": policy_scope,
        "caller_type": caller_type,
        "surface": surface,
        "policies": policies,
        "policy_ids": [int(p["id"]) for p in policies],
        "enforcement": enforcement,
    }
