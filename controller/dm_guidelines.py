from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class DmGuidelines:
    version: str = "dm_guidelines_v1"
    output_contract: dict[str, Any] = field(default_factory=dict)
    observables_language_rules: list[str] = field(default_factory=list)
    non_mind_reading_constraints: list[str] = field(default_factory=list)
    regulation_support_moves: list[str] = field(default_factory=list)
    disallowed_moves: list[str] = field(default_factory=list)
    voice_constraints: list[str] = field(default_factory=list)
    non_negotiables: list[str] = field(default_factory=list)

    def to_prompt_block(self) -> str:
        lines: list[str] = [f"DM Guidelines (version={self.version})"]
        if self.non_negotiables:
            lines.append("Non-negotiables:")
            for item in self.non_negotiables:
                lines.append(f"- {item}")
        if self.observables_language_rules:
            lines.append("Observables-first language rules:")
            for item in self.observables_language_rules:
                lines.append(f"- {item}")
        if self.non_mind_reading_constraints:
            lines.append("Non-mind-reading constraints:")
            for item in self.non_mind_reading_constraints:
                lines.append(f"- {item}")
        if self.regulation_support_moves:
            lines.append("Regulation-support moves:")
            for item in self.regulation_support_moves:
                lines.append(f"- {item}")
        if self.disallowed_moves:
            lines.append("Disallowed moves:")
            for item in self.disallowed_moves:
                lines.append(f"- {item}")
        if self.voice_constraints:
            lines.append("Voice constraints:")
            for item in self.voice_constraints:
                lines.append(f"- {item}")
        if self.output_contract:
            lines.append(f"Output contract: {self.output_contract}")
        return "\n".join(lines)


def default_dm_guidelines() -> DmGuidelines:
    return DmGuidelines(
        version="dm_guidelines_v1",
        output_contract={
            "sections": ["drafts", "risk_notes", "optional_tighten"],
            "drafts": {"min": 1, "max": 3},
            "risk_notes": {"min": 2, "max": 8},
        },
        observables_language_rules=[
            "Describe concrete language/behavioral patterns instead of hidden motives.",
            "Prefer phrasing like 'this sounds fast/intense/all-or-nothing' over diagnosis.",
        ],
        non_mind_reading_constraints=[
            "Do not claim certainty about internal states.",
            "Avoid clinical framing unless explicitly requested and clearly grounded.",
        ],
        regulation_support_moves=[
            "Offer choices that slow pace and increase agency.",
            "Use short options that reduce escalation and preserve dignity.",
        ],
        disallowed_moves=[
            "No contempt, mockery, or moral grandstanding.",
            "No private detail leakage about other members.",
        ],
        voice_constraints=[
            "Clear, respectful, and direct.",
            "Keep emotionally loaded wording grounded and non-accusatory.",
        ],
        non_negotiables=[
            "No mind-reading claims.",
            "No shaming language.",
            "Stay aligned to long-term growth and relationship continuity.",
        ],
    )


def _as_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            out.append(text)
    return out


def load_dm_guidelines(path: str | Path | None) -> tuple[DmGuidelines, str | None]:
    """
    Returns (guidelines, warning_message). warning_message is None on clean load.
    """
    defaults = default_dm_guidelines()
    if not path:
        return (defaults, "DM guidelines path missing; using built-in defaults.")

    p = Path(path)
    if not p.exists():
        return (defaults, f"DM guidelines file not found at {p}; using built-in defaults.")

    try:
        payload = yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception as exc:
        return (defaults, f"Failed to read DM guidelines from {p}: {exc}; using built-in defaults.")

    if not isinstance(payload, dict):
        return (defaults, f"Invalid DM guidelines format in {p}; using built-in defaults.")

    guidelines = DmGuidelines(
        version=str(payload.get("version") or defaults.version),
        output_contract=payload.get("output_contract") if isinstance(payload.get("output_contract"), dict) else defaults.output_contract,
        observables_language_rules=_as_list(payload.get("observables_language_rules")) or defaults.observables_language_rules,
        non_mind_reading_constraints=_as_list(payload.get("non_mind_reading_constraints")) or defaults.non_mind_reading_constraints,
        regulation_support_moves=_as_list(payload.get("regulation_support_moves")) or defaults.regulation_support_moves,
        disallowed_moves=_as_list(payload.get("disallowed_moves")) or defaults.disallowed_moves,
        voice_constraints=_as_list(payload.get("voice_constraints")) or defaults.voice_constraints,
        non_negotiables=_as_list(payload.get("non_negotiables")) or defaults.non_negotiables,
    )
    return (guidelines, None)
