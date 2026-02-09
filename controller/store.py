from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dumps(value: Any, fallback: str) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return fallback


def _loads(text: str | None, fallback: Any) -> Any:
    if not text:
        return fallback
    try:
        return json.loads(text)
    except Exception:
        return fallback


def ensure_controller_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS context_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            caller_type TEXT NOT NULL,
            surface TEXT NOT NULL,
            channel_id INTEGER,
            guild_id INTEGER,
            sensitivity_policy_id TEXT,
            allowed_capabilities_json TEXT DEFAULT '[]',
            created_at_utc TEXT,
            updated_at_utc TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_profiles (
            id INTEGER PRIMARY KEY,
            layer_estimate TEXT DEFAULT 'unknown',
            risk_flags_json TEXT DEFAULT '[]',
            preferred_tone TEXT,
            dev_arc_meta_ids_json TEXT DEFAULT '[]',
            last_seen_at_utc TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS controller_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scope TEXT NOT NULL,
            persona TEXT DEFAULT 'guide',
            depth REAL DEFAULT 0.35,
            strictness REAL DEFAULT 0.65,
            intervention_level REAL DEFAULT 0.35,
            memory_budget_json TEXT DEFAULT '{}',
            tool_budget_json TEXT DEFAULT '[]',
            last_trained_at_utc TEXT,
            lifecycle TEXT DEFAULT 'active',
            created_at_utc TEXT,
            updated_at_utc TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS episode_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_utc TEXT NOT NULL,
            context_profile_id INTEGER,
            user_id INTEGER,
            controller_config_id INTEGER,
            input_excerpt TEXT,
            assistant_output_excerpt TEXT,
            retrieved_memory_ids_json TEXT DEFAULT '[]',
            tags_json TEXT DEFAULT '[]',
            explicit_rating INTEGER,
            implicit_signals_json TEXT DEFAULT '{}',
            human_notes TEXT,
            target_user_id INTEGER,
            target_display_name TEXT,
            target_type TEXT,
            target_confidence REAL,
            target_entity_key TEXT,
            mode_requested TEXT,
            mode_inferred TEXT,
            mode_used TEXT,
            dm_guidelines_version TEXT,
            dm_guidelines_source TEXT,
            blocking_collab INTEGER,
            critical_missing_fields_json TEXT,
            blocking_reason TEXT,
            draft_version TEXT,
            draft_variant_id TEXT,
            prompt_fingerprint TEXT,
            guild_id INTEGER,
            channel_id INTEGER,
            message_id INTEGER,
            created_at_utc TEXT
        )
        """
    )

    cur.execute("CREATE INDEX IF NOT EXISTS idx_context_profiles_surface ON context_profiles(surface)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_context_profiles_channel_id ON context_profiles(channel_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_controller_configs_scope ON controller_configs(scope)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_controller_configs_lifecycle ON controller_configs(lifecycle)")
    for stmt in (
        "ALTER TABLE episode_logs ADD COLUMN target_user_id INTEGER",
        "ALTER TABLE episode_logs ADD COLUMN target_display_name TEXT",
        "ALTER TABLE episode_logs ADD COLUMN target_type TEXT",
        "ALTER TABLE episode_logs ADD COLUMN target_confidence REAL",
        "ALTER TABLE episode_logs ADD COLUMN target_entity_key TEXT",
        "ALTER TABLE episode_logs ADD COLUMN mode_requested TEXT",
        "ALTER TABLE episode_logs ADD COLUMN mode_inferred TEXT",
        "ALTER TABLE episode_logs ADD COLUMN mode_used TEXT",
        "ALTER TABLE episode_logs ADD COLUMN dm_guidelines_version TEXT",
        "ALTER TABLE episode_logs ADD COLUMN dm_guidelines_source TEXT",
        "ALTER TABLE episode_logs ADD COLUMN blocking_collab INTEGER",
        "ALTER TABLE episode_logs ADD COLUMN critical_missing_fields_json TEXT",
        "ALTER TABLE episode_logs ADD COLUMN blocking_reason TEXT",
        "ALTER TABLE episode_logs ADD COLUMN draft_version TEXT",
        "ALTER TABLE episode_logs ADD COLUMN draft_variant_id TEXT",
        "ALTER TABLE episode_logs ADD COLUMN prompt_fingerprint TEXT",
    ):
        try:
            cur.execute(stmt)
        except sqlite3.OperationalError:
            pass
    cur.execute("CREATE INDEX IF NOT EXISTS idx_episode_logs_timestamp ON episode_logs(timestamp_utc)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_episode_logs_user_id ON episode_logs(user_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_episode_logs_context ON episode_logs(context_profile_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_episode_logs_target_user_id ON episode_logs(target_user_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_episode_logs_target_entity_key ON episode_logs(target_entity_key)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_episode_logs_mode_used ON episode_logs(mode_used)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_episode_logs_dm_guidelines_version ON episode_logs(dm_guidelines_version)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_episode_logs_blocking_collab ON episode_logs(blocking_collab)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_episode_logs_draft_variant_id ON episode_logs(draft_variant_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_episode_logs_prompt_fingerprint ON episode_logs(prompt_fingerprint)")

    conn.commit()


def seed_default_controller_configs(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    now = _utc_now_iso()

    defaults = [
        (
            "global",
            "guide",
            0.35,
            0.65,
            0.35,
            {"hot": 4, "warm": 3, "cold": 1, "summaries": 2, "meta": 0},
            [],
        ),
        (
            "caller_type:founder",
            "analyst",
            0.70,
            0.80,
            0.55,
            {"hot": 5, "warm": 4, "cold": 2, "summaries": 3, "meta": 0},
            [],
        ),
        (
            "caller_type:core_lead",
            "ops",
            0.55,
            0.75,
            0.45,
            {"hot": 5, "warm": 3, "cold": 1, "summaries": 2, "meta": 0},
            [],
        ),
        (
            "caller_type:coach",
            "coach",
            0.45,
            0.80,
            0.40,
            {"hot": 4, "warm": 3, "cold": 1, "summaries": 2, "meta": 0},
            [],
        ),
        (
            "caller_type:member",
            "guide",
            0.25,
            0.85,
            0.20,
            {"hot": 4, "warm": 2, "cold": 0, "summaries": 1, "meta": 0},
            [],
        ),
        (
            "caller_type:external",
            "guide",
            0.10,
            0.90,
            0.10,
            {"hot": 3, "warm": 1, "cold": 0, "summaries": 0, "meta": 0},
            [],
        ),
    ]

    for scope, persona, depth, strictness, intervention, memory_budget, tool_budget in defaults:
        cur.execute(
            "SELECT 1 FROM controller_configs WHERE scope = ? AND lifecycle = 'active' LIMIT 1",
            (scope,),
        )
        if cur.fetchone():
            continue
        cur.execute(
            """
            INSERT INTO controller_configs (
                scope, persona, depth, strictness, intervention_level,
                memory_budget_json, tool_budget_json, lifecycle,
                created_at_utc, updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (
                scope,
                persona,
                float(depth),
                float(strictness),
                float(intervention),
                _dumps(memory_budget, "{}"),
                _dumps(tool_budget, "[]"),
                now,
                now,
            ),
        )
    conn.commit()


def get_or_create_context_profile_sync(conn: sqlite3.Connection, payload: dict[str, Any]) -> int:
    cur = conn.cursor()
    caller_type = (payload.get("caller_type") or "member").strip()
    surface = (payload.get("surface") or "public_channel").strip()
    channel_id = payload.get("channel_id")
    guild_id = payload.get("guild_id")
    sensitivity_policy_id = (payload.get("sensitivity_policy_id") or "policy:default").strip()
    allowed_caps_json = _dumps(payload.get("allowed_capabilities", []), "[]")
    now = _utc_now_iso()

    cur.execute(
        """
        SELECT id
        FROM context_profiles
        WHERE caller_type = ?
          AND surface = ?
          AND COALESCE(channel_id, -1) = COALESCE(?, -1)
          AND COALESCE(guild_id, -1) = COALESCE(?, -1)
          AND COALESCE(sensitivity_policy_id, '') = COALESCE(?, '')
        LIMIT 1
        """,
        (caller_type, surface, channel_id, guild_id, sensitivity_policy_id),
    )
    row = cur.fetchone()
    if row:
        cid = int(row[0])
        cur.execute(
            """
            UPDATE context_profiles
            SET allowed_capabilities_json = ?, updated_at_utc = ?
            WHERE id = ?
            """,
            (allowed_caps_json, now, cid),
        )
        conn.commit()
        return cid

    cur.execute(
        """
        INSERT INTO context_profiles (
            caller_type, surface, channel_id, guild_id,
            sensitivity_policy_id, allowed_capabilities_json,
            created_at_utc, updated_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (caller_type, surface, channel_id, guild_id, sensitivity_policy_id, allowed_caps_json, now, now),
    )
    conn.commit()
    return int(cur.lastrowid)


def upsert_user_profile_last_seen_sync(conn: sqlite3.Connection, user_id: int, last_seen_at_utc: str | None = None) -> None:
    cur = conn.cursor()
    ts = last_seen_at_utc or _utc_now_iso()
    cur.execute(
        """
        INSERT INTO user_profiles (id, last_seen_at_utc)
        VALUES (?, ?)
        ON CONFLICT(id) DO UPDATE SET
            last_seen_at_utc = excluded.last_seen_at_utc
        """,
        (int(user_id), ts),
    )
    conn.commit()


def select_active_controller_config_sync(
    conn: sqlite3.Connection,
    *,
    caller_type: str,
    context_profile_id: int,
    user_id: int,
) -> dict[str, Any]:
    cur = conn.cursor()
    scope_priority = [
        f"user_id:{int(user_id)}",
        f"context_profile_id:{int(context_profile_id)}",
        f"caller_type:{caller_type}",
        "global",
    ]

    for scope in scope_priority:
        cur.execute(
            """
            SELECT id, scope, persona, depth, strictness, intervention_level,
                   memory_budget_json, tool_budget_json, lifecycle
            FROM controller_configs
            WHERE scope = ? AND lifecycle = 'active'
            ORDER BY id DESC
            LIMIT 1
            """,
            (scope,),
        )
        row = cur.fetchone()
        if not row:
            continue
        return {
            "id": int(row[0]),
            "scope": row[1],
            "persona": row[2],
            "depth": float(row[3] or 0.0),
            "strictness": float(row[4] or 0.0),
            "intervention_level": float(row[5] or 0.0),
            "memory_budget": _loads(row[6], {}),
            "tool_budget": _loads(row[7], []),
            "lifecycle": row[8],
        }

    seed_default_controller_configs(conn)
    return select_active_controller_config_sync(
        conn,
        caller_type=caller_type,
        context_profile_id=context_profile_id,
        user_id=user_id,
    )


def insert_episode_log_sync(conn: sqlite3.Connection, payload: dict[str, Any]) -> int:
    cur = conn.cursor()
    now = _utc_now_iso()
    cur.execute(
        """
        INSERT INTO episode_logs (
            timestamp_utc, context_profile_id, user_id, controller_config_id,
            input_excerpt, assistant_output_excerpt,
            retrieved_memory_ids_json, tags_json,
            explicit_rating, implicit_signals_json, human_notes,
            target_user_id, target_display_name, target_type, target_confidence, target_entity_key,
            mode_requested, mode_inferred, mode_used,
            dm_guidelines_version, dm_guidelines_source,
            blocking_collab, critical_missing_fields_json, blocking_reason,
            draft_version, draft_variant_id, prompt_fingerprint,
            guild_id, channel_id, message_id, created_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload.get("timestamp_utc") or now,
            payload.get("context_profile_id"),
            payload.get("user_id"),
            payload.get("controller_config_id"),
            payload.get("input_excerpt"),
            payload.get("assistant_output_excerpt"),
            _dumps(payload.get("retrieved_memory_ids", []), "[]"),
            _dumps(payload.get("tags", []), "[]"),
            payload.get("explicit_rating"),
            _dumps(payload.get("implicit_signals", {}), "{}"),
            payload.get("human_notes"),
            payload.get("target_user_id"),
            payload.get("target_display_name"),
            payload.get("target_type"),
            payload.get("target_confidence"),
            payload.get("target_entity_key"),
            payload.get("mode_requested"),
            payload.get("mode_inferred"),
            payload.get("mode_used"),
            payload.get("dm_guidelines_version"),
            payload.get("dm_guidelines_source"),
            int(1 if payload.get("blocking_collab") else 0),
            _dumps(payload.get("critical_missing_fields", []), "[]"),
            payload.get("blocking_reason"),
            payload.get("draft_version"),
            payload.get("draft_variant_id"),
            payload.get("prompt_fingerprint"),
            payload.get("guild_id"),
            payload.get("channel_id"),
            payload.get("message_id"),
            now,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def fetch_episode_logs_sync(conn: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            el.id, el.timestamp_utc, el.user_id, el.input_excerpt, el.assistant_output_excerpt,
            el.retrieved_memory_ids_json, el.tags_json, el.explicit_rating,
            el.target_user_id, el.target_display_name, el.target_type, el.target_confidence, el.target_entity_key,
            el.mode_requested, el.mode_inferred, el.mode_used,
            el.dm_guidelines_version, el.dm_guidelines_source,
            el.blocking_collab, el.critical_missing_fields_json, el.blocking_reason,
            el.draft_version, el.draft_variant_id, el.prompt_fingerprint,
            el.guild_id, el.channel_id, el.message_id,
            cp.caller_type, cp.surface, cp.sensitivity_policy_id,
            cc.id, cc.scope, cc.persona
        FROM episode_logs el
        LEFT JOIN context_profiles cp ON cp.id = el.context_profile_id
        LEFT JOIN controller_configs cc ON cc.id = el.controller_config_id
        ORDER BY el.id DESC
        LIMIT ?
        """,
        (max(1, min(int(limit), 200)),),
    )
    rows = cur.fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "id": int(row[0]),
                "timestamp_utc": row[1],
                "user_id": row[2],
                "input_excerpt": row[3] or "",
                "assistant_output_excerpt": row[4] or "",
                "retrieved_memory_ids": _loads(row[5], []),
                "tags": _loads(row[6], []),
                "explicit_rating": row[7],
                "target_user_id": row[8],
                "target_display_name": row[9],
                "target_type": row[10] or "unknown",
                "target_confidence": row[11],
                "target_entity_key": row[12],
                "mode_requested": row[13],
                "mode_inferred": row[14],
                "mode_used": row[15],
                "dm_guidelines_version": row[16],
                "dm_guidelines_source": row[17],
                "blocking_collab": bool(int(row[18] or 0)),
                "critical_missing_fields": _loads(row[19], []),
                "blocking_reason": row[20],
                "draft_version": row[21],
                "draft_variant_id": row[22],
                "prompt_fingerprint": row[23],
                "guild_id": row[24],
                "channel_id": row[25],
                "message_id": row[26],
                "caller_type": row[27] or "unknown",
                "surface": row[28] or "unknown",
                "sensitivity_policy_id": row[29] or "policy:default",
                "controller_config_id": row[30],
                "controller_scope": row[31] or "unknown",
                "controller_persona": row[32] or "guide",
            }
        )
    return out


def update_latest_dm_draft_feedback_sync(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    outcome: str,
    note: str | None = None,
) -> dict[str, Any] | None:
    rating_map = {
        "sent": 2,
        "keep": 1,
        "edit": 0,
        "discard": -1,
    }
    outcome_key = str(outcome or "").strip().lower()
    if outcome_key not in rating_map:
        return None

    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, COALESCE(human_notes, '')
        FROM episode_logs
        WHERE user_id = ?
          AND tags_json LIKE '%"mode:dm_draft"%'
        ORDER BY id DESC
        LIMIT 1
        """,
        (int(user_id),),
    )
    row = cur.fetchone()
    if not row:
        return None

    episode_id = int(row[0])
    prev_notes = str(row[1] or "").strip()
    note_clean = str(note or "").strip()
    merged_note = prev_notes
    if note_clean:
        merged_note = f"{prev_notes}\n{note_clean}".strip() if prev_notes else note_clean

    cur.execute(
        """
        UPDATE episode_logs
        SET explicit_rating = ?, human_notes = ?
        WHERE id = ?
        """,
        (int(rating_map[outcome_key]), merged_note, episode_id),
    )
    conn.commit()
    return {
        "episode_id": episode_id,
        "outcome": outcome_key,
        "explicit_rating": int(rating_map[outcome_key]),
        "human_notes": merged_note,
    }


def update_latest_dm_draft_evaluation_sync(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    rubric_scores: dict[str, int],
    failure_tags: list[str] | None = None,
    note: str | None = None,
) -> dict[str, Any] | None:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, COALESCE(implicit_signals_json, '{}'), COALESCE(human_notes, '')
        FROM episode_logs
        WHERE user_id = ?
          AND tags_json LIKE '%"mode:dm_draft"%'
        ORDER BY id DESC
        LIMIT 1
        """,
        (int(user_id),),
    )
    row = cur.fetchone()
    if not row:
        return None

    episode_id = int(row[0])
    implicit = _loads(row[1], {})
    if not isinstance(implicit, dict):
        implicit = {}

    eval_block = {
        "rubric": {k: int(v) for k, v in (rubric_scores or {}).items()},
        "failure_tags": [str(t).strip().lower() for t in (failure_tags or []) if str(t).strip()],
        "scored_at_utc": _utc_now_iso(),
    }
    implicit["evaluation"] = eval_block

    prev_notes = str(row[2] or "").strip()
    note_clean = str(note or "").strip()
    merged_note = prev_notes
    if note_clean:
        merged_note = f"{prev_notes}\n{note_clean}".strip() if prev_notes else note_clean

    cur.execute(
        """
        UPDATE episode_logs
        SET implicit_signals_json = ?, human_notes = ?
        WHERE id = ?
        """,
        (_dumps(implicit, "{}"), merged_note, episode_id),
    )
    conn.commit()
    return {
        "episode_id": episode_id,
        "evaluation": eval_block,
        "human_notes": merged_note,
    }
