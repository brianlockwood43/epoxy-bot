from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from controller.dm_draft_parser import DmDraftRequest
from controller.dm_guidelines import DmGuidelines


@dataclass(slots=True)
class DmDraftVariant:
    id: str
    label: str
    text: str
    rationale: str | None = None


@dataclass(slots=True)
class DmDraftResult:
    drafts: list[DmDraftVariant] = field(default_factory=list)
    risk_notes: list[str] = field(default_factory=list)
    optional_tighten: str | None = None
    recall_coverage: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DmDraftRun:
    result: DmDraftResult
    mode: str
    parse_quality: str
    missing_fields: list[str]
    assumptions_used: list[str] = field(default_factory=list)
    clarifying_questions: list[str] = field(default_factory=list)
    recall_count: int = 0


BOUNDARY_CONTEXT_MARKERS = {
    "boundary",
    "consent",
    "safety",
    "unsafe",
    "harm",
    "abuse",
    "threat",
    "harass",
    "membership",
    "ban",
    "remove",
    "suspend",
    "escalat",
    "conflict",
    "violation",
}


def infer_completion_mode(text: str) -> str:
    _ = text
    # Best-effort drafting is disabled; DM drafting is collaboration-only.
    return "collab"


def select_mode(*, mode_requested: str | None, prompt_text: str) -> tuple[str, str]:
    """
    Returns (mode_used, mode_inferred).
    DM drafting is collaboration-only; explicit/implicit best_effort is ignored.
    """
    mode_inferred = infer_completion_mode(prompt_text)
    requested = (mode_requested or "").strip().lower().replace("-", "_")
    if requested == "collab":
        return ("collab", mode_inferred)
    return ("collab", mode_inferred)


def build_collab_questions(missing_fields: list[str]) -> list[str]:
    mapping = {
        "target": "Who is this DM for (mention, ID, or short identifier)?",
        "objective": "What is the one-line objective for this specific DM?",
        "situation_context": "What happened right before this DM, in 1-3 lines?",
        "my_goals": "What 1-3 long-term growth goals should this support?",
        "non_negotiables": "What are your must-haves or hard boundaries for this message?",
        "tone": "What tone should I target (for example: steady, warm, direct, firm)?",
    }
    questions: list[str] = []
    for field in missing_fields:
        q = mapping.get(field)
        if q:
            questions.append(q)
        if len(questions) >= 2:
            break
    return questions


def _context_implies_boundary_risk(text: str) -> bool:
    low = (text or "").strip().lower()
    if not low:
        return False
    return any(marker in low for marker in BOUNDARY_CONTEXT_MARKERS)


def evaluate_collab_blocking(
    *,
    mode: str,
    req: DmDraftRequest,
    missing_fields: list[str],
    prompt_text: str,
) -> tuple[bool, list[str], str | None]:
    if mode != "collab":
        return (False, [], None)

    critical: list[str] = []
    reasons: list[str] = []

    if not (req.target_user_id is not None or (req.target or "").strip()):
        critical.append("target")
        reasons.append("missing_target")

    if ("objective" in missing_fields) or (not req.objective.strip()):
        critical.append("objective")
        reasons.append("missing_objective")

    needs_non_negotiables = ("non_negotiables" in missing_fields) or (not req.non_negotiables)
    if needs_non_negotiables and _context_implies_boundary_risk(f"{prompt_text}\n{req.situation_context}"):
        critical.append("non_negotiables")
        reasons.append("missing_non_negotiables_boundary_context")

    if not critical:
        return (False, [], None)

    reason = reasons[0] if len(reasons) == 1 else "multiple_critical_missing"
    # stable unique order
    out = []
    seen = set()
    for field in critical:
        if field in seen:
            continue
        seen.add(field)
        out.append(field)
    return (True, out, reason)


def _event_bucket_key(event: dict[str, Any]) -> str:
    if event.get("id") is not None:
        return f"event:{int(event['id'])}"
    text = str(event.get("text") or "").strip().lower()
    ch = str(event.get("channel_name") or event.get("source_channel_name") or "").strip().lower()
    return f"event_fallback:{ch}:{text[:120]}"


def _summary_bucket_key(summary: dict[str, Any]) -> str:
    if summary.get("id") is not None:
        return f"summary:{int(summary['id'])}"
    text = str(summary.get("summary_text") or "").strip().lower()
    topic = str(summary.get("topic_id") or "").strip().lower()
    return f"summary_fallback:{topic}:{text[:120]}"


def _as_lc_tag_set(item: dict[str, Any]) -> set[str]:
    raw_tags = item.get("tags") or []
    if not isinstance(raw_tags, list):
        return set()
    return {str(tag).strip().lower() for tag in raw_tags if str(tag).strip()}


def _topic_key(item: dict[str, Any]) -> str:
    return str(item.get("topic_id") or "").strip().lower()


def _is_note_like(item: dict[str, Any]) -> bool:
    tags = _as_lc_tag_set(item)
    topic = _topic_key(item)
    note_markers = {"note", "notes"}
    return bool((tags & note_markers) or topic in note_markers)


def _is_policy_like(item: dict[str, Any]) -> bool:
    tags = _as_lc_tag_set(item)
    topic = _topic_key(item)
    policy_markers = {"policy", "policies", "invariant", "invariants"}
    return bool((tags & policy_markers) or topic in policy_markers)


def _channel_name_for_bucket(event: dict[str, Any]) -> str:
    return (
        str(
            event.get("source_channel_name")
            or event.get("logged_from_channel_name")
            or event.get("channel_name")
            or ""
        )
        .strip()
        .lower()
    )


def _is_recent_dm_like(event: dict[str, Any]) -> bool:
    tags = _as_lc_tag_set(event)
    if "dm" in tags:
        return True
    channel = _channel_name_for_bucket(event)
    dm_markers = ("dm", "direct message", "direct-message", "private")
    return any(marker in channel for marker in dm_markers)


def _is_public_like(event: dict[str, Any]) -> bool:
    tags = _as_lc_tag_set(event)
    if "public" in tags:
        return True
    channel = _channel_name_for_bucket(event)
    public_markers = ("public", "welcome", "announcements", "general", "lfg")
    return any(marker in channel for marker in public_markers)


def compute_recall_provenance_counts(
    events: list[dict[str, Any]],
    summaries: list[dict[str, Any]],
    profile_events: list[dict[str, Any]],
) -> dict[str, int]:
    profile_keys: set[str] = set()
    recent_dm_keys: set[str] = set()
    public_keys: set[str] = set()
    note_keys: set[str] = set()
    policy_keys: set[str] = set()

    for event in events:
        key = _event_bucket_key(event)
        if _is_recent_dm_like(event):
            recent_dm_keys.add(key)
        if _is_public_like(event):
            public_keys.add(key)
        if _is_note_like(event):
            note_keys.add(key)
        if _is_policy_like(event):
            policy_keys.add(key)

    for summary in summaries:
        key = _summary_bucket_key(summary)
        if _is_note_like(summary):
            note_keys.add(key)
        if _is_policy_like(summary):
            policy_keys.add(key)

    for event in profile_events:
        profile_keys.add(_event_bucket_key(event))

    return {
        "target_profile_count": len(profile_keys),
        "recent_dm_count": len(recent_dm_keys),
        "public_interaction_count": len(public_keys),
        "notes_count": len(note_keys),
        "policy_count": len(policy_keys),
    }


def compute_recall_coverage(
    recall_count: int,
    *,
    provenance_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    n = int(max(0, recall_count))
    if n <= 2:
        out: dict[str, Any] = {
            "level": "thin",
            "count": n,
            "note": "Recall is thin; leaning mostly on manual context.",
        }
        if provenance_counts:
            out["provenance_counts"] = {k: int(v) for k, v in provenance_counts.items()}
        return out
    if n <= 7:
        out = {
            "level": "mixed",
            "count": n,
            "note": "Recall is moderate; using both prior history and manual context.",
        }
        if provenance_counts:
            out["provenance_counts"] = {k: int(v) for k, v in provenance_counts.items()}
        return out
    out = {
        "level": "rich",
        "count": n,
        "note": "Recall is strong; substantial prior history is available.",
    }
    if provenance_counts:
        out["provenance_counts"] = {k: int(v) for k, v in provenance_counts.items()}
    return out


def _safe_extract_json_obj(text: str) -> dict | None:
    if not text:
        return None

    def _escape_newlines_in_json_strings(raw: str) -> str:
        out: list[str] = []
        in_string = False
        escaped = False
        for ch in raw:
            if in_string:
                if escaped:
                    out.append(ch)
                    escaped = False
                    continue
                if ch == "\\":
                    out.append(ch)
                    escaped = True
                    continue
                if ch == '"':
                    out.append(ch)
                    in_string = False
                    continue
                if ch in {"\n", "\r"}:
                    out.append("\\n")
                    continue
                out.append(ch)
                continue

            out.append(ch)
            if ch == '"':
                in_string = True
        return "".join(out)

    def _iter_json_candidates(raw: str) -> list[str]:
        candidates: list[str] = []
        stripped = raw.strip()
        if stripped:
            candidates.append(stripped)

        fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, flags=re.I)
        if fence:
            fenced = (fence.group(1) or "").strip()
            if fenced:
                candidates.append(fenced)

        starts = [idx for idx, ch in enumerate(raw) if ch == "{"]
        for start in starts[:12]:
            depth = 0
            in_string = False
            escaped = False
            for i in range(start, len(raw)):
                ch = raw[i]
                if in_string:
                    if escaped:
                        escaped = False
                        continue
                    if ch == "\\":
                        escaped = True
                        continue
                    if ch == '"':
                        in_string = False
                    continue

                if ch == '"':
                    in_string = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = raw[start : i + 1].strip()
                        if candidate:
                            candidates.append(candidate)
                        break

        out: list[str] = []
        seen: set[str] = set()
        for item in candidates:
            if not item or item in seen:
                continue
            seen.add(item)
            out.append(item)
        return out

    for candidate in _iter_json_candidates(text):
        for probe in (candidate, _escape_newlines_in_json_strings(candidate)):
            try:
                parsed = json.loads(probe)
            except Exception:
                continue
            if isinstance(parsed, dict):
                return parsed
    return None


def _coerce_variants(payload: dict) -> list[DmDraftVariant]:
    drafts_raw = payload.get("drafts")
    if not isinstance(drafts_raw, list):
        drafts_raw = []
    out: list[DmDraftVariant] = []
    for idx, item in enumerate(drafts_raw):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        out.append(
            DmDraftVariant(
                id=str(item.get("id") or f"draft_{idx+1}"),
                label=str(item.get("label") or f"Draft {idx+1}"),
                text=text,
                rationale=str(item.get("rationale")).strip() if item.get("rationale") is not None else None,
            )
        )
    return out


def parse_dm_result_from_model(
    raw_text: str,
    *,
    recall_coverage: dict[str, Any],
    assumptions_used: list[str],
) -> DmDraftResult:
    obj = _safe_extract_json_obj(raw_text)
    if obj is None:
        fallback_notes = [str(recall_coverage.get("note") or "Recall coverage unavailable.")]
        return DmDraftResult(
            drafts=[DmDraftVariant(id="primary", label="Primary Draft", text=(raw_text or "").strip() or "(empty draft)")],
            risk_notes=fallback_notes,
            optional_tighten=None,
            recall_coverage=recall_coverage,
        )

    drafts = _coerce_variants(obj)
    if not drafts:
        primary_text = str(obj.get("draft") or "").strip() or "(empty draft)"
        drafts = [DmDraftVariant(id="primary", label="Primary Draft", text=primary_text)]

    risk_notes_raw = obj.get("risk_notes")
    risk_notes: list[str] = []
    if isinstance(risk_notes_raw, list):
        for note in risk_notes_raw:
            clean = str(note or "").strip()
            if clean:
                risk_notes.append(clean)
    elif isinstance(risk_notes_raw, str) and risk_notes_raw.strip():
        risk_notes = [risk_notes_raw.strip()]

    recall_note = str(recall_coverage.get("note") or "")
    if recall_note:
        risk_notes.append(recall_note)

    optional_tighten = obj.get("optional_tighten")
    if optional_tighten is not None:
        optional_tighten = str(optional_tighten).strip()
    if optional_tighten == "":
        optional_tighten = None

    return DmDraftResult(
        drafts=drafts,
        risk_notes=risk_notes,
        optional_tighten=optional_tighten,
        recall_coverage=recall_coverage,
    )


def build_dm_prompt_messages(
    *,
    system_prompt_base: str,
    context_pack: str,
    guidelines: DmGuidelines,
    recent_context: str,
    memory_pack: str,
    profile_pack: str,
    req: DmDraftRequest,
    mode: str,
    clarifying_questions: list[str],
    max_chars: int,
) -> list[dict[str, str]]:
    goals_block = "\n".join(f"- {item}" for item in req.my_goals) if req.my_goals else "- (none provided)"
    constraints_block = "\n".join(f"- {item}" for item in req.non_negotiables) if req.non_negotiables else "- (none provided)"
    collab_line = ""
    if clarifying_questions:
        collab_line = "If helpful, include concise follow-up questions:\n" + "\n".join(f"- {q}" for q in clarifying_questions)

    contract = (
        "Return JSON only with keys:\n"
        "- drafts: array of objects {id,label,text,rationale|null}\n"
        "- risk_notes: array of short strings\n"
        "- optional_tighten: string or null\n"
        "Use at least one draft."
    )
    task = (
        "Draft a high-emotional-load DM response for a member-facing conversation.\n"
        "Use observables-first language, avoid mind-reading claims, and provide regulation-supporting options.\n"
        f"Mode={mode}.\n\n"
        f"Objective:\n{req.objective}\n\n"
        f"Situation Context:\n{req.situation_context}\n\n"
        f"My Long-Term Goals:\n{goals_block}\n\n"
        f"Non-Negotiables:\n{constraints_block}\n\n"
        f"Tone: {req.tone}\n\n"
        f"{contract}\n\n"
        f"{collab_line}".strip()
    )

    msgs = [
        {"role": "system", "content": (system_prompt_base or "")[:max_chars]},
        {"role": "system", "content": (context_pack or "")[:max_chars]},
        {"role": "system", "content": guidelines.to_prompt_block()[:max_chars]},
        {"role": "system", "content": f"Recent channel context:\n{recent_context}"[:max_chars]},
    ]
    if memory_pack:
        msgs.append({"role": "system", "content": f"Relevant memory:\n{memory_pack}"[:max_chars]})
    if profile_pack:
        msgs.append({"role": "system", "content": profile_pack[:max_chars]})
    msgs.append({"role": "user", "content": task[:max_chars]})
    return msgs


def format_dm_result_for_discord(run: DmDraftRun) -> str:
    lines: list[str] = []
    lines.append(f"DM Draft Mode: {run.mode} | parse={run.parse_quality}")
    for idx, draft in enumerate(run.result.drafts, start=1):
        lines.append("")
        lines.append(f"Draft {idx} ({draft.label}):")
        lines.append(draft.text)
        if draft.rationale:
            lines.append(f"Rationale: {draft.rationale}")
    if run.result.risk_notes:
        lines.append("")
        lines.append("Risk Notes:")
        for note in run.result.risk_notes:
            lines.append(f"- {note}")
    if run.assumptions_used:
        lines.append("")
        lines.append("Assumptions Used:")
        for assumption in run.assumptions_used:
            lines.append(f"- {assumption}")
    if run.result.optional_tighten:
        lines.append("")
        lines.append(f"Optional Tighten: {run.result.optional_tighten}")
    if run.clarifying_questions:
        lines.append("")
        lines.append("Quick Follow-Ups:")
        for q in run.clarifying_questions:
            lines.append(f"- {q}")
    return "\n".join(lines).strip()
