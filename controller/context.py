from __future__ import annotations

import os
import re
from typing import Any


def parse_id_set(raw: str | None) -> set[int]:
    if not raw:
        return set()
    out: set[int] = set()
    for tok in re.split(r"[\s,;]+", raw.strip()):
        if not tok:
            continue
        if re.fullmatch(r"\d{8,22}", tok):
            out.add(int(tok))
    return out


def parse_str_set(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {tok.strip().lower() for tok in re.split(r"[\s,;]+", raw) if tok.strip()}


def resolve_allowed_channel_ids(default_ids: set[int]) -> set[int]:
    env_ids = parse_id_set(os.getenv("EPOXY_ALLOWED_CHANNEL_IDS"))
    return env_ids if env_ids else set(default_ids)


def resolve_channel_groups() -> dict[str, set[int]]:
    return {
        "leadership": parse_id_set(os.getenv("EPOXY_LEADERSHIP_CHANNEL_IDS")),
        "staff": parse_id_set(os.getenv("EPOXY_STAFF_CHANNEL_IDS")),
        "member": parse_id_set(os.getenv("EPOXY_MEMBER_CHANNEL_IDS")),
        "public": parse_id_set(os.getenv("EPOXY_PUBLIC_CHANNEL_IDS")),
    }


def classify_context(
    *,
    author_id: int,
    is_dm: bool,
    channel_id: int | None,
    guild_id: int | None,
    founder_user_ids: set[int],
    channel_groups: dict[str, set[int]],
) -> dict[str, Any]:
    if is_dm:
        caller_type = "founder" if author_id in founder_user_ids else "member"
        return {
            "caller_type": caller_type,
            "surface": "dm",
            "channel_policy_group": "dm",
            "sensitivity_policy_id": "policy:dm_privacy",
            "allowed_capabilities": ["self_context_only"],
            "channel_id": channel_id,
            "guild_id": guild_id,
        }

    cid = int(channel_id) if channel_id is not None else None
    group = "unknown"
    for name in ("leadership", "staff", "member", "public"):
        if cid is not None and cid in channel_groups.get(name, set()):
            group = name
            break

    if group == "leadership":
        caller_type = "founder" if author_id in founder_user_ids else "core_lead"
        surface = "coach_channel"
        policy_id = "policy:leadership_confidential"
        caps = ["cross_member_analysis", "strategy_access"]
    elif group == "staff":
        caller_type = "founder" if author_id in founder_user_ids else "coach"
        surface = "coach_channel"
        policy_id = "policy:staff_confidential"
        caps = ["anonymized_patterns_only", "coaching_context"]
    elif group == "member":
        caller_type = "member"
        surface = "public_channel"
        policy_id = "policy:member_privacy"
        caps = ["anonymized_patterns_only", "self_context_only"]
    elif group == "public":
        caller_type = "external"
        surface = "public_channel"
        policy_id = "policy:public_safe"
        caps = ["public_info_only"]
    else:
        caller_type = "member"
        surface = "public_channel"
        policy_id = "policy:default"
        caps = ["anonymized_patterns_only"]

    return {
        "caller_type": caller_type,
        "surface": surface,
        "channel_policy_group": group,
        "sensitivity_policy_id": policy_id,
        "allowed_capabilities": caps,
        "channel_id": cid,
        "guild_id": guild_id,
    }

