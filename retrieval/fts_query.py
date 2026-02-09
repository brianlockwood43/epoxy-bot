from __future__ import annotations

import re


def build_fts_query(q: str) -> str:
    """Build a conservative FTS5 query string from free text."""
    text = (q or "").strip()
    if not text:
        return ""

    # Hyphenated tokens can be parsed as operators/column syntax by SQLite FTS.
    # Normalize punctuation separators into spaces before tokenization.
    text = re.sub(r"[-/]+", " ", text)

    words = re.findall(r"[A-Za-z0-9_]{3,}", text.lower())
    words = words[:10]
    if not words:
        return ""

    # OR keeps recall forgiving while avoiding raw user query syntax.
    return " OR ".join(words)
