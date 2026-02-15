from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Callable


def _default_false(*args, **kwargs) -> bool:
    return False


@dataclass(frozen=True)
class CommandDeps:
    # Core/shared
    db_lock: Any = None
    db_conn: Any = None
    send_chunked: Callable | None = None
    client: Any = None
    openai_model: str = "gpt-5.1"
    max_line_chars: int = 600

    # Stage + memory config
    stage_at_least: Callable[[str], bool] | None = None
    memory_stage: str = "M0"
    memory_stage_rank: int = 0
    auto_capture: bool = False
    auto_summary: bool = False
    memory_review_mode: str = "capture_only"
    topic_suggest: bool = False
    topic_min_conf: float = 0.85
    topic_allowlist: list[str] = field(default_factory=list)

    # Store/service functions
    fetch_episode_logs_sync: Callable | None = None
    update_latest_dm_draft_feedback_sync: Callable | None = None
    update_latest_dm_draft_evaluation_sync: Callable | None = None
    list_schema_migrations_sync: Callable | None = None
    topic_counts_sync: Callable | None = None
    list_known_topics_sync: Callable | None = None
    get_topic_summary_sync: Callable | None = None
    summarize_topic_func: Callable | None = None
    normalize_tags: Callable | None = None
    remember_event_func: Callable | None = None
    infer_scope: Callable[[str], str] | None = None
    recall_memory_func: Callable | None = None
    format_memory_for_llm: Callable | None = None
    subject_user_tag: Callable[[int], str] | None = None
    subject_person_tag: Callable[[int], str] | None = None
    get_or_create_person_sync: Callable | None = None
    list_candidate_memories_sync: Callable | None = None
    approve_memory_sync: Callable | None = None
    reject_memory_sync: Callable | None = None
    parse_channel_id_token: Callable | None = None
    parse_duration_to_minutes: Callable | None = None
    fetch_messages_since_sync: Callable | None = None
    fetch_latest_messages_sync: Callable | None = None
    fetch_memory_events_since_sync: Callable | None = None
    fetch_latest_memory_events_sync: Callable | None = None
    fetch_recent_context_sync: Callable | None = None
    format_recent_context: Callable | None = None
    format_memory_events_window: Callable | None = None
    extract_json_array: Callable | None = None
    is_valid_topic_id: Callable[[str], bool] | None = None
    set_memory_origin_func: Callable | None = None

    # Community/welcome/lfg
    welcome_channel_id: int = 0
    welcome_panel_factory: Callable | None = None
    lfg_source_channel_id: int = 0
    lfg_public_channel_id: int = 0
    paddock_lounge_channel_id: int = 0
    lfg_role_name: str = ""

    # Ad-hoc modules
    announcement_service: Any = None


@dataclass(frozen=True)
class CommandGates:
    in_allowed_channel: Callable[[Any], bool] = _default_false
    allowed_channel_ids: set[int] = field(default_factory=set)
    user_is_owner: Callable[[Any], bool] = _default_false
    user_is_member: Callable[[Any], bool] = _default_false
