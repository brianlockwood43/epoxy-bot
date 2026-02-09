from __future__ import annotations

import asyncio
import hashlib
import json
import re

import discord
from controller.dm_episode_artifact import build_dm_episode_artifact
from controller.dm_draft_parser import parse_dm_draft_request
from controller.dm_draft_service import DmDraftRun
from controller.dm_draft_service import apply_best_effort_assumptions
from controller.dm_draft_service import build_collab_questions
from controller.dm_draft_service import build_dm_prompt_messages
from controller.dm_draft_service import compute_recall_coverage
from controller.dm_draft_service import compute_recall_provenance_counts
from controller.dm_draft_service import evaluate_collab_blocking
from controller.dm_draft_service import format_dm_result_for_discord
from controller.dm_draft_service import parse_dm_result_from_model
from controller.dm_draft_service import select_mode
from controller.episode_log_filters import should_log_episode
from controller.prompt_assembly import build_chat_messages
from discord.ext import commands
from memory.runtime_recall import maybe_build_memory_pack
from misc.discord_gates import message_in_allowed_channels
from misc.mention_routes import classify_mention_route
from misc.mention_routes import extract_dm_mode_payload
from misc.runtime_deps import RuntimeBootDeps
from misc.runtime_deps import RuntimeDeps

DM_DRAFT_VERSION = "1.1"


def _dedupe_recall_count(events: list[dict], summaries: list[dict], profile_events: list[dict]) -> int:
    seen: set[tuple[str, int]] = set()
    for event in events:
        if event.get("id") is not None:
            seen.add(("event", int(event["id"])))
    for summary in summaries:
        if summary.get("id") is not None:
            seen.add(("summary", int(summary["id"])))
    for event in profile_events:
        if event.get("id") is not None:
            seen.add(("profile", int(event["id"])))
    return len(seen)


def _best_display_name_for_user(user_obj) -> str | None:
    for attr in ("display_name", "global_name", "name"):
        value = getattr(user_obj, attr, None)
        if value:
            return str(value)
    return None


def _slug_entity_token(text: str) -> str:
    raw = str(text or "").strip().lower()
    if not raw:
        return "unknown"
    raw = re.sub(r"<@!?\d+>", "", raw)
    raw = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    return raw or "unknown"


def _make_target_entity_key(
    *,
    target_user_id: int | None,
    target_type: str,
    target_display_name: str | None,
    target_text: str,
) -> str:
    if target_user_id is not None:
        return f"discord:{int(target_user_id)}"
    prefix = str(target_type or "unknown").strip().lower()
    if prefix not in {"member", "staff", "external", "self", "unknown"}:
        prefix = "unknown"
    slug = _slug_entity_token(target_display_name or target_text)
    return f"{prefix}:{slug}"


def _normalize_dm_field_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _normalize_dm_field_list(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values or []:
        clean = _normalize_dm_field_text(value)
        if clean:
            out.append(clean)
    return out


def _build_prompt_fingerprint(
    *,
    target: str | None,
    target_user_id: int | None,
    target_entity_key: str | None,
    objective: str,
    situation_context: str,
    my_goals: list[str],
    non_negotiables: list[str],
    tone: str,
    mode_used: str,
) -> str:
    normalized_payload = {
        "target": _normalize_dm_field_text(target),
        "target_user_id": int(target_user_id) if target_user_id is not None else None,
        "target_entity_key": _normalize_dm_field_text(target_entity_key),
        "objective": _normalize_dm_field_text(objective),
        "situation_context": _normalize_dm_field_text(situation_context),
        "my_goals": _normalize_dm_field_list(my_goals),
        "non_negotiables": _normalize_dm_field_list(non_negotiables),
        "tone": _normalize_dm_field_text(tone).lower(),
        "mode_used": _normalize_dm_field_text(mode_used).lower(),
    }
    raw = json.dumps(normalized_payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _resolve_dm_target_fields(*, req, message: discord.Message, deps: RuntimeDeps) -> dict[str, object | None]:
    target_text = str(req.target or "").strip()
    target_user_id = req.target_user_id
    target_display_name = target_text or None
    target_type = "unknown"
    target_confidence: float | None = None

    explicit_type = re.match(r"^\s*(member|staff|external|self|unknown)\s*:\s*(.+)$", target_text, flags=re.I)
    if explicit_type and target_user_id is None:
        target_type = explicit_type.group(1).strip().lower()
        explicit_name = explicit_type.group(2).strip()
        if explicit_name:
            target_display_name = explicit_name
        if target_type == "self":
            target_user_id = int(message.author.id)
            target_display_name = _best_display_name_for_user(message.author) or target_display_name

    # Common self aliases: infer the author's ID when explicitly requested as self.
    if target_user_id is None and target_text.lower() in {"me", "myself", "self"}:
        target_user_id = int(message.author.id)
        target_type = "self"
        target_confidence = 0.85
        target_display_name = _best_display_name_for_user(message.author) or target_display_name

    if target_user_id is not None:
        author_id = int(message.author.id)
        if target_user_id == author_id:
            target_type = "self"
            if target_display_name is None:
                target_display_name = _best_display_name_for_user(message.author) or f"<@{author_id}>"
        elif int(target_user_id) in deps.founder_user_ids:
            target_type = "staff"
        else:
            member_obj = None
            try:
                if message.guild is not None:
                    member_obj = message.guild.get_member(int(target_user_id))
            except Exception:
                member_obj = None

            if member_obj is not None:
                target_display_name = _best_display_name_for_user(member_obj) or target_display_name
                try:
                    target_type = "staff" if deps.user_is_owner(member_obj) else "member"
                except Exception:
                    target_type = "member"
            elif message.guild is not None:
                target_type = "external"
                target_confidence = 0.75
            else:
                target_type = "unknown"
                target_confidence = 0.45

        if target_display_name is None:
            target_display_name = f"<@{int(target_user_id)}>"
    elif target_text:
        target_type = "unknown"
        target_confidence = 0.35

    return {
        "target_user_id": int(target_user_id) if target_user_id is not None else None,
        "target_display_name": target_display_name,
        "target_type": target_type,
        "target_confidence": target_confidence,
        "target_entity_key": _make_target_entity_key(
            target_user_id=(int(target_user_id) if target_user_id is not None else None),
            target_type=target_type,
            target_display_name=target_display_name,
            target_text=target_text,
        ),
    }


def register_runtime_events(
    bot: commands.Bot,
    *,
    deps: RuntimeDeps,
    boot: RuntimeBootDeps,
) -> None:
    @bot.event
    async def on_ready():
        if not getattr(bot, "_welcome_panel_registered", False):
            bot.add_view(boot.welcome_panel_factory())
            bot._welcome_panel_registered = True

        print(f"Epoxy is online as {bot.user}")
        if boot.bootstrap_channel_reset_all:
            await boot.reset_all_backfill_done_func()
            print("[Backfill] Reset ALL backfill_done flags (bootstrap)")

        for channel_id in boot.allowed_channel_ids:
            channel = bot.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await bot.fetch_channel(channel_id)
                except Exception as e:
                    print(f"[Backfill] Could not fetch channel {channel_id}: {e}")
                    continue
            await boot.backfill_channel_func(channel)

        if deps.stage_at_least("M1") and not getattr(bot, "_maintenance_task", None):
            bot._maintenance_task = asyncio.create_task(boot.maintenance_loop_func())
            print(f"[Memory] maintenance loop started (stage={deps.memory_stage})")

        if boot.announcement_enabled and not getattr(bot, "_announcement_task", None):
            bot._announcement_task = asyncio.create_task(boot.announcement_loop_func())
            print("[Announcements] automation loop started")

    @bot.event
    async def on_message(message: discord.Message):
        if not message_in_allowed_channels(message, boot.allowed_channel_ids):
            return

        if message.author.bot:
            if bot.user and message.author.id == bot.user.id:
                await deps.log_message_func(message)
            return

        await deps.log_message_func(message)
        await deps.maybe_auto_capture_func(message)

        if (message.content or "").lstrip().startswith("!"):
            await bot.process_commands(message)
            return

        if bot.user and bot.user in message.mentions:
            prompt = re.sub(rf"<@!?\s*{bot.user.id}\s*>", "", message.content or "").strip()

            if not prompt:
                await message.channel.send("Yep?")
                return

            try:
                max_msg_content = 1900

                recent_context, ctx_rows = await deps.get_recent_channel_context_func(message.channel.id, message.id)
                if len(recent_context) > max_msg_content:
                    recent_context = recent_context[-max_msg_content:]

                anchor_block = ""
                async with deps.db_lock:
                    bot_rows = await asyncio.to_thread(
                        deps.fetch_last_messages_by_author_sync,
                        deps.db_conn,
                        message.channel.id,
                        message.id,
                        "%Epoxy%",
                        1,
                    )
                    user_rows = await asyncio.to_thread(
                        deps.fetch_last_messages_by_author_sync,
                        deps.db_conn,
                        message.channel.id,
                        message.id,
                        f"%{message.author.name}%",
                        1,
                    )

                def _fmt_anchor(rows, label: str) -> str:
                    if not rows:
                        return ""
                    ts, who, txt = rows[0]
                    clean = " ".join((txt or "").split())
                    if len(clean) > 420:
                        clean = clean[:419] + "..."
                    return f"{label}: [{ts}] {who}: {clean}"

                parts = []
                b = _fmt_anchor(bot_rows, "LAST EPOXY MESSAGE")
                u = _fmt_anchor(user_rows, "LAST MESSAGE FROM THIS USER")
                if b:
                    parts.append(b)
                if u:
                    parts.append(u)
                if parts:
                    anchor_block = (
                        "Reply anchors (use these to interpret short replies like 'yes', 'fun vibe', 'agree'):\n"
                        + "\n".join(parts)
                    )
                    if len(anchor_block) > max_msg_content:
                        anchor_block = anchor_block[-max_msg_content:]

                context_pack = deps.build_context_pack()[:max_msg_content]
                safe_prompt = prompt[:max_msg_content]
                runtime_ctx = deps.classify_context(
                    author_id=int(message.author.id),
                    is_dm=(message.guild is None),
                    channel_id=int(message.channel.id) if hasattr(message.channel, "id") else None,
                    guild_id=(int(message.guild.id) if message.guild else None),
                    founder_user_ids=deps.founder_user_ids,
                    channel_groups=deps.channel_policy_groups,
                )

                async with deps.db_lock:
                    person_origin = f"discord:{int(message.guild.id)}" if message.guild else "discord:dm"
                    actor_person_id = await asyncio.to_thread(
                        deps.get_or_create_person_sync,
                        deps.db_conn,
                        platform="discord",
                        external_id=str(int(message.author.id)),
                        origin=person_origin,
                        label="discord_user_id",
                    )
                    actor_person_id = await asyncio.to_thread(
                        deps.canonical_person_id_sync,
                        deps.db_conn,
                        int(actor_person_id),
                    )
                    context_profile_id = await asyncio.to_thread(
                        deps.get_or_create_context_profile_sync,
                        deps.db_conn,
                        {
                            "caller_type": runtime_ctx["caller_type"],
                            "surface": runtime_ctx["surface"],
                            "channel_id": runtime_ctx.get("channel_id"),
                            "guild_id": runtime_ctx.get("guild_id"),
                            "sensitivity_policy_id": runtime_ctx["sensitivity_policy_id"],
                            "allowed_capabilities": runtime_ctx["allowed_capabilities"],
                        },
                    )
                    await asyncio.to_thread(
                        deps.upsert_user_profile_last_seen_sync,
                        deps.db_conn,
                        int(actor_person_id),
                        deps.utc_iso(),
                    )
                    controller_cfg = await asyncio.to_thread(
                        deps.select_active_controller_config_sync,
                        deps.db_conn,
                        caller_type=runtime_ctx["caller_type"],
                        context_profile_id=int(context_profile_id),
                        user_id=int(message.author.id),
                        person_id=int(actor_person_id),
                    )

                route = classify_mention_route(safe_prompt)

                if route == "dm_draft":
                    if not deps.user_is_owner(message.author):
                        await message.channel.send("DM draft mode is owner-only.")
                        return

                    dm_payload = extract_dm_mode_payload(safe_prompt) or ""
                    parsed = parse_dm_draft_request(dm_payload)
                    req = parsed.request
                    target_fields = _resolve_dm_target_fields(req=req, message=message, deps=deps)
                    req.target_user_id = int(target_fields["target_user_id"]) if target_fields["target_user_id"] is not None else None
                    target_person_id: int | None = None
                    if req.target_user_id is not None:
                        target_origin = f"discord:{int(message.guild.id)}" if message.guild else "discord:dm"
                        async with deps.db_lock:
                            target_person_id = await asyncio.to_thread(
                                deps.get_or_create_person_sync,
                                deps.db_conn,
                                platform="discord",
                                external_id=str(int(req.target_user_id)),
                                origin=target_origin,
                                label="discord_user_id",
                            )
                            target_person_id = await asyncio.to_thread(
                                deps.canonical_person_id_sync,
                                deps.db_conn,
                                int(target_person_id),
                            )
                    target_fields["target_person_id"] = int(target_person_id) if target_person_id is not None else None

                    mode_requested = req.mode
                    mode, mode_inferred = select_mode(mode_requested=mode_requested, prompt_text=dm_payload)
                    prompt_fingerprint = _build_prompt_fingerprint(
                        target=req.target,
                        target_user_id=req.target_user_id,
                        target_entity_key=str(target_fields.get("target_entity_key") or ""),
                        objective=req.objective,
                        situation_context=req.situation_context,
                        my_goals=list(req.my_goals),
                        non_negotiables=list(req.non_negotiables),
                        tone=req.tone,
                        mode_used=mode,
                    )
                    dm_parse_payload = {
                        "target": req.target,
                        "target_user_id": target_fields["target_user_id"],
                        "target_person_id": target_fields["target_person_id"],
                        "target_display_name": target_fields["target_display_name"],
                        "target_type": target_fields["target_type"],
                        "target_confidence": target_fields["target_confidence"],
                        "target_entity_key": target_fields["target_entity_key"],
                        "objective": req.objective,
                        "situation_context": req.situation_context,
                        "my_goals": list(req.my_goals),
                        "non_negotiables": list(req.non_negotiables),
                        "tone": req.tone,
                        "mode": req.mode,
                        "mode_requested": mode_requested,
                        "mode_inferred": mode_inferred,
                        "mode_used": mode,
                        "dm_guidelines_version": deps.dm_guidelines.version,
                        "dm_guidelines_source": deps.dm_guidelines_source,
                        "draft_version": DM_DRAFT_VERSION,
                        "prompt_fingerprint": prompt_fingerprint,
                        "parse_quality": parsed.parse_quality,
                        "missing_fields": list(parsed.missing_fields),
                        "used_structured_parse": bool(parsed.used_structured_parse),
                    }
                    blocking_collab, critical_missing_fields, blocking_reason = evaluate_collab_blocking(
                        mode=mode,
                        req=req,
                        missing_fields=parsed.missing_fields,
                        prompt_text=dm_payload,
                    )
                    clarifying_questions = build_collab_questions(
                        critical_missing_fields if blocking_collab else parsed.missing_fields
                    ) if mode == "collab" else []

                    if blocking_collab:
                        lines = [
                            "Collab mode needs a couple of critical clarifications before I draft.",
                            f"Blocking reason: {blocking_reason}",
                        ]
                        if critical_missing_fields:
                            lines.append(f"Critical missing fields: {', '.join(critical_missing_fields)}")
                        if clarifying_questions:
                            lines.append("")
                            lines.append("Please answer:")
                            for q in clarifying_questions[:2]:
                                lines.append(f"- {q}")
                        reply = "\n".join(lines).strip()
                        await deps.send_chunked(message.channel, reply)

                        if deps.enable_episode_logging and should_log_episode(deps.episode_log_filters, runtime_ctx):
                            dm_result_payload = {
                                "status": "blocked_collab",
                                "blocking_collab": True,
                                "dm_guidelines_version": deps.dm_guidelines.version,
                                "dm_guidelines_source": deps.dm_guidelines_source,
                                "draft_version": DM_DRAFT_VERSION,
                                "draft_variant_id": None,
                                "prompt_fingerprint": prompt_fingerprint,
                                "clarifying_questions": list(clarifying_questions[:2]),
                                "critical_missing_fields": list(critical_missing_fields),
                                "blocking_reason": blocking_reason,
                            }
                            dm_artifact = build_dm_episode_artifact(
                                parse_payload=dm_parse_payload,
                                result_payload=dm_result_payload,
                            )
                            episode_payload = {
                                "timestamp_utc": deps.utc_iso(),
                                "context_profile_id": int(context_profile_id),
                                "user_id": int(message.author.id),
                                "person_id": int(actor_person_id),
                                "controller_config_id": int(controller_cfg.get("id")) if controller_cfg.get("id") is not None else None,
                                "input_excerpt": safe_prompt[:500],
                                "assistant_output_excerpt": reply[:800],
                                "retrieved_memory_ids": [],
                                "tags": [
                                    "mode:dm_draft",
                                    "flow:blocking_collab",
                                    f"surface:{runtime_ctx['surface']}",
                                    f"caller:{runtime_ctx['caller_type']}",
                                    f"group:{runtime_ctx['channel_policy_group']}",
                                    f"actor_person:{int(actor_person_id)}",
                                    f"target_user:{target_fields['target_user_id'] if target_fields['target_user_id'] is not None else 'none'}",
                                    f"target_person:{target_fields['target_person_id'] if target_fields['target_person_id'] is not None else 'none'}",
                                    f"target_type:{target_fields['target_type']}",
                                    f"target_entity:{target_fields['target_entity_key']}",
                                    f"guideline_pack:{deps.dm_guidelines.version}",
                                ],
                                "implicit_signals": {
                                    "ctx_rows": int(ctx_rows),
                                    "memory_hits": 0,
                                    "parse_quality": parsed.parse_quality,
                                    "missing_fields_count": len(parsed.missing_fields),
                                    "mode_requested": mode_requested,
                                    "mode_inferred": mode_inferred,
                                    "mode_used": mode,
                                    "dm_guidelines_version": deps.dm_guidelines.version,
                                    "dm_guidelines_source": deps.dm_guidelines_source,
                                    "blocking_collab": True,
                                    "critical_missing_fields": list(critical_missing_fields),
                                    "blocking_reason": blocking_reason,
                                    "draft_version": DM_DRAFT_VERSION,
                                    "draft_variant_id": None,
                                    "prompt_fingerprint": prompt_fingerprint,
                                    "target_user_id": target_fields["target_user_id"],
                                    "target_person_id": target_fields["target_person_id"],
                                    "target_display_name": target_fields["target_display_name"],
                                    "target_type": target_fields["target_type"],
                                    "target_confidence": target_fields["target_confidence"],
                                    "target_entity_key": target_fields["target_entity_key"],
                                    **dm_artifact,
                                },
                                "target_user_id": target_fields["target_user_id"],
                                "target_person_id": target_fields["target_person_id"],
                                "target_display_name": target_fields["target_display_name"],
                                "target_type": target_fields["target_type"],
                                "target_confidence": target_fields["target_confidence"],
                                "target_entity_key": target_fields["target_entity_key"],
                                "mode_requested": mode_requested,
                                "mode_inferred": mode_inferred,
                                "mode_used": mode,
                                "dm_guidelines_version": deps.dm_guidelines.version,
                                "dm_guidelines_source": deps.dm_guidelines_source,
                                "blocking_collab": True,
                                "critical_missing_fields": list(critical_missing_fields),
                                "blocking_reason": blocking_reason,
                                "draft_version": DM_DRAFT_VERSION,
                                "draft_variant_id": None,
                                "prompt_fingerprint": prompt_fingerprint,
                                "guild_id": int(message.guild.id) if message.guild else None,
                                "channel_id": int(message.channel.id) if hasattr(message.channel, "id") else None,
                                "message_id": int(message.id),
                            }
                            async with deps.db_lock:
                                await asyncio.to_thread(deps.insert_episode_log_sync, deps.db_conn, episode_payload)
                        return

                    req, assumptions_used = apply_best_effort_assumptions(req, parsed.missing_fields)
                    prompt_fingerprint = _build_prompt_fingerprint(
                        target=req.target,
                        target_user_id=req.target_user_id,
                        target_entity_key=str(target_fields.get("target_entity_key") or ""),
                        objective=req.objective,
                        situation_context=req.situation_context,
                        my_goals=list(req.my_goals),
                        non_negotiables=list(req.non_negotiables),
                        tone=req.tone,
                        mode_used=mode,
                    )
                    dm_parse_payload["prompt_fingerprint"] = prompt_fingerprint

                    recall_query_parts = [req.objective, req.situation_context]
                    recall_query_parts.extend(req.my_goals)
                    recall_query_parts.extend(req.non_negotiables)
                    recall_query = " ".join(part.strip() for part in recall_query_parts if str(part).strip()) or dm_payload
                    recall_scope = deps.infer_scope(recall_query) if deps.stage_at_least("M2") else "auto"
                    events, summaries = await deps.recall_memory_func(recall_query, scope=recall_scope)
                    retrieved_memory_ids = [int(e["id"]) for e in events if e.get("id") is not None]
                    memory_pack = deps.format_memory_for_llm(events, summaries, max_chars=max_msg_content)[:max_msg_content]

                    profile_events: list[dict] = []
                    profile_pack = ""
                    if req.target_user_id is not None or target_fields["target_person_id"] is not None:
                        profile_events = await deps.recall_profile_for_identity_func(
                            int(target_fields["target_person_id"]) if target_fields["target_person_id"] is not None else None,
                            int(req.target_user_id) if req.target_user_id is not None else None,
                            6,
                        )
                        profile_block_id = int(target_fields["target_person_id"] or req.target_user_id or 0)
                        display_name = req.target or str(req.target_user_id or target_fields["target_person_id"])
                        profile_pack = deps.format_profile_for_llm(
                            [
                                (
                                    profile_block_id,
                                    display_name,
                                    profile_events,
                                )
                            ],
                            max_chars=900,
                        )[:max_msg_content]

                    recall_count = _dedupe_recall_count(events, summaries, profile_events)
                    recall_provenance_counts = compute_recall_provenance_counts(
                        events=events,
                        summaries=summaries,
                        profile_events=profile_events,
                    )
                    recall_coverage = compute_recall_coverage(
                        recall_count,
                        provenance_counts=recall_provenance_counts,
                    )

                    dm_messages = build_dm_prompt_messages(
                        system_prompt_base=deps.system_prompt_base,
                        context_pack=context_pack,
                        guidelines=deps.dm_guidelines,
                        recent_context=recent_context,
                        memory_pack=memory_pack,
                        profile_pack=profile_pack,
                        req=req,
                        mode=mode,
                        clarifying_questions=clarifying_questions,
                        max_chars=max_msg_content,
                    )
                    dm_resp = await asyncio.to_thread(
                        deps.client.chat.completions.create,
                        model=deps.openai_model,
                        messages=dm_messages,
                    )
                    dm_raw = (dm_resp.choices[0].message.content or "").strip()
                    dm_result = parse_dm_result_from_model(
                        dm_raw,
                        recall_coverage=recall_coverage,
                        assumptions_used=assumptions_used,
                    )
                    run = DmDraftRun(
                        result=dm_result,
                        mode=mode,
                        parse_quality=parsed.parse_quality,
                        missing_fields=list(parsed.missing_fields),
                        assumptions_used=assumptions_used,
                        clarifying_questions=clarifying_questions,
                        recall_count=recall_count,
                    )
                    reply = format_dm_result_for_discord(run)
                    await deps.send_chunked(message.channel, reply)

                    if deps.enable_episode_logging and should_log_episode(deps.episode_log_filters, runtime_ctx):
                        draft_variant_id = dm_result.drafts[0].id if dm_result.drafts else None
                        dm_result_payload = {
                            "status": "drafted",
                            "blocking_collab": False,
                            "dm_guidelines_version": deps.dm_guidelines.version,
                            "dm_guidelines_source": deps.dm_guidelines_source,
                            "draft_version": DM_DRAFT_VERSION,
                            "draft_variant_id": draft_variant_id,
                            "prompt_fingerprint": prompt_fingerprint,
                            "critical_missing_fields": [],
                            "blocking_reason": None,
                            "drafts": [
                                {
                                    "id": d.id,
                                    "label": d.label,
                                    "text": d.text,
                                    "rationale": d.rationale,
                                }
                                for d in dm_result.drafts
                            ],
                            "risk_notes": list(dm_result.risk_notes),
                            "optional_tighten": dm_result.optional_tighten,
                            "recall_coverage": dict(dm_result.recall_coverage),
                            "clarifying_questions": list(clarifying_questions[:2]),
                            "assumptions_used": list(assumptions_used),
                        }
                        dm_artifact = build_dm_episode_artifact(
                            parse_payload=dm_parse_payload,
                            result_payload=dm_result_payload,
                        )
                        episode_payload = {
                            "timestamp_utc": deps.utc_iso(),
                            "context_profile_id": int(context_profile_id),
                            "user_id": int(message.author.id),
                            "person_id": int(actor_person_id),
                            "controller_config_id": int(controller_cfg.get("id")) if controller_cfg.get("id") is not None else None,
                            "input_excerpt": safe_prompt[:500],
                            "assistant_output_excerpt": reply[:800],
                            "retrieved_memory_ids": retrieved_memory_ids,
                            "tags": [
                                "mode:dm_draft",
                                f"surface:{runtime_ctx['surface']}",
                                f"caller:{runtime_ctx['caller_type']}",
                                f"group:{runtime_ctx['channel_policy_group']}",
                                f"actor_person:{int(actor_person_id)}",
                                f"target_user:{target_fields['target_user_id'] if target_fields['target_user_id'] is not None else 'none'}",
                                f"target_person:{target_fields['target_person_id'] if target_fields['target_person_id'] is not None else 'none'}",
                                f"target_type:{target_fields['target_type']}",
                                f"target_entity:{target_fields['target_entity_key']}",
                                f"guideline_pack:{deps.dm_guidelines.version}",
                            ],
                            "implicit_signals": {
                                "ctx_rows": int(ctx_rows),
                                "memory_hits": len(retrieved_memory_ids),
                                "parse_quality": parsed.parse_quality,
                                "missing_fields_count": len(parsed.missing_fields),
                                "mode_requested": mode_requested,
                                "mode_inferred": mode_inferred,
                                "mode_used": mode,
                                "dm_guidelines_version": deps.dm_guidelines.version,
                                "dm_guidelines_source": deps.dm_guidelines_source,
                                "blocking_collab": False,
                                "critical_missing_fields": [],
                                "blocking_reason": None,
                                "draft_version": DM_DRAFT_VERSION,
                                "draft_variant_id": draft_variant_id,
                                "prompt_fingerprint": prompt_fingerprint,
                                "profile_hits": len(profile_events),
                                "recall_coverage_count": int(recall_count),
                                "recall_provenance_counts": dict(recall_provenance_counts),
                                "target_user_id": target_fields["target_user_id"],
                                "target_person_id": target_fields["target_person_id"],
                                "target_display_name": target_fields["target_display_name"],
                                "target_type": target_fields["target_type"],
                                "target_confidence": target_fields["target_confidence"],
                                "target_entity_key": target_fields["target_entity_key"],
                                **dm_artifact,
                            },
                            "target_user_id": target_fields["target_user_id"],
                            "target_person_id": target_fields["target_person_id"],
                            "target_display_name": target_fields["target_display_name"],
                            "target_type": target_fields["target_type"],
                            "target_confidence": target_fields["target_confidence"],
                            "target_entity_key": target_fields["target_entity_key"],
                            "mode_requested": mode_requested,
                            "mode_inferred": mode_inferred,
                            "mode_used": mode,
                            "dm_guidelines_version": deps.dm_guidelines.version,
                            "dm_guidelines_source": deps.dm_guidelines_source,
                            "blocking_collab": False,
                            "critical_missing_fields": [],
                            "blocking_reason": None,
                            "draft_version": DM_DRAFT_VERSION,
                            "draft_variant_id": draft_variant_id,
                            "prompt_fingerprint": prompt_fingerprint,
                            "guild_id": int(message.guild.id) if message.guild else None,
                            "channel_id": int(message.channel.id) if hasattr(message.channel, "id") else None,
                            "message_id": int(message.id),
                        }
                        async with deps.db_lock:
                            await asyncio.to_thread(deps.insert_episode_log_sync, deps.db_conn, episode_payload)
                    return

                events, summaries, retrieved_memory_ids, memory_pack = await maybe_build_memory_pack(
                    stage_at_least=deps.stage_at_least,
                    infer_scope=deps.infer_scope,
                    recall_memory_func=deps.recall_memory_func,
                    format_memory_for_llm=deps.format_memory_for_llm,
                    safe_prompt=safe_prompt,
                    max_chars=max_msg_content,
                )

                print(
                    f"[CTX] channel={message.channel.id} rows={ctx_rows} before={message.id} "
                    f"ctx_chars={len(recent_context)} pack_chars={len(context_pack)} prompt_chars={len(safe_prompt)} "
                    f"mem_chars={len(memory_pack)} stage={deps.memory_stage} limit={deps.recent_context_limit} "
                    f"context={runtime_ctx['caller_type']}/{runtime_ctx['surface']} cfg={controller_cfg.get('scope','global')}"
                )

                instructions = (
                    "Use ONLY the context provided in this request: "
                    "(1) Recent channel context, "
                    "(2) Relevant persistent memory (if provided), and "
                    "(3) Topic summaries (if provided). "
                    "Do not rely on general knowledge.\n"
                    "CRITICAL ATTRIBUTION RULE: Do NOT invent metadata (channel name, user, date, message id, source). "
                    "If a detail is not explicitly present, label it as unknown.\n"
                    "CORESPONSE/CONTINUITY RULE: If the user reply is short (<= 6 words), interpret it as an answer to "
                    "Epoxy's most recent direct question/offer in the recent context unless the user clearly starts a new task.\n"
                    "COREFERENCE RULE: If the user uses a pronoun (he/she/they/it/that) and the recent channel context "
                    "clearly names a single likely referent in the last 1-3 turns, assume that referent. "
                    "Ask a clarifying question ONLY if there are 2+ plausible referents in the last 3 turns.\n"
                    "If the provided context is insufficient to answer, say so and ask 1 clarifying question."
                )[:max_msg_content]
                controller_directive = (
                    f"Controller context: caller_type={runtime_ctx['caller_type']}, "
                    f"surface={runtime_ctx['surface']}, policy={runtime_ctx['sensitivity_policy_id']}, "
                    f"persona={controller_cfg.get('persona', 'guide')}, "
                    f"depth={controller_cfg.get('depth', 0.35):.2f}, "
                    f"strictness={controller_cfg.get('strictness', 0.65):.2f}, "
                    f"intervention={controller_cfg.get('intervention_level', 0.35):.2f}. "
                    "Never reveal another member's private information in member/public contexts."
                )[:max_msg_content]

                chat_messages = build_chat_messages(
                    system_prompt_base=deps.system_prompt_base,
                    context_pack=context_pack,
                    controller_directive=controller_directive,
                    instructions=instructions,
                    anchor_block=anchor_block,
                    recent_context=recent_context,
                    memory_pack=memory_pack or None,
                    safe_prompt=safe_prompt,
                    max_chars=max_msg_content,
                )

                resp = await asyncio.to_thread(
                    deps.client.chat.completions.create,
                    model=deps.openai_model,
                    messages=chat_messages,
                )
                reply = (resp.choices[0].message.content or "(no output)")
                await deps.send_chunked(message.channel, reply)

                if deps.enable_episode_logging and should_log_episode(deps.episode_log_filters, runtime_ctx):
                    episode_payload = {
                        "timestamp_utc": deps.utc_iso(),
                        "context_profile_id": int(context_profile_id),
                        "user_id": int(message.author.id),
                        "person_id": int(actor_person_id),
                        "controller_config_id": int(controller_cfg.get("id")) if controller_cfg.get("id") is not None else None,
                        "input_excerpt": safe_prompt[:500],
                        "assistant_output_excerpt": reply[:800],
                        "retrieved_memory_ids": retrieved_memory_ids,
                        "tags": [
                            f"surface:{runtime_ctx['surface']}",
                            f"caller:{runtime_ctx['caller_type']}",
                            f"group:{runtime_ctx['channel_policy_group']}",
                            f"actor_person:{int(actor_person_id)}",
                        ],
                        "implicit_signals": {"ctx_rows": int(ctx_rows), "memory_hits": len(retrieved_memory_ids)},
                        "guild_id": int(message.guild.id) if message.guild else None,
                        "channel_id": int(message.channel.id) if hasattr(message.channel, "id") else None,
                        "message_id": int(message.id),
                    }
                    async with deps.db_lock:
                        await asyncio.to_thread(deps.insert_episode_log_sync, deps.db_conn, episode_payload)

                return

            except Exception as e:
                print(f"[OpenAI] Error: {e}")
                await message.channel.send("Epoxy hiccuped. Check logs.")

        await bot.process_commands(message)
