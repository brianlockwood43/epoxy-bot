from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ContextProfile:
    id: int | None
    caller_type: str
    surface: str
    channel_id: int | None
    guild_id: int | None
    sensitivity_policy_id: str
    allowed_capabilities: list[str] = field(default_factory=list)


@dataclass(slots=True)
class UserProfile:
    person_id: int
    layer_estimate: str = "unknown"
    risk_flags: list[str] = field(default_factory=list)
    preferred_tone: str | None = None
    dev_arc_meta_ids: list[int] = field(default_factory=list)
    last_seen_at_utc: str | None = None


@dataclass(slots=True)
class ControllerConfig:
    id: int | None
    scope: str
    persona: str = "guide"
    depth: float = 0.35
    strictness: float = 0.65
    intervention_level: float = 0.35
    memory_budget: dict[str, int] = field(
        default_factory=lambda: {"hot": 4, "warm": 3, "cold": 1, "summaries": 2, "meta": 0}
    )
    tool_budget: list[str] = field(default_factory=list)
    lifecycle: str = "active"


@dataclass(slots=True)
class EpisodeLog:
    id: int | None
    timestamp_utc: str
    context_profile_id: int
    user_id: int
    person_id: int | None
    controller_config_id: int
    input_excerpt: str
    assistant_output_excerpt: str
    retrieved_memory_ids: list[int] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    explicit_rating: int | None = None
    implicit_signals: dict = field(default_factory=dict)
    human_notes: str | None = None
    target_user_id: int | None = None
    target_person_id: int | None = None
    target_display_name: str | None = None
    target_type: str = "unknown"
    target_confidence: float | None = None
    target_entity_key: str | None = None
    mode_requested: str | None = None
    mode_inferred: str | None = None
    mode_used: str | None = None
    dm_guidelines_version: str | None = None
    dm_guidelines_source: str | None = None
    blocking_collab: bool = False
    critical_missing_fields: list[str] = field(default_factory=list)
    blocking_reason: str | None = None
    draft_version: str | None = None
    draft_variant_id: str | None = None
    prompt_fingerprint: str | None = None
