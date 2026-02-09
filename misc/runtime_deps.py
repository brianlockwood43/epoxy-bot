from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class RuntimeDeps:
    # core
    db_lock: Any
    db_conn: Any
    send_chunked: Callable
    user_is_owner: Callable

    # stages / time
    stage_at_least: Callable[[str], bool]
    memory_stage: str
    utc_iso: Callable[[], str]

    # logging / ingestion
    log_message_func: Callable
    maybe_auto_capture_func: Callable

    # context + controller
    build_context_pack: Callable[[], str]
    classify_context: Callable[..., dict]
    founder_user_ids: set[int]
    channel_policy_groups: dict
    get_recent_channel_context_func: Callable
    fetch_last_messages_by_author_sync: Callable
    get_or_create_context_profile_sync: Callable
    upsert_user_profile_last_seen_sync: Callable
    select_active_controller_config_sync: Callable

    # memory
    infer_scope: Callable[[str], str]
    recall_memory_func: Callable
    format_memory_for_llm: Callable
    recall_profile_for_user_func: Callable
    format_profile_for_llm: Callable
    dm_guidelines: Any
    dm_guidelines_source: str
    system_prompt_base: str

    # llm
    client: Any
    openai_model: str

    # episode logging
    enable_episode_logging: bool
    episode_log_filters: set[str]
    insert_episode_log_sync: Callable
    recent_context_limit: int


@dataclass(frozen=True)
class RuntimeBootDeps:
    welcome_panel_factory: Callable
    allowed_channel_ids: set[int]
    bootstrap_channel_reset_all: bool
    reset_all_backfill_done_func: Callable
    backfill_channel_func: Callable
    maintenance_loop_func: Callable
    announcement_enabled: bool
    announcement_loop_func: Callable
