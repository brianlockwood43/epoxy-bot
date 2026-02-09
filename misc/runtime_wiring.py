from __future__ import annotations

from ingestion.service import backfill_channel as backfill_channel_service
from ingestion.service import maybe_auto_capture as maybe_auto_capture_service
from misc.commands.command_deps import CommandDeps
from misc.commands.command_deps import CommandGates
from misc.commands.commands_announcements import register as register_announcements
from misc.commands.commands_community import register as register_community
from misc.commands.commands_memory import register as register_memory
from misc.commands.commands_mining import register as register_mining
from misc.commands.commands_owner import register as register_owner
from misc.runtime_deps import RuntimeBootDeps
from misc.runtime_deps import RuntimeDeps
from misc.events_runtime import register_runtime_events


def wire_bot_runtime(
    bot,
    *,
    allowed_channel_ids: set[int],
    user_is_owner,
    fetch_episode_logs_sync,
    update_latest_dm_draft_feedback_sync,
    update_latest_dm_draft_evaluation_sync,
    list_schema_migrations_sync,
    stage_at_least,
    memory_stage: str,
    memory_stage_rank: int,
    auto_capture: bool,
    auto_summary: bool,
    topic_suggest: bool,
    topic_min_conf: float,
    topic_allowlist: list[str],
    db_lock,
    db_conn,
    topic_counts_sync,
    list_known_topics_sync,
    get_topic_summary_sync,
    summarize_topic_func,
    send_chunked,
    normalize_tags,
    remember_event_func,
    infer_scope,
    recall_memory_func,
    format_memory_for_llm,
    subject_user_tag,
    parse_channel_id_token,
    parse_duration_to_minutes,
    fetch_messages_since_sync,
    fetch_latest_messages_sync,
    fetch_memory_events_since_sync,
    fetch_latest_memory_events_sync,
    fetch_recent_context_sync,
    format_recent_context,
    format_memory_events_window,
    extract_json_array,
    is_valid_topic_id,
    set_memory_origin_func,
    client,
    openai_model: str,
    max_line_chars: int,
    welcome_channel_id: int,
    welcome_panel_factory,
    lfg_source_channel_id: int,
    lfg_public_channel_id: int,
    paddock_lounge_channel_id: int,
    lfg_role_name: str,
    user_is_member,
    bootstrap_channel_reset_all: bool,
    bootstrap_channel_reset: bool,
    bootstrap_backfill_capture: bool,
    reset_all_backfill_done_func,
    reset_backfill_done_func,
    is_backfill_done_func,
    mark_backfill_done_func,
    backfill_limit: int,
    backfill_pause_every: int,
    backfill_pause_seconds: float,
    log_message_func,
    maintenance_loop_func,
    get_recent_channel_context_func,
    fetch_last_messages_by_author_sync,
    build_context_pack,
    classify_context,
    founder_user_ids: set[int],
    channel_policy_groups: dict,
    recall_profile_for_user_func,
    format_profile_for_llm,
    dm_guidelines,
    dm_guidelines_source: str,
    get_or_create_context_profile_sync,
    upsert_user_profile_last_seen_sync,
    select_active_controller_config_sync,
    utc_iso,
    system_prompt_base: str,
    enable_episode_logging: bool,
    episode_log_filters: set[str],
    insert_episode_log_sync,
    recent_context_limit: int,
    announcement_enabled: bool,
    announcement_service,
    announcement_loop_func,
) -> None:
    def in_allowed_channel(ctx) -> bool:
        try:
            return int(ctx.channel.id) in allowed_channel_ids
        except Exception:
            return False

    command_deps = CommandDeps(
        db_lock=db_lock,
        db_conn=db_conn,
        send_chunked=send_chunked,
        client=client,
        openai_model=openai_model,
        max_line_chars=max_line_chars,
        stage_at_least=stage_at_least,
        memory_stage=memory_stage,
        memory_stage_rank=memory_stage_rank,
        auto_capture=auto_capture,
        auto_summary=auto_summary,
        topic_suggest=topic_suggest,
        topic_min_conf=topic_min_conf,
        topic_allowlist=topic_allowlist,
        fetch_episode_logs_sync=fetch_episode_logs_sync,
        update_latest_dm_draft_feedback_sync=update_latest_dm_draft_feedback_sync,
        update_latest_dm_draft_evaluation_sync=update_latest_dm_draft_evaluation_sync,
        list_schema_migrations_sync=list_schema_migrations_sync,
        topic_counts_sync=topic_counts_sync,
        list_known_topics_sync=list_known_topics_sync,
        get_topic_summary_sync=get_topic_summary_sync,
        summarize_topic_func=summarize_topic_func,
        normalize_tags=normalize_tags,
        remember_event_func=remember_event_func,
        infer_scope=infer_scope,
        recall_memory_func=recall_memory_func,
        format_memory_for_llm=format_memory_for_llm,
        subject_user_tag=subject_user_tag,
        parse_channel_id_token=parse_channel_id_token,
        parse_duration_to_minutes=parse_duration_to_minutes,
        fetch_messages_since_sync=fetch_messages_since_sync,
        fetch_latest_messages_sync=fetch_latest_messages_sync,
        fetch_memory_events_since_sync=fetch_memory_events_since_sync,
        fetch_latest_memory_events_sync=fetch_latest_memory_events_sync,
        fetch_recent_context_sync=fetch_recent_context_sync,
        format_recent_context=format_recent_context,
        format_memory_events_window=format_memory_events_window,
        extract_json_array=extract_json_array,
        is_valid_topic_id=is_valid_topic_id,
        set_memory_origin_func=set_memory_origin_func,
        welcome_channel_id=welcome_channel_id,
        welcome_panel_factory=welcome_panel_factory,
        lfg_source_channel_id=lfg_source_channel_id,
        lfg_public_channel_id=lfg_public_channel_id,
        paddock_lounge_channel_id=paddock_lounge_channel_id,
        lfg_role_name=lfg_role_name,
        announcement_service=announcement_service,
    )
    command_gates = CommandGates(
        in_allowed_channel=in_allowed_channel,
        allowed_channel_ids=allowed_channel_ids,
        user_is_owner=user_is_owner,
        user_is_member=user_is_member,
    )

    register_owner(
        bot,
        deps=command_deps,
        gates=command_gates,
    )

    register_memory(
        bot,
        deps=command_deps,
        gates=command_gates,
    )

    register_mining(
        bot,
        deps=command_deps,
        gates=command_gates,
    )

    register_community(
        bot,
        deps=command_deps,
        gates=command_gates,
    )

    if announcement_service is not None:
        register_announcements(
            bot,
            deps=command_deps,
            gates=command_gates,
        )

    async def backfill_channel(channel):
        return await backfill_channel_service(
            channel,
            allowed_channel_ids=allowed_channel_ids,
            bootstrap_channel_reset=bootstrap_channel_reset,
            reset_backfill_done_func=reset_backfill_done_func,
            is_backfill_done_func=is_backfill_done_func,
            backfill_limit=backfill_limit,
            bootstrap_backfill_capture=bootstrap_backfill_capture,
            stage_at_least=stage_at_least,
            log_message_func=log_message_func,
            maybe_auto_capture_func=maybe_auto_capture,
            backfill_pause_every=backfill_pause_every,
            backfill_pause_seconds=backfill_pause_seconds,
            bot_user=bot.user,
            mark_backfill_done_func=mark_backfill_done_func,
        )

    async def maybe_auto_capture(message):
        return await maybe_auto_capture_service(
            message,
            auto_capture=auto_capture,
            stage_at_least=stage_at_least,
            remember_event_func=remember_event_func,
        )

    register_runtime_events(
        bot,
        deps=RuntimeDeps(
            db_lock=db_lock,
            db_conn=db_conn,
            send_chunked=send_chunked,
            user_is_owner=user_is_owner,
            stage_at_least=stage_at_least,
            memory_stage=memory_stage,
            utc_iso=utc_iso,
            log_message_func=log_message_func,
            maybe_auto_capture_func=maybe_auto_capture,
            build_context_pack=build_context_pack,
            classify_context=classify_context,
            founder_user_ids=founder_user_ids,
            channel_policy_groups=channel_policy_groups,
            get_recent_channel_context_func=get_recent_channel_context_func,
            fetch_last_messages_by_author_sync=fetch_last_messages_by_author_sync,
            get_or_create_context_profile_sync=get_or_create_context_profile_sync,
            upsert_user_profile_last_seen_sync=upsert_user_profile_last_seen_sync,
            select_active_controller_config_sync=select_active_controller_config_sync,
            infer_scope=infer_scope,
            recall_memory_func=recall_memory_func,
            format_memory_for_llm=format_memory_for_llm,
            recall_profile_for_user_func=recall_profile_for_user_func,
            format_profile_for_llm=format_profile_for_llm,
            dm_guidelines=dm_guidelines,
            dm_guidelines_source=dm_guidelines_source,
            system_prompt_base=system_prompt_base,
            client=client,
            openai_model=openai_model,
            enable_episode_logging=enable_episode_logging,
            episode_log_filters=episode_log_filters,
            insert_episode_log_sync=insert_episode_log_sync,
            recent_context_limit=recent_context_limit,
        ),
        boot=RuntimeBootDeps(
            welcome_panel_factory=welcome_panel_factory,
            allowed_channel_ids=allowed_channel_ids,
            bootstrap_channel_reset_all=bootstrap_channel_reset_all,
            reset_all_backfill_done_func=reset_all_backfill_done_func,
            backfill_channel_func=backfill_channel,
            maintenance_loop_func=maintenance_loop_func,
            announcement_enabled=announcement_enabled,
            announcement_loop_func=announcement_loop_func,
        ),
    )
