from __future__ import annotations

from typing import Any


def should_log_episode(filters: set[str], runtime_ctx: dict[str, Any]) -> bool:
    """
    Supports:
    - prefixed tokens: caller:<type>, context:<group>, surface:<surface>
    - bare tokens for backwards compatibility and convenience:
      - caller types: founder/core_lead/coach/member/external
      - context groups: dm/public/member/staff/leadership/unknown
      - surfaces: dm/public_channel/coach_channel/system_job
    - special token: all
    """
    if not filters:
        return True

    normalized = {str(token or "").strip().lower() for token in filters if str(token or "").strip()}
    if not normalized:
        return True
    if "all" in normalized:
        return True

    caller = str(runtime_ctx.get("caller_type") or "").strip().lower()
    context = str(runtime_ctx.get("channel_policy_group") or "").strip().lower()
    surface = str(runtime_ctx.get("surface") or "").strip().lower()

    for token in normalized:
        if ":" in token:
            key, value = token.split(":", 1)
            key = key.strip()
            value = value.strip()
            if not value:
                continue
            if key in {"caller", "caller_type"} and value == caller:
                return True
            if key in {"context", "group", "channel_group"} and value == context:
                return True
            if key in {"surface"} and value == surface:
                return True
            continue

        if token in {caller, context, surface}:
            return True

    return False
