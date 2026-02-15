from __future__ import annotations

"""This module is the single source of truth for building Discord <t:...> timestamp tags; all model behavior should use placeholders and let this module do the formatting."""

import re
from dataclasses import dataclass
from datetime import date as date_value
from datetime import datetime
from datetime import timedelta
from typing import Mapping
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError


DISCORD_TIMESTAMP_STYLES = {"t", "T", "d", "D", "f", "F", "R"}
PLACEHOLDER_PATTERN = re.compile(r"\{\{DISCORD_TS:([A-Za-z0-9_][A-Za-z0-9_-]*)\}\}")
RAW_TS_PATTERN = re.compile(r"<t:\d+(?::[tTdDfFR])?>")


@dataclass(frozen=True, slots=True)
class RecurringTimestampSpec:
    weekday: int
    hour: int
    minute: int
    timezone: str
    style: str = "f"


@dataclass(frozen=True, slots=True)
class TimestampRenderResult:
    text: str
    resolved_count: int
    unresolved_names: list[str]
    raw_tag_count: int
    blocked: bool
    block_reason: str | None


def _validate_style(style: str) -> str:
    clean = str(style or "").strip() or "f"
    if clean not in DISCORD_TIMESTAMP_STYLES:
        raise ValueError(f"Invalid Discord timestamp style: {clean}")
    return clean


def _validate_weekday(weekday: int) -> int:
    try:
        out = int(weekday)
    except Exception as exc:
        raise ValueError(f"Invalid weekday: {weekday}") from exc
    if out < 0 or out > 6:
        raise ValueError(f"Invalid weekday: {weekday} (expected 0..6)")
    return out


def _validate_hour_minute(hour: int, minute: int) -> tuple[int, int]:
    try:
        hh = int(hour)
        mm = int(minute)
    except Exception as exc:
        raise ValueError(f"Invalid hour/minute: {hour}:{minute}") from exc
    if hh < 0 or hh > 23:
        raise ValueError(f"Invalid hour: {hour} (expected 0..23)")
    if mm < 0 or mm > 59:
        raise ValueError(f"Invalid minute: {minute} (expected 0..59)")
    return hh, mm


def _require_aware_datetime(value: datetime, *, arg_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{arg_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{arg_name} must be timezone-aware")
    return value


def _require_timezone(timezone_name: str) -> ZoneInfo:
    clean = str(timezone_name or "").strip()
    if not clean:
        raise ValueError("Unknown timezone_name: ''")
    try:
        return ZoneInfo(clean)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone_name: {clean}") from exc


def format_discord_timestamp(dt: datetime, style: str = "f") -> str:
    aware = _require_aware_datetime(dt, arg_name="dt")
    style_clean = _validate_style(style)
    return f"<t:{int(aware.timestamp())}:{style_clean}>"


def next_weekday_time(
    weekday: int,
    hour: int,
    minute: int,
    timezone_name: str,
    now: datetime | None = None,
) -> datetime:
    """
    Return the next upcoming occurrence of weekday + local time in timezone_name.

    If now is None, use current time in timezone_name.
    If the target time today is still in the future, return today.
    Otherwise, return the same weekday in the following week.
    """
    wd = _validate_weekday(weekday)
    hh, mm = _validate_hour_minute(hour, minute)
    tz = _require_timezone(timezone_name)

    if now is None:
        now_local = datetime.now(tz)
    else:
        now_local = _require_aware_datetime(now, arg_name="now").astimezone(tz)

    days_ahead = (wd - now_local.weekday()) % 7
    target_date = now_local.date() + timedelta(days=days_ahead)
    candidate = datetime(target_date.year, target_date.month, target_date.day, hh, mm, tzinfo=tz)
    if candidate <= now_local:
        candidate = candidate + timedelta(days=7)
    return candidate


def next_weekday_timestamp_tag(
    weekday: int,
    hour: int,
    minute: int,
    timezone_name: str,
    style: str = "f",
    now: datetime | None = None,
) -> str:
    target = next_weekday_time(
        weekday=weekday,
        hour=hour,
        minute=minute,
        timezone_name=timezone_name,
        now=now,
    )
    return format_discord_timestamp(target, style=style)


def fixed_date_time_timestamp_tag(
    date: date_value,
    hour: int,
    minute: int,
    timezone_name: str,
    style: str = "f",
) -> str:
    if not isinstance(date, date_value):
        raise ValueError("date must be a datetime.date")
    hh, mm = _validate_hour_minute(hour, minute)
    tz = _require_timezone(timezone_name)
    style_clean = _validate_style(style)
    target = datetime(date.year, date.month, date.day, hh, mm, tzinfo=tz)
    return format_discord_timestamp(target, style=style_clean)


def _normalize_spec(
    name: str,
    value: RecurringTimestampSpec | Mapping[str, object],
    *,
    default_style: str,
) -> RecurringTimestampSpec:
    if isinstance(value, RecurringTimestampSpec):
        style = _validate_style(value.style or default_style)
        _ = _require_timezone(value.timezone)
        _ = _validate_weekday(value.weekday)
        _ = _validate_hour_minute(value.hour, value.minute)
        return RecurringTimestampSpec(
            weekday=int(value.weekday),
            hour=int(value.hour),
            minute=int(value.minute),
            timezone=str(value.timezone),
            style=style,
        )
    if not isinstance(value, Mapping):
        raise ValueError(f"Invalid timestamp spec for '{name}'")
    style = _validate_style(str(value.get("style") or default_style))
    timezone_name = str(value.get("timezone") or "").strip()
    _ = _require_timezone(timezone_name)
    weekday = _validate_weekday(int(value.get("weekday")))
    hour, minute = _validate_hour_minute(int(value.get("hour")), int(value.get("minute")))
    return RecurringTimestampSpec(
        weekday=weekday,
        hour=hour,
        minute=minute,
        timezone=timezone_name,
        style=style,
    )


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def render_named_timestamp_placeholders(
    text: str,
    *,
    events: Mapping[str, RecurringTimestampSpec | Mapping[str, object]],
    default_style: str = "f",
    unresolved_policy: str = "passthrough",
    raw_tag_policy: str = "allow",
    now: datetime | None = None,
) -> TimestampRenderResult:
    source = text or ""
    style_default = _validate_style(default_style)
    unresolved_mode = str(unresolved_policy or "passthrough").strip().lower()
    raw_mode = str(raw_tag_policy or "allow").strip().lower()
    if unresolved_mode not in {"passthrough", "block"}:
        raise ValueError(f"Invalid unresolved_policy: {unresolved_policy}")
    if raw_mode not in {"allow", "block"}:
        raise ValueError(f"Invalid raw_tag_policy: {raw_tag_policy}")

    unresolved: list[str] = []
    resolved_count = 0

    def _replace(match: re.Match[str]) -> str:
        nonlocal resolved_count
        placeholder_name = str(match.group(1) or "").strip()
        spec_value = events.get(placeholder_name)
        if spec_value is None:
            unresolved.append(placeholder_name)
            return match.group(0)
        spec = _normalize_spec(placeholder_name, spec_value, default_style=style_default)
        out = next_weekday_timestamp_tag(
            weekday=spec.weekday,
            hour=spec.hour,
            minute=spec.minute,
            timezone_name=spec.timezone,
            style=spec.style,
            now=now,
        )
        resolved_count += 1
        return out

    rendered = PLACEHOLDER_PATTERN.sub(_replace, source)
    unresolved_names = _dedupe_preserve_order(unresolved)
    raw_tag_count = len(RAW_TS_PATTERN.findall(rendered))

    blocked = False
    block_reason: str | None = None
    if unresolved_mode == "block" and unresolved_names:
        blocked = True
        block_reason = "unresolved_placeholders"
    elif raw_mode == "block" and raw_tag_count > 0:
        blocked = True
        block_reason = "raw_timestamp_tags"

    return TimestampRenderResult(
        text=rendered,
        resolved_count=resolved_count,
        unresolved_names=unresolved_names,
        raw_tag_count=raw_tag_count,
        blocked=blocked,
        block_reason=block_reason,
    )
