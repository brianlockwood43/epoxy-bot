from __future__ import annotations

import re
from typing import Any


def format_policy_directive(policy_bundle: dict[str, Any] | None, *, max_chars: int = 550) -> str:
    if not isinstance(policy_bundle, dict):
        return ""
    policies = policy_bundle.get("policies")
    if not isinstance(policies, list) or not policies:
        return ""

    lines = ["Policy constraints (resolved from canonical meta items):"]
    for policy in policies[:6]:
        statement = str(policy.get("statement") or "").strip()
        if not statement:
            continue
        priority = str(policy.get("priority") or "medium").lower()
        scope = str(policy.get("scope") or "global")
        lines.append(f"- [{priority}] ({scope}) {statement}")

    text = "\n".join(lines).strip()
    return text[:max_chars] if len(text) > max_chars else text


def apply_policy_enforcement(
    reply: str,
    *,
    policy_bundle: dict[str, Any] | None,
    author_id: int | None,
    caller_type: str,
    surface: str,
) -> tuple[str, list[str]]:
    text = str(reply or "")
    applied: list[str] = []
    if not text:
        return text, applied

    enforcement = {}
    if isinstance(policy_bundle, dict):
        enforcement = policy_bundle.get("enforcement") or {}
    if not isinstance(enforcement, dict):
        enforcement = {}

    member_facing = str(caller_type or "").strip().lower() in {"member", "external"} or str(surface or "") == "public_channel"

    if member_facing and (
        bool(enforcement.get("no_cross_member_private_disclosure"))
        or bool(enforcement.get("redact_discord_mentions_in_member_context"))
    ):
        if author_id is not None:
            pattern = rf"<@!?((?!{int(author_id)})\d{{8,20}})>"
        else:
            pattern = r"<@!?\d{8,20}>"
        next_text = re.sub(pattern, "[redacted-user]", text)
        if next_text != text:
            text = next_text
            applied.append("redact_discord_mentions")

    return text, applied
