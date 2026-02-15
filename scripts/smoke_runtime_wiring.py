from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace

class _DummyCompletions:
    def create(self, *args, **kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="[]"))]
        )


class _DummyClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=_DummyCompletions())


def _classify_context(**kwargs):
    return {
        "caller_type": "member",
        "surface": "public_channel",
        "sensitivity_policy_id": "policy:member_default",
        "allowed_capabilities": ["anonymized_patterns_only"],
        "channel_policy_group": "member",
        "channel_id": kwargs.get("channel_id"),
        "guild_id": kwargs.get("guild_id"),
    }


async def _noop_async(*args, **kwargs):
    return None


def _noop(*args, **kwargs):
    return None


class _DummyAnnouncementService:
    async def run_tick(self, bot):
        return None


async def _remember_event(*args, **kwargs):
    return {"id": 1}


async def _recall_memory(*args, **kwargs):
    return ([], [])


async def _get_recent_context(*args, **kwargs):
    return ("", 0)


def _select_active_controller_config(*args, **kwargs):
    return {"id": 1, "persona": "guide", "scope": "global"}


def _try_import_or_skip(module_name: str, pip_name: str | None = None) -> bool:
    try:
        importlib.import_module(module_name)
        return True
    except ModuleNotFoundError:
        install_name = pip_name or module_name
        print(
            f"Smoke wiring check skipped: missing dependency '{module_name}'. "
            f"Install requirements and retry (e.g. `pip install {install_name}` "
            f"or `pip install -r requirements.txt`)."
        )
        return False


def _main() -> int:
    if not _try_import_or_skip("discord", "discord.py"):
        return 0

    import discord
    from discord.ext import commands
    from misc.runtime_wiring import wire_bot_runtime

    intents = discord.Intents.none()
    bot = commands.Bot(command_prefix="!", intents=intents)
    db_lock = asyncio.Lock()
    db_conn = object()

    wire_bot_runtime(
        bot,
        allowed_channel_ids={123456789012345678},
        user_is_owner=lambda user: True,
        fetch_episode_logs_sync=lambda conn, limit: [],
        update_latest_dm_draft_feedback_sync=lambda conn, user_id, outcome, note=None: None,
        update_latest_dm_draft_evaluation_sync=lambda conn, user_id, rubric_scores, failure_tags=None, note=None: None,
        list_schema_migrations_sync=lambda conn, limit: [],
        stage_at_least=lambda stage: True,
        memory_stage="M3",
        memory_stage_rank=3,
        memory_review_mode="capture_only",
        auto_capture=False,
        auto_summary=False,
        topic_suggest=False,
        topic_min_conf=0.85,
        topic_allowlist=["epoxy_bot", "community"],
        db_lock=db_lock,
        db_conn=db_conn,
        topic_counts_sync=lambda conn, limit: [],
        list_known_topics_sync=lambda conn, limit: [],
        get_topic_summary_sync=lambda conn, topic_id: None,
        summarize_topic_func=_noop_async,
        send_chunked=_noop_async,
        normalize_tags=lambda tags: tags,
        remember_event_func=_remember_event,
        infer_scope=lambda prompt: "auto",
        recall_memory_func=_recall_memory,
        format_memory_for_llm=lambda events, summaries, max_chars=1700: "",
        resolve_policy_bundle_sync=lambda conn, sensitivity_policy_id, caller_type, surface, limit=20: {
            "policies": [],
            "policy_ids": [],
            "enforcement": {},
        },
        format_policy_directive_func=lambda policy_bundle, max_chars=550: "",
        apply_policy_enforcement_func=lambda reply, **kwargs: (reply, []),
        subject_user_tag=lambda user_id: f"user:{user_id}",
        subject_person_tag=lambda person_id: f"person:{person_id}",
        get_or_create_person_sync=lambda conn, **kwargs: 1,
        list_candidate_memories_sync=lambda conn, limit=20, offset=0: [],
        approve_memory_sync=lambda conn, **kwargs: {"id": int(kwargs.get("memory_id", 0)), "lifecycle": "active"},
        reject_memory_sync=lambda conn, **kwargs: {"id": int(kwargs.get("memory_id", 0)), "lifecycle": "deprecated"},
        parse_channel_id_token=lambda token: None,
        parse_duration_to_minutes=lambda token: None,
        fetch_messages_since_sync=lambda conn, channel_id, since_iso, limit: [],
        fetch_latest_messages_sync=lambda conn, channel_id, limit: [],
        fetch_memory_events_since_sync=lambda conn, since_iso, limit: [],
        fetch_latest_memory_events_sync=lambda conn, limit: [],
        fetch_recent_context_sync=lambda conn, channel_id, before_id, limit: [],
        format_recent_context=lambda rows, max_chars, max_line_chars: "",
        format_memory_events_window=lambda rows, max_chars=12000: "",
        extract_json_array=lambda text: [],
        is_valid_topic_id=lambda topic_id: True,
        set_memory_origin_func=_noop_async,
        client=_DummyClient(),
        openai_model="gpt-5.1",
        max_line_chars=600,
        welcome_channel_id=123456789012345678,
        welcome_panel_factory=lambda: discord.ui.View(),
        lfg_source_channel_id=123456789012345678,
        lfg_public_channel_id=123456789012345678,
        paddock_lounge_channel_id=123456789012345678,
        lfg_role_name="Driving Pings",
        user_is_member=lambda member: True,
        bootstrap_channel_reset_all=False,
        bootstrap_channel_reset=False,
        bootstrap_backfill_capture=False,
        reset_all_backfill_done_func=_noop_async,
        reset_backfill_done_func=_noop_async,
        is_backfill_done_func=lambda channel_id: False,
        mark_backfill_done_func=_noop_async,
        backfill_limit=50,
        backfill_pause_every=100,
        backfill_pause_seconds=0.1,
        log_message_func=_noop_async,
        maintenance_loop_func=_noop_async,
        get_recent_channel_context_func=_get_recent_context,
        fetch_last_messages_by_author_sync=lambda conn, channel_id, before_id, like, limit=1: [],
        build_context_pack=lambda: "",
        classify_context=_classify_context,
        founder_user_ids=set(),
        channel_policy_groups={"leadership": set(), "staff": set(), "member": set(), "public": set()},
        recall_profile_for_identity_func=lambda person_id, user_id, limit=6: [],
        format_profile_for_llm=lambda user_blocks, max_chars=900: "",
        dm_guidelines=SimpleNamespace(version="dm_guidelines_test", to_prompt_block=lambda: "DM Guidelines"),
        dm_guidelines_source="file",
        get_or_create_context_profile_sync=lambda conn, payload: 1,
        resolve_person_id_sync=lambda conn, platform, external_id: 1,
        canonical_person_id_sync=lambda conn, person_id: int(person_id),
        upsert_user_profile_last_seen_sync=_noop,
        select_active_controller_config_sync=_select_active_controller_config,
        utc_iso=lambda dt=None: "2026-01-01T00:00:00+00:00",
        system_prompt_base="You are Epoxy.",
        enable_episode_logging=False,
        episode_log_filters={"context:public"},
        insert_episode_log_sync=_noop,
        recent_context_limit=40,
        announcement_enabled=True,
        announcement_service=_DummyAnnouncementService(),
        announcement_loop_func=_noop_async,
    )

    expected_commands = {
        "episodelogs",
        "dbmigrations",
        "dmfeedback",
        "dmeval",
        "announce.status",
        "announce.answers",
        "announce.answer",
        "announce.generate",
        "announce.override",
        "announce.clear_override",
        "announce.approve",
        "announce.unapprove",
        "announce.done",
        "announce.undo_done",
        "announce.post_now",
        "memstage",
        "topics",
        "remember",
        "recall",
        "topic",
        "summarize",
        "profile",
        "memlast",
        "memfind",
        "memreview",
        "memapprove",
        "memreject",
        "mine",
        "ctxpeek",
        "topicsuggest",
        "setup_welcome_panel",
        "lfg",
    }
    existing_commands = set(bot.all_commands.keys())
    missing = sorted(expected_commands - existing_commands)
    if missing:
        raise RuntimeError(f"Missing expected commands: {missing}")

    if "on_ready" not in bot.extra_events or "on_message" not in bot.extra_events:
        raise RuntimeError("Runtime events were not registered")

    print("Smoke wiring check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
