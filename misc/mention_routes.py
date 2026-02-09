from __future__ import annotations

import re


def extract_dm_mode_payload(prompt: str) -> str | None:
    text = (prompt or "").strip()
    if not text:
        return None
    m = re.match(r"^dm\s*:\s*(.+)$", text, flags=re.I | re.S)
    if m:
        return m.group(1).strip()
    m2 = re.match(r"^dm\s+(.+)$", text, flags=re.I | re.S)
    if m2:
        return m2.group(1).strip()
    return None


def classify_mention_route(prompt: str) -> str:
    return "dm_draft" if extract_dm_mode_payload(prompt) is not None else "default"
