from __future__ import annotations

import re
from dataclasses import dataclass, field


REQUIRED_FIELDS = ("objective", "situation_context", "my_goals", "non_negotiables", "tone")
LIST_FIELDS = {"my_goals", "non_negotiables"}
FIELD_ALIASES = {
    "target": "target",
    "objective": "objective",
    "situation_context": "situation_context",
    "situation": "situation_context",
    "context": "situation_context",
    "my_goals": "my_goals",
    "goals": "my_goals",
    "non_negotiables": "non_negotiables",
    "non-negotiables": "non_negotiables",
    "nonnegotiables": "non_negotiables",
    "tone": "tone",
    "mode": "mode",
}


@dataclass(slots=True)
class DmDraftRequest:
    target: str | None = None
    target_user_id: int | None = None
    objective: str = ""
    situation_context: str = ""
    my_goals: list[str] = field(default_factory=list)
    non_negotiables: list[str] = field(default_factory=list)
    tone: str = ""
    mode: str | None = None
    raw_text: str = ""


@dataclass(slots=True)
class DmParseResult:
    request: DmDraftRequest
    parse_quality: str
    missing_fields: list[str]
    used_structured_parse: bool


def _extract_target_user_id(target: str | None) -> int | None:
    raw = str(target or "").strip()
    if not raw:
        return None
    mention = re.search(r"<@!?(\d{8,22})>", raw)
    if mention:
        return int(mention.group(1))
    digits = re.search(r"\b(\d{8,22})\b", raw)
    if digits:
        return int(digits.group(1))
    return None


def _split_list_value(value: str) -> list[str]:
    text = (value or "").strip()
    if not text:
        return []
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    parts = re.split(r"[|,;]\s*|\n+", text)
    out: list[str] = []
    for part in parts:
        clean = str(part or "").strip().strip("-").strip()
        if clean:
            out.append(clean)
    return out


def _normalize_field_name(name: str) -> str | None:
    clean = (name or "").strip().lower()
    clean = clean.replace("[]", "")
    return FIELD_ALIASES.get(clean)


def _normalize_mode_value(value: str) -> str | None:
    raw = (value or "").strip().lower()
    if not raw:
        return None
    token = raw.replace("-", "_").replace(" ", "_")
    if token in {"auto", "collab"}:
        return token
    return None


def _to_parse_quality(objective: str, situation_context: str, missing_fields: list[str]) -> str:
    if not objective.strip() and not situation_context.strip():
        return "insufficient"
    if not missing_fields:
        return "full"
    return "partial"


def _preprocess_text(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    if ";" in raw and "\n" not in raw:
        return raw.replace(";", "\n")
    return raw


def parse_dm_draft_request(text: str) -> DmParseResult:
    raw = _preprocess_text(text)
    req = DmDraftRequest(raw_text=raw)
    if not raw:
        missing = list(REQUIRED_FIELDS)
        return DmParseResult(req, "insufficient", missing, False)

    # Structured parse supports:
    # - key=value
    # - key: value
    # - multiline sections and bullet lists for list fields
    field_pattern = re.compile(r"^\s*([a-zA-Z_][a-zA-Z0-9_\-\[\]]*)\s*[:=]\s*(.*)\s*$")
    bullet_pattern = re.compile(r"^\s*[-*]\s+(.+)$")

    parsed_any_field = False
    current_field: str | None = None
    bucket: dict[str, list[str]] = {k: [] for k in ("objective", "situation_context", "tone", "target", "mode")}
    list_bucket: dict[str, list[str]] = {k: [] for k in LIST_FIELDS}

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        m = field_pattern.match(line)
        if m:
            maybe_field = _normalize_field_name(m.group(1))
            if maybe_field:
                parsed_any_field = True
                current_field = maybe_field
                inline = (m.group(2) or "").strip()
                if current_field in LIST_FIELDS:
                    if inline:
                        list_bucket[current_field].extend(_split_list_value(inline))
                else:
                    if inline:
                        bucket[current_field].append(inline)
                continue

        b = bullet_pattern.match(line)
        if b and current_field in LIST_FIELDS:
            parsed_any_field = True
            list_bucket[current_field].append((b.group(1) or "").strip())
            continue

        if current_field in LIST_FIELDS:
            list_bucket[current_field].append(stripped)
        elif current_field:
            bucket[current_field].append(stripped)

    if parsed_any_field:
        req.target = " ".join(bucket["target"]).strip() or None
        req.target_user_id = _extract_target_user_id(req.target)
        req.objective = " ".join(bucket["objective"]).strip()
        req.situation_context = " ".join(bucket["situation_context"]).strip()
        req.tone = " ".join(bucket["tone"]).strip()
        req.mode = _normalize_mode_value(" ".join(bucket["mode"]).strip())
        req.my_goals = [g for g in list_bucket["my_goals"] if g]
        req.non_negotiables = [n for n in list_bucket["non_negotiables"] if n]
    else:
        req.situation_context = raw

    missing_fields: list[str] = []
    if not req.objective.strip():
        missing_fields.append("objective")
    if not req.situation_context.strip():
        missing_fields.append("situation_context")
    if not req.my_goals:
        missing_fields.append("my_goals")
    if not req.non_negotiables:
        missing_fields.append("non_negotiables")
    if not req.tone.strip():
        missing_fields.append("tone")

    parse_quality = _to_parse_quality(req.objective, req.situation_context, missing_fields)
    return DmParseResult(req, parse_quality, missing_fields, parsed_any_field)
