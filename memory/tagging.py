from __future__ import annotations

import re
from typing import Iterable


KIND_VALUES: set[str] = {
    "decision",
    "policy",
    "canon",
    "profile",
    "protocol",
    "proposal",
    "insight",
    "task",
    "event",
    "preference",
    "concept",
    "relationship",
    "instruction",
    "skill",
    "artifact_ref",
    "note",
}


def _clean_slug(raw: str) -> str:
    value = str(raw or "").strip().lower()
    value = re.sub(r"[^a-z0-9_\-]", "", value)
    return value


def _emit(out: list[str], seen: set[str], value: str) -> None:
    clean = str(value or "").strip().lower()
    if not clean or clean in seen:
        return
    seen.add(clean)
    out.append(clean)


def normalize_memory_tags(
    tags: Iterable[str] | None,
    *,
    preserve_legacy: bool = True,
) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    for raw_tag in (tags or []):
        clean = str(raw_tag or "").strip().lower()
        if not clean:
            continue

        kind_match = re.fullmatch(r"kind:([a-z0-9_\-]+)", clean)
        if kind_match:
            kind = _clean_slug(kind_match.group(1))
            if kind:
                _emit(out, seen, f"kind:{kind}")
                if preserve_legacy:
                    _emit(out, seen, kind)
            continue

        topic_match = re.fullmatch(r"topic:([a-z0-9_\-]+)", clean)
        if topic_match:
            topic = _clean_slug(topic_match.group(1))
            if topic:
                _emit(out, seen, f"topic:{topic}")
                if preserve_legacy:
                    _emit(out, seen, topic)
            continue

        subject_match = re.fullmatch(r"subject:(person|user):([0-9]{1,20})", clean)
        if subject_match:
            _emit(out, seen, f"subject:{subject_match.group(1)}:{subject_match.group(2)}")
            continue

        source_match = re.fullmatch(r"source:([a-z0-9_\-]+)", clean)
        if source_match:
            source = _clean_slug(source_match.group(1))
            if source:
                _emit(out, seen, f"source:{source}")
            continue

        # Legacy kind tags become typed kind tags.
        legacy_kind = _clean_slug(clean)
        if legacy_kind in KIND_VALUES:
            _emit(out, seen, f"kind:{legacy_kind}")
            if preserve_legacy:
                _emit(out, seen, legacy_kind)
            continue

        # Untyped tags are treated as topics.
        topic = _clean_slug(clean)
        if topic:
            _emit(out, seen, f"topic:{topic}")
            if preserve_legacy:
                _emit(out, seen, topic)

    return out


def extract_kind(tags: Iterable[str] | None) -> str | None:
    for raw_tag in (tags or []):
        clean = str(raw_tag or "").strip().lower()
        if not clean:
            continue

        match = re.fullmatch(r"kind:([a-z0-9_\-]+)", clean)
        if match:
            kind = _clean_slug(match.group(1))
            if kind:
                return kind
            continue

        kind = _clean_slug(clean)
        if kind in KIND_VALUES:
            return kind
    return None


def extract_topics(tags: Iterable[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    for raw_tag in (tags or []):
        clean = str(raw_tag or "").strip().lower()
        if not clean:
            continue

        topic_match = re.fullmatch(r"topic:([a-z0-9_\-]+)", clean)
        if topic_match:
            topic = _clean_slug(topic_match.group(1))
            if topic and topic not in seen:
                seen.add(topic)
                out.append(topic)
            continue

        if clean.startswith(("kind:", "subject:", "source:")):
            continue

        topic = _clean_slug(clean)
        if not topic or topic in KIND_VALUES or topic in seen:
            continue
        seen.add(topic)
        out.append(topic)

    return out
