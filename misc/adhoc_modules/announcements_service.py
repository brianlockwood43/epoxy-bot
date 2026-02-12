from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from misc.adhoc_modules.announcements_store import ANNOUNCEMENT_TERMINAL_STATES
from misc.adhoc_modules.announcements_store import approve_cycle_sync
from misc.adhoc_modules.announcements_store import create_or_get_cycle_sync
from misc.adhoc_modules.announcements_store import fetch_answers_sync
from misc.adhoc_modules.announcements_store import fetch_cycle_by_date_sync
from misc.adhoc_modules.announcements_store import fetch_cycle_by_prep_thread_sync
from misc.adhoc_modules.announcements_store import insert_audit_log_sync
from misc.adhoc_modules.announcements_store import mark_manual_done_sync
from misc.adhoc_modules.announcements_store import mark_missed_sync
from misc.adhoc_modules.announcements_store import mark_posted_sync
from misc.adhoc_modules.announcements_store import set_draft_sync
from misc.adhoc_modules.announcements_store import set_override_sync
from misc.adhoc_modules.announcements_store import set_prep_refs_sync
from misc.adhoc_modules.announcements_store import undo_manual_done_sync
from misc.adhoc_modules.announcements_store import unapprove_cycle_sync
from misc.adhoc_modules.announcements_store import update_cycle_fields_sync
from misc.adhoc_modules.announcements_store import upsert_answer_sync


VALID_STATUSES = {
    "planned",
    "prep_pinged",
    "draft_ready",
    "approved",
    "posted",
    "manual_done",
    "missed",
    "cancelled",
}

DONE_MODE_TO_PATH = {
    "self": "manual_self_posted",
    "draft": "manual_draft_posted",
}

WEEKDAY_KEYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


@dataclass(slots=True)
class AnnouncementTemplateDay:
    weekday_key: str
    enabled: bool
    target_channel_id: int
    publish_time_local: str
    tone: str
    structure: list[str]
    questions: list[dict[str, Any]]
    style_notes: str
    style_examples: list[dict[str, str]]


class AnnouncementService:
    def __init__(
        self,
        *,
        db_lock,
        db_conn,
        client,
        openai_model: str,
        stage_at_least,
        recall_memory_func,
        format_memory_for_llm,
        utc_iso,
        templates_path: str,
        enabled: bool,
        timezone_name: str,
        prep_time_local: str,
        prep_channel_id: int,
        prep_role_name: str | None,
        dry_run: bool,
    ) -> None:
        self.db_lock = db_lock
        self.db_conn = db_conn
        self.client = client
        self.openai_model = openai_model
        self.stage_at_least = stage_at_least
        self.recall_memory_func = recall_memory_func
        self.format_memory_for_llm = format_memory_for_llm
        self.utc_iso = utc_iso
        self.templates_path = str(templates_path)
        self.enabled = bool(enabled)
        self.timezone_name = (timezone_name or "UTC").strip() or "UTC"
        self.prep_time_local = (prep_time_local or "09:00").strip() or "09:00"
        self.prep_channel_id = int(prep_channel_id or 0)
        self.prep_role_name = (prep_role_name or "").strip()
        self.dry_run = bool(dry_run)

        self._templates_cache: dict[str, Any] | None = None
        self._templates_mtime: float | None = None

    @staticmethod
    def _parse_hhmm(value: str) -> tuple[int, int]:
        v = (value or "").strip()
        m = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", v)
        if not m:
            raise ValueError(f"Invalid HH:MM time: {value}")
        return int(m.group(1)), int(m.group(2))

    def _tzinfo(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone_name)
        except Exception:
            return ZoneInfo("UTC")

    def _now_local(self) -> datetime:
        return datetime.now(timezone.utc).astimezone(self._tzinfo())

    def _today_local_str(self) -> str:
        return self._now_local().date().isoformat()

    def _tomorrow_local_str(self) -> str:
        return (self._now_local().date() + timedelta(days=1)).isoformat()

    def _local_date_for_mode(self, mode: str) -> str:
        m = (mode or "").strip().lower()
        if m == "tomorrow":
            return self._tomorrow_local_str()
        return self._today_local_str()

    def _read_templates(self) -> dict[str, Any]:
        path = Path(self.templates_path)
        if not path.exists():
            raise RuntimeError(f"Announcement template file not found: {self.templates_path}")
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise RuntimeError("Announcement templates file must contain a top-level mapping")
        return raw

    def _normalize_templates(self, raw: dict[str, Any]) -> dict[str, Any]:
        days_raw = raw.get("days") if isinstance(raw.get("days"), dict) else {}
        days_out: dict[str, dict[str, Any]] = {}
        for key in WEEKDAY_KEYS:
            d = days_raw.get(key) if isinstance(days_raw.get(key), dict) else {}
            questions = d.get("questions") if isinstance(d.get("questions"), list) else []
            normalized_questions: list[dict[str, Any]] = []
            for q in questions:
                if not isinstance(q, dict):
                    continue
                qid = str(q.get("id") or "").strip().lower()
                if not qid:
                    continue
                normalized_questions.append(
                    {
                        "id": qid,
                        "prompt": str(q.get("prompt") or "").strip(),
                        "required": bool(q.get("required", False)),
                        "guidance": str(q.get("guidance") or "").strip(),
                    }
                )

            style_raw = d.get("style_guidance") if isinstance(d.get("style_guidance"), dict) else {}
            style_notes = str(style_raw.get("notes") or "").strip()
            style_examples_raw = style_raw.get("examples") if isinstance(style_raw.get("examples"), list) else []
            normalized_style_examples: list[dict[str, str]] = []
            for idx, ex in enumerate(style_examples_raw):
                if not isinstance(ex, dict):
                    continue
                text = str(ex.get("text") or "").strip()
                if not text:
                    continue
                ex_id = str(ex.get("id") or f"example_{idx + 1}").strip()
                summary = str(ex.get("summary") or "").strip()
                normalized_style_examples.append({"id": ex_id, "summary": summary, "text": text})

            publish_local = str(d.get("publish_time_local") or "16:00").strip()
            try:
                self._parse_hhmm(publish_local)
            except ValueError:
                publish_local = "16:00"

            days_out[key] = {
                "enabled": bool(d.get("enabled", False)),
                "target_channel_id": int(d.get("target_channel_id") or 0),
                "publish_time_local": publish_local,
                "tone": str(d.get("tone") or "").strip(),
                "structure": [str(x).strip() for x in (d.get("structure") or []) if str(x).strip()],
                "questions": normalized_questions,
                "style_guidance": {
                    "notes": style_notes,
                    "examples": normalized_style_examples,
                }
                if style_notes or normalized_style_examples
                else None,
            }

        merged = {
            "timezone": str(raw.get("timezone") or "UTC").strip() or "UTC",
            "prep_time_local": str(raw.get("prep_time_local") or "09:00").strip() or "09:00",
            "prep_channel_id": int(raw.get("prep_channel_id") or 0),
            "prep_role_name": str(raw.get("prep_role_name") or "").strip(),
            "days": days_out,
        }
        return merged

    def _templates(self, force_reload: bool = False) -> dict[str, Any]:
        path = Path(self.templates_path)
        mtime = path.stat().st_mtime if path.exists() else None
        if (
            not force_reload
            and self._templates_cache is not None
            and self._templates_mtime is not None
            and mtime == self._templates_mtime
        ):
            return self._templates_cache

        raw = self._read_templates()
        data = self._normalize_templates(raw)
        self._templates_cache = data
        self._templates_mtime = mtime
        return data

    def reload_templates(self) -> dict[str, Any]:
        return self._templates(force_reload=True)

    def _effective_timezone(self) -> str:
        t = self._templates().get("timezone") or "UTC"
        if self.timezone_name and self.timezone_name != "UTC":
            return self.timezone_name
        return str(t).strip() or "UTC"

    def _effective_prep_time_local(self) -> str:
        if self.prep_time_local:
            return self.prep_time_local
        return str(self._templates().get("prep_time_local") or "09:00")

    def _effective_prep_channel_id(self) -> int:
        if self.prep_channel_id:
            return int(self.prep_channel_id)
        return int(self._templates().get("prep_channel_id") or 0)

    def _effective_prep_role_name(self) -> str:
        if self.prep_role_name:
            return self.prep_role_name
        return str(self._templates().get("prep_role_name") or "").strip()

    def _day_key_for_date(self, target_date_local: str) -> str:
        dt = datetime.strptime(target_date_local, "%Y-%m-%d").date()
        return WEEKDAY_KEYS[dt.weekday()]

    def _day_template(self, target_date_local: str) -> AnnouncementTemplateDay | None:
        day_key = self._day_key_for_date(target_date_local)
        days = self._templates().get("days") or {}
        d = days.get(day_key) if isinstance(days, dict) else None
        if not isinstance(d, dict):
            return None
        style_raw = d.get("style_guidance") if isinstance(d.get("style_guidance"), dict) else {}
        style_examples_raw = style_raw.get("examples") if isinstance(style_raw.get("examples"), list) else []
        style_examples: list[dict[str, str]] = []
        for idx, ex in enumerate(style_examples_raw):
            if not isinstance(ex, dict):
                continue
            text = str(ex.get("text") or "").strip()
            if not text:
                continue
            ex_id = str(ex.get("id") or f"example_{idx + 1}").strip()
            summary = str(ex.get("summary") or "").strip()
            style_examples.append({"id": ex_id, "summary": summary, "text": text})
        return AnnouncementTemplateDay(
            weekday_key=day_key,
            enabled=bool(d.get("enabled", False)),
            target_channel_id=int(d.get("target_channel_id") or 0),
            publish_time_local=str(d.get("publish_time_local") or "16:00"),
            tone=str(d.get("tone") or ""),
            structure=list(d.get("structure") or []),
            questions=list(d.get("questions") or []),
            style_notes=str(style_raw.get("notes") or "").strip(),
            style_examples=style_examples,
        )

    def _publish_at_utc(self, *, target_date_local: str, publish_time_local: str) -> str:
        tz = ZoneInfo(self._effective_timezone())
        hh, mm = self._parse_hhmm(publish_time_local)
        d = datetime.strptime(target_date_local, "%Y-%m-%d").date()
        local_dt = datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz)
        return local_dt.astimezone(timezone.utc).isoformat()

    async def _fetch_cycle_for_thread(self, thread_id: int) -> dict[str, Any] | None:
        async with self.db_lock:
            return await asyncio.to_thread(fetch_cycle_by_prep_thread_sync, self.db_conn, int(thread_id))

    async def fetch_cycle_by_date(self, target_date_local: str) -> dict[str, Any] | None:
        async with self.db_lock:
            return await asyncio.to_thread(
                fetch_cycle_by_date_sync,
                self.db_conn,
                target_date_local=target_date_local,
                timezone=self._effective_timezone(),
            )

    async def ensure_cycle_for_date(self, target_date_local: str) -> dict[str, Any] | None:
        day = self._day_template(target_date_local)
        if not day or not day.enabled or day.target_channel_id <= 0:
            return None
        publish_at_utc = self._publish_at_utc(
            target_date_local=target_date_local,
            publish_time_local=day.publish_time_local,
        )
        async with self.db_lock:
            cycle = await asyncio.to_thread(
                create_or_get_cycle_sync,
                self.db_conn,
                target_date_local=target_date_local,
                timezone=self._effective_timezone(),
                weekday_key=day.weekday_key,
                target_channel_id=day.target_channel_id,
                publish_at_utc=publish_at_utc,
            )
            if (
                cycle.get("target_channel_id") != day.target_channel_id
                or cycle.get("publish_at_utc") != publish_at_utc
                or cycle.get("weekday_key") != day.weekday_key
            ):
                cycle = await asyncio.to_thread(
                    update_cycle_fields_sync,
                    self.db_conn,
                    int(cycle["id"]),
                    {
                        "target_channel_id": int(day.target_channel_id),
                        "publish_at_utc": publish_at_utc,
                        "weekday_key": day.weekday_key,
                    },
                )
            return cycle

    @staticmethod
    def _parse_date_token(date_token: str | None) -> str | None:
        tok = (date_token or "").strip()
        if not tok:
            return None
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", tok):
            return tok
        return None

    async def resolve_target_date(
        self,
        *,
        date_token: str | None,
        default_mode: str,
        channel_id: int | None = None,
    ) -> str:
        parsed = self._parse_date_token(date_token)
        if parsed:
            return parsed
        if channel_id:
            cycle = await self._fetch_cycle_for_thread(int(channel_id))
            if cycle:
                return str(cycle["target_date_local"])
        return self._local_date_for_mode(default_mode)

    async def _fetch_answers_map(self, cycle_id: int) -> dict[str, dict[str, Any]]:
        async with self.db_lock:
            rows = await asyncio.to_thread(fetch_answers_sync, self.db_conn, int(cycle_id))
        return {str(r["question_id"]).strip().lower(): r for r in rows}

    async def set_answer(
        self,
        *,
        target_date_local: str,
        question_id: str,
        answer_text: str,
        actor_user_id: int,
        source_message_id: int | None,
    ) -> tuple[bool, str]:
        cycle = await self.ensure_cycle_for_date(target_date_local)
        if not cycle:
            return (False, f"No enabled announcement day config for {target_date_local}.")
        if cycle.get("status") in ANNOUNCEMENT_TERMINAL_STATES:
            return (False, f"Cycle is terminal ({cycle.get('status')}); cannot add answers.")

        day = self._day_template(target_date_local)
        if not day:
            return (False, "No day template found.")
        qid = (question_id or "").strip().lower()
        valid_ids = {str(q.get("id") or "").strip().lower() for q in day.questions}
        if qid not in valid_ids:
            return (False, f"Unknown question id '{qid}'.")
        text = (answer_text or "").strip()
        if not text:
            return (False, "Answer text cannot be empty.")

        async with self.db_lock:
            _ = await asyncio.to_thread(
                upsert_answer_sync,
                self.db_conn,
                cycle_id=int(cycle["id"]),
                question_id=qid,
                answer_text=text,
                answered_by_user_id=int(actor_user_id),
                source_message_id=source_message_id,
            )
            await asyncio.to_thread(
                insert_audit_log_sync,
                self.db_conn,
                cycle_id=int(cycle["id"]),
                action="answer_set",
                actor_type="user",
                actor_user_id=int(actor_user_id),
                payload={"question_id": qid, "chars": len(text)},
            )
        return (True, f"Saved answer for `{qid}` on {target_date_local}.")

    def _question_prompt_block(self, day: AnnouncementTemplateDay, answers_map: dict[str, dict[str, Any]]) -> tuple[str, list[str]]:
        lines: list[str] = []
        missing_required: list[str] = []
        for q in day.questions:
            qid = str(q.get("id") or "").strip().lower()
            prompt = str(q.get("prompt") or "").strip()
            required = bool(q.get("required", False))
            answer_row = answers_map.get(qid)
            ans = (answer_row.get("answer_text") if answer_row else "") or ""
            ans = ans.strip()
            if ans:
                lines.append(f"- {qid}: {ans}")
            else:
                if required:
                    lines.append(f"- {qid}: TODO({qid})")
                    missing_required.append(qid)
                else:
                    lines.append(f"- {qid}: (optional, not provided)")
            if prompt:
                lines.append(f"  prompt: {prompt}")
        return ("\n".join(lines).strip(), missing_required)

    def _fallback_draft(self, *, target_date_local: str, day: AnnouncementTemplateDay, answers_map: dict[str, dict[str, Any]]) -> str:
        lines: list[str] = [
            f"Announcement Draft - {target_date_local}",
            "",
            f"Tone: {day.tone or 'Clear and concise.'}",
            "",
        ]
        if day.structure:
            lines.append("Structure:")
            for sec in day.structure:
                lines.append(f"- {sec}")
            lines.append("")

        lines.append("Inputs:")
        _, missing = self._question_prompt_block(day, answers_map)
        for q in day.questions:
            qid = str(q.get("id") or "").strip().lower()
            answer_row = answers_map.get(qid)
            ans = (answer_row.get("answer_text") if answer_row else "") or ""
            lines.append(f"- {qid}: {ans.strip() if ans.strip() else f'TODO({qid})'}")

        if missing:
            lines.append("")
            lines.append("Missing required:")
            for qid in missing:
                lines.append(f"- TODO({qid})")
        return "\n".join(lines).strip()

    def _style_prompt_block(self, day: AnnouncementTemplateDay) -> str:
        notes = (day.style_notes or "").strip()
        examples = list(day.style_examples or [])[:2]
        if not notes and not examples:
            return ""
        lines: list[str] = []
        if notes:
            lines.append(f"Style notes: {notes}")
        if examples:
            lines.append("Style reference examples (for style inspiration only):")
            for idx, ex in enumerate(examples, start=1):
                ex_id = str(ex.get("id") or f"example_{idx}").strip()
                summary = str(ex.get("summary") or "").strip()
                text = str(ex.get("text") or "").strip()
                if summary:
                    lines.append(f"- Example {idx} ({ex_id}) summary: {summary}")
                else:
                    lines.append(f"- Example {idx} ({ex_id})")
                lines.append(f"  text: {text}")
        return "\n".join(lines).strip()

    @staticmethod
    def _enforce_todo_markers(text: str, missing_required: list[str]) -> str:
        out = (text or "").strip()
        if not out:
            out = "Draft unavailable."
        additions: list[str] = []
        for qid in missing_required:
            marker = f"TODO({qid})"
            if marker not in out:
                additions.append(f"- {marker}")
        if additions:
            out = out + "\n\nMissing required inputs:\n" + "\n".join(additions)
        return out

    async def generate_draft(self, *, target_date_local: str, actor_user_id: int | None = None) -> tuple[bool, str, str | None]:
        cycle = await self.ensure_cycle_for_date(target_date_local)
        if not cycle:
            return (False, f"No enabled announcement day config for {target_date_local}.", None)
        if cycle.get("status") in {"posted", "manual_done", "missed", "cancelled"}:
            return (False, f"Cycle is terminal ({cycle.get('status')}); draft generation blocked.", None)

        day = self._day_template(target_date_local)
        if not day:
            return (False, "No day template found.", None)

        answers_map = await self._fetch_answers_map(int(cycle["id"]))
        qa_block, missing_required = self._question_prompt_block(day, answers_map)
        memory_pack = ""
        if self.stage_at_least("M1"):
            query_tokens = [day.weekday_key, "announcement", day.tone]
            for qid, row in answers_map.items():
                query_tokens.append(qid)
                query_tokens.append(str(row.get("answer_text") or ""))
            query = " ".join(query_tokens).strip()
            events, summaries = await self.recall_memory_func(query, scope="warm")
            memory_pack = self.format_memory_for_llm(events, summaries, max_chars=1400)

        sys_prompt = (
            "You are Epoxy's announcement drafting assistant.\n"
            "Generate a concise, publish-ready Discord announcement.\n"
            "Follow tone and structure exactly. Use provided answers and memory context if present.\n"
            "Do not invent concrete claims not supported by inputs.\n"
            "If style guidance references are provided, use them only to infer voice and structure; do not copy wording.\n"
            "If required inputs are missing, keep TODO(question_id) markers in the draft."
        )
        style_block = self._style_prompt_block(day)
        style_section = f"Style guidance:\n{style_block}\n\n" if style_block else ""
        user_prompt = (
            f"Target date: {target_date_local}\n"
            f"Weekday: {day.weekday_key}\n"
            f"Tone: {day.tone}\n"
            f"Structure sections: {', '.join(day.structure) if day.structure else '(no explicit sections)'}\n\n"
            f"Q&A inputs:\n{qa_block}\n\n"
            f"Relevant memory context:\n{memory_pack or '(none)'}\n\n"
            f"{style_section}"
            "Return only the announcement body."
        )

        draft_text: str
        try:
            resp = self.client.chat.completions.create(
                model=self.openai_model,
                messages=[
                    {"role": "system", "content": sys_prompt[:1800]},
                    {"role": "user", "content": user_prompt[:6000]},
                ],
            )
            draft_text = (resp.choices[0].message.content or "").strip()
            if not draft_text:
                draft_text = self._fallback_draft(target_date_local=target_date_local, day=day, answers_map=answers_map)
        except Exception:
            draft_text = self._fallback_draft(target_date_local=target_date_local, day=day, answers_map=answers_map)

        draft_text = self._enforce_todo_markers(draft_text, missing_required)

        async with self.db_lock:
            updated = await asyncio.to_thread(
                set_draft_sync,
                self.db_conn,
                cycle_id=int(cycle["id"]),
                draft_text=draft_text,
                clear_approval=True,
            )
            await asyncio.to_thread(
                insert_audit_log_sync,
                self.db_conn,
                cycle_id=int(cycle["id"]),
                action="draft_generated",
                actor_type="user" if actor_user_id else "system",
                actor_user_id=int(actor_user_id) if actor_user_id is not None else None,
                payload={"missing_required": missing_required, "answers": len(answers_map)},
            )
        return (True, f"Draft generated for {target_date_local}.", draft_text if updated else draft_text)

    async def set_override(
        self,
        *,
        target_date_local: str,
        override_text: str | None,
        actor_user_id: int,
    ) -> tuple[bool, str]:
        cycle = await self.ensure_cycle_for_date(target_date_local)
        if not cycle:
            return (False, f"No enabled announcement day config for {target_date_local}.")
        if cycle.get("status") in ANNOUNCEMENT_TERMINAL_STATES:
            return (False, f"Cycle is terminal ({cycle.get('status')}); override blocked.")
        async with self.db_lock:
            _ = await asyncio.to_thread(
                set_override_sync,
                self.db_conn,
                cycle_id=int(cycle["id"]),
                override_text=override_text,
            )
            await asyncio.to_thread(
                insert_audit_log_sync,
                self.db_conn,
                cycle_id=int(cycle["id"]),
                action="override_set" if override_text else "override_cleared",
                actor_type="user",
                actor_user_id=int(actor_user_id),
                payload={"chars": len((override_text or "").strip())},
            )
        if override_text:
            return (True, "Override text saved.")
        return (True, "Override cleared.")

    async def approve(self, *, target_date_local: str, actor_user_id: int) -> tuple[bool, str]:
        cycle = await self.ensure_cycle_for_date(target_date_local)
        if not cycle:
            return (False, f"No enabled announcement day config for {target_date_local}.")
        if cycle.get("status") in ANNOUNCEMENT_TERMINAL_STATES:
            return (False, f"Cycle is terminal ({cycle.get('status')}); cannot approve.")
        final_text = ((cycle.get("override_text") or "").strip() or (cycle.get("draft_text") or "").strip())
        if not final_text:
            return (False, "No draft/override text available. Run `!announce.generate` first.")
        async with self.db_lock:
            _ = await asyncio.to_thread(
                approve_cycle_sync,
                self.db_conn,
                cycle_id=int(cycle["id"]),
                user_id=int(actor_user_id),
            )
            await asyncio.to_thread(
                insert_audit_log_sync,
                self.db_conn,
                cycle_id=int(cycle["id"]),
                action="approved",
                actor_type="user",
                actor_user_id=int(actor_user_id),
                payload={"chars": len(final_text)},
            )
        return (True, f"Cycle {target_date_local} approved for scheduled posting.")

    async def unapprove(self, *, target_date_local: str, actor_user_id: int) -> tuple[bool, str]:
        cycle = await self.fetch_cycle_by_date(target_date_local)
        if not cycle:
            return (False, f"No cycle found for {target_date_local}.")
        if cycle.get("status") != "approved":
            return (False, f"Cycle is {cycle.get('status')}; only approved cycles can be unapproved.")
        async with self.db_lock:
            _ = await asyncio.to_thread(unapprove_cycle_sync, self.db_conn, cycle_id=int(cycle["id"]))
            await asyncio.to_thread(
                insert_audit_log_sync,
                self.db_conn,
                cycle_id=int(cycle["id"]),
                action="unapproved",
                actor_type="user",
                actor_user_id=int(actor_user_id),
                payload={},
            )
        return (True, f"Cycle {target_date_local} moved back to draft_ready.")

    async def mark_done(
        self,
        *,
        target_date_local: str,
        mode: str | None,
        actor_user_id: int,
        link: str | None,
        note: str | None,
    ) -> tuple[bool, str]:
        cycle = await self.ensure_cycle_for_date(target_date_local)
        if not cycle:
            return (False, f"No enabled announcement day config for {target_date_local}.")
        status = str(cycle.get("status") or "")
        if status == "posted":
            return (False, "Cycle already posted by Epoxy; done mark is not applicable.")
        if status in {"missed", "cancelled"}:
            return (False, f"Cycle is terminal ({status}); done mark blocked.")
        if status == "manual_done":
            return (False, "Cycle is already marked done.")

        normalized_mode = (mode or "").strip().lower() or "self"
        if normalized_mode not in DONE_MODE_TO_PATH:
            normalized_mode = "self"
        completion_path = DONE_MODE_TO_PATH[normalized_mode]

        async with self.db_lock:
            _ = await asyncio.to_thread(
                mark_manual_done_sync,
                self.db_conn,
                cycle_id=int(cycle["id"]),
                user_id=int(actor_user_id),
                completion_path=completion_path,
                link=link,
                note=note,
            )
            await asyncio.to_thread(
                insert_audit_log_sync,
                self.db_conn,
                cycle_id=int(cycle["id"]),
                action="manual_done",
                actor_type="user",
                actor_user_id=int(actor_user_id),
                payload={"mode": normalized_mode, "has_link": bool(link), "has_note": bool(note)},
            )
        return (True, f"Marked {target_date_local} as manual_done ({completion_path}).")

    async def undo_done(self, *, target_date_local: str, actor_user_id: int) -> tuple[bool, str]:
        cycle = await self.fetch_cycle_by_date(target_date_local)
        if not cycle:
            return (False, f"No cycle found for {target_date_local}.")
        if cycle.get("status") != "manual_done":
            return (False, f"Cycle is {cycle.get('status')}; only manual_done can be undone.")

        publish_at_raw = cycle.get("publish_at_utc")
        if publish_at_raw:
            try:
                publish_at = datetime.fromisoformat(str(publish_at_raw))
                if publish_at.tzinfo is None:
                    publish_at = publish_at.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) >= publish_at:
                    return (False, "Publish cutoff already passed; cannot undo done.")
            except Exception:
                pass

        async with self.db_lock:
            updated = await asyncio.to_thread(undo_manual_done_sync, self.db_conn, cycle_id=int(cycle["id"]))
            await asyncio.to_thread(
                insert_audit_log_sync,
                self.db_conn,
                cycle_id=int(cycle["id"]),
                action="manual_done_undone",
                actor_type="user",
                actor_user_id=int(actor_user_id),
                payload={"restored_status": updated.get("status") if updated else None},
            )
        return (True, f"Manual done undone for {target_date_local}.")

    async def get_answers_text(self, *, target_date_local: str) -> str:
        cycle = await self.fetch_cycle_by_date(target_date_local)
        if not cycle:
            return f"No cycle found for {target_date_local}."
        day = self._day_template(target_date_local)
        answers_map = await self._fetch_answers_map(int(cycle["id"]))
        lines = [f"Answers for {target_date_local} (status={cycle.get('status')}):"]
        if not day:
            lines.append("- No day template loaded.")
            return "\n".join(lines)
        for q in day.questions:
            qid = str(q.get("id") or "").strip().lower()
            prompt = str(q.get("prompt") or "").strip()
            required = bool(q.get("required", False))
            answer_row = answers_map.get(qid)
            ans = (answer_row.get("answer_text") if answer_row else "") or ""
            req = "required" if required else "optional"
            lines.append(f"- {qid} ({req}): {ans.strip() if ans.strip() else '(missing)'}")
            if prompt:
                lines.append(f"  prompt: {prompt}")
        return "\n".join(lines)

    async def get_status_text(self, *, target_date_local: str) -> str:
        cycle = await self.fetch_cycle_by_date(target_date_local)
        if not cycle:
            return f"No cycle found for {target_date_local}."
        answers_map = await self._fetch_answers_map(int(cycle["id"]))
        final_text = (cycle.get("override_text") or "").strip() or (cycle.get("draft_text") or "").strip()
        lines = [
            f"Announcement cycle {target_date_local}",
            f"- status: {cycle.get('status')}",
            f"- completion_path: {cycle.get('completion_path') or '(none)'}",
            f"- timezone: {cycle.get('timezone')}",
            f"- weekday_key: {cycle.get('weekday_key')}",
            f"- target_channel_id: {cycle.get('target_channel_id')}",
            f"- publish_at_utc: {cycle.get('publish_at_utc')}",
            f"- prep_channel_id: {cycle.get('prep_channel_id')}",
            f"- prep_thread_id: {cycle.get('prep_thread_id')}",
            f"- approved_by_user_id: {cycle.get('approved_by_user_id')}",
            f"- answers_count: {len(answers_map)}",
            f"- has_draft: {'yes' if (cycle.get('draft_text') or '').strip() else 'no'}",
            f"- has_override: {'yes' if (cycle.get('override_text') or '').strip() else 'no'}",
            f"- final_chars: {len(final_text)}",
        ]
        if cycle.get("manual_done_link"):
            lines.append(f"- manual_done_link: {cycle.get('manual_done_link')}")
        if cycle.get("manual_done_note"):
            lines.append(f"- manual_done_note: {cycle.get('manual_done_note')}")
        return "\n".join(lines)

    async def _get_channel(self, bot, channel_id: int):
        if channel_id <= 0:
            return None
        ch = bot.get_channel(int(channel_id))
        if ch is not None:
            return ch
        try:
            return await bot.fetch_channel(int(channel_id))
        except Exception:
            return None

    async def _send_prep_prompt(self, bot, cycle: dict[str, Any], day: AnnouncementTemplateDay) -> tuple[int | None, int | None]:
        prep_channel_id = self._effective_prep_channel_id()
        if prep_channel_id <= 0:
            raise RuntimeError("EPOXY_ANNOUNCE_PREP_CHANNEL_ID (or template prep_channel_id) must be set")
        prep_channel = await self._get_channel(bot, prep_channel_id)
        if prep_channel is None:
            raise RuntimeError(f"Prep channel not found: {prep_channel_id}")

        role_mention = ""
        role_name = self._effective_prep_role_name()
        if role_name and hasattr(prep_channel, "guild") and getattr(prep_channel, "guild", None):
            try:
                roles = list(getattr(prep_channel.guild, "roles", []) or [])
                for role in roles:
                    if str(getattr(role, "name", "")).strip() == role_name:
                        role_mention = str(getattr(role, "mention", "")).strip()
                        break
            except Exception:
                role_mention = ""

        date_local = str(cycle["target_date_local"])
        header = f"{role_mention} " if role_mention else ""
        header += (
            f"Daily announcement prep for **{date_local}**.\n"
            "Reply in the thread with `!announce.answer <question_id> | <answer>`.\n"
            "Then run `!announce.generate` and optionally `!announce.approve`."
        )
        root = await prep_channel.send(header)

        thread_obj = None
        try:
            if hasattr(root, "create_thread"):
                thread_obj = await root.create_thread(name=f"announce-prep-{date_local}")
        except Exception:
            thread_obj = None

        dest = thread_obj or prep_channel
        q_lines = ["Questions:"]
        for q in day.questions:
            qid = str(q.get("id") or "").strip().lower()
            prompt = str(q.get("prompt") or "").strip()
            req = "required" if bool(q.get("required", False)) else "optional"
            q_lines.append(f"- `{qid}` ({req}): {prompt}")
        await dest.send("\n".join(q_lines)[:1900])

        root_id = int(getattr(root, "id", 0) or 0) or None
        thread_id = int(getattr(thread_obj, "id", 0) or 0) or None
        return root_id, thread_id

    async def _notify_prep(self, bot, cycle: dict[str, Any], text: str) -> None:
        thread_id = int(cycle.get("prep_thread_id") or 0)
        channel_id = int(cycle.get("prep_channel_id") or self._effective_prep_channel_id() or 0)
        target = None
        if thread_id > 0:
            target = await self._get_channel(bot, thread_id)
        if target is None and channel_id > 0:
            target = await self._get_channel(bot, channel_id)
        if target is not None:
            try:
                await target.send((text or "")[:1900])
            except Exception:
                pass

    async def _trigger_prep_ping(
        self,
        *,
        bot,
        cycle: dict[str, Any],
        day: AnnouncementTemplateDay,
        actor_type: str,
        actor_user_id: int | None,
    ) -> tuple[bool, str]:
        try:
            prep_message_id, prep_thread_id = await self._send_prep_prompt(bot, cycle, day)
            async with self.db_lock:
                _ = await asyncio.to_thread(
                    set_prep_refs_sync,
                    self.db_conn,
                    cycle_id=int(cycle["id"]),
                    prep_channel_id=int(self._effective_prep_channel_id()),
                    prep_message_id=prep_message_id,
                    prep_thread_id=prep_thread_id,
                )
                await asyncio.to_thread(
                    insert_audit_log_sync,
                    self.db_conn,
                    cycle_id=int(cycle["id"]),
                    action="prep_pinged",
                    actor_type=actor_type,
                    actor_user_id=actor_user_id,
                    payload={"prep_message_id": prep_message_id, "prep_thread_id": prep_thread_id},
                )
            return (True, "Prep prompt sent.")
        except Exception as e:
            async with self.db_lock:
                _ = await asyncio.to_thread(
                    update_cycle_fields_sync,
                    self.db_conn,
                    int(cycle["id"]),
                    {"last_error": str(e)[:300]},
                )
                await asyncio.to_thread(
                    insert_audit_log_sync,
                    self.db_conn,
                    cycle_id=int(cycle["id"]),
                    action="prep_ping_failed",
                    actor_type=actor_type,
                    actor_user_id=actor_user_id,
                    payload={"error": str(e)[:200]},
                )
            return (False, f"Prep ping failed: {str(e)[:160]}")

    async def _publish_cycle(self, bot, cycle: dict[str, Any], *, actor_type: str, actor_user_id: int | None) -> tuple[bool, str]:
        if str(cycle.get("status")) != "approved":
            return (False, f"Cycle status is {cycle.get('status')}; not publishable.")
        final_text = ((cycle.get("override_text") or "").strip() or (cycle.get("draft_text") or "").strip())
        if not final_text:
            return (False, "No draft/override text available.")
        target_channel_id = int(cycle.get("target_channel_id") or 0)
        if target_channel_id <= 0:
            return (False, "Target channel id is missing.")

        posted_message_id: int | None = None
        if not self.dry_run:
            channel = await self._get_channel(bot, target_channel_id)
            if channel is None:
                return (False, f"Target channel not found: {target_channel_id}")
            msg = await channel.send(final_text[:1900])
            posted_message_id = int(getattr(msg, "id", 0) or 0) or None

        async with self.db_lock:
            posted = await asyncio.to_thread(
                mark_posted_sync,
                self.db_conn,
                cycle_id=int(cycle["id"]),
                posted_message_id=posted_message_id,
                final_text=final_text,
                completion_path="epoxy_posted",
            )
            await asyncio.to_thread(
                insert_audit_log_sync,
                self.db_conn,
                cycle_id=int(cycle["id"]),
                action="posted" if posted else "post_skipped",
                actor_type=actor_type,
                actor_user_id=actor_user_id,
                payload={
                    "dry_run": self.dry_run,
                    "posted_message_id": posted_message_id,
                    "target_channel_id": target_channel_id,
                    "chars": len(final_text),
                },
            )
        if posted:
            return (True, "Posted successfully.")
        return (False, "Post skipped because cycle was no longer publishable.")

    async def post_now(self, *, bot, target_date_local: str, actor_user_id: int) -> tuple[bool, str]:
        cycle = await self.fetch_cycle_by_date(target_date_local)
        if not cycle:
            return (False, f"No cycle found for {target_date_local}.")
        if cycle.get("status") in {"posted", "manual_done", "missed", "cancelled"}:
            return (False, f"Cycle is terminal ({cycle.get('status')}); cannot post.")
        return await self._publish_cycle(bot, cycle, actor_type="user", actor_user_id=int(actor_user_id))

    async def prep_now(self, *, bot, target_date_local: str, actor_user_id: int) -> tuple[bool, str]:
        cycle = await self.ensure_cycle_for_date(target_date_local)
        if not cycle:
            return (False, f"No enabled announcement day config for {target_date_local}.")
        status = str(cycle.get("status") or "")
        if status in ANNOUNCEMENT_TERMINAL_STATES:
            return (False, f"Cycle is terminal ({status}); prep ping blocked.")
        if status != "planned":
            return (False, f"Cycle is {status}; prep ping is only available from planned state.")
        day = self._day_template(target_date_local)
        if not day:
            return (False, "No day template found.")
        ok, msg = await self._trigger_prep_ping(
            bot=bot,
            cycle=cycle,
            day=day,
            actor_type="user",
            actor_user_id=int(actor_user_id),
        )
        if not ok:
            return (False, msg)
        return (True, f"Prep prompt sent for {target_date_local}.")

    async def _mark_missed(self, *, bot, cycle: dict[str, Any], reason: str) -> None:
        async with self.db_lock:
            _ = await asyncio.to_thread(mark_missed_sync, self.db_conn, cycle_id=int(cycle["id"]), reason=reason)
            await asyncio.to_thread(
                insert_audit_log_sync,
                self.db_conn,
                cycle_id=int(cycle["id"]),
                action="missed",
                actor_type="system",
                actor_user_id=None,
                payload={"reason": reason},
            )
        await self._notify_prep(bot, cycle, f"Announcement cycle {cycle['target_date_local']} missed publish cutoff ({reason}).")

    async def run_tick(self, bot) -> None:
        if not self.enabled:
            return

        now_local = self._now_local()
        today_local = now_local.date().isoformat()
        tomorrow_local = (now_local.date() + timedelta(days=1)).isoformat()
        prep_h, prep_m = self._parse_hhmm(self._effective_prep_time_local())
        prep_due = (now_local.hour, now_local.minute) >= (prep_h, prep_m)

        tomorrow_cycle = await self.ensure_cycle_for_date(tomorrow_local)
        if prep_due and tomorrow_cycle and str(tomorrow_cycle.get("status")) == "planned":
            day = self._day_template(tomorrow_local)
            if day:
                await self._trigger_prep_ping(
                    bot=bot,
                    cycle=tomorrow_cycle,
                    day=day,
                    actor_type="system",
                    actor_user_id=None,
                )

        today_cycle = await self.ensure_cycle_for_date(today_local)
        if not today_cycle:
            return

        publish_at_raw = today_cycle.get("publish_at_utc")
        if not publish_at_raw:
            return
        try:
            publish_at = datetime.fromisoformat(str(publish_at_raw))
            if publish_at.tzinfo is None:
                publish_at = publish_at.replace(tzinfo=timezone.utc)
        except Exception:
            return

        if datetime.now(timezone.utc) < publish_at:
            return

        status = str(today_cycle.get("status") or "")
        if status in ANNOUNCEMENT_TERMINAL_STATES:
            return
        if status == "approved":
            ok, msg = await self._publish_cycle(bot, today_cycle, actor_type="system", actor_user_id=None)
            if not ok:
                async with self.db_lock:
                    _ = await asyncio.to_thread(
                        update_cycle_fields_sync,
                        self.db_conn,
                        int(today_cycle["id"]),
                        {"last_error": msg[:300]},
                    )
            return
        if status in {"planned", "prep_pinged", "draft_ready"}:
            await self._mark_missed(bot=bot, cycle=today_cycle, reason="not approved by publish time")


def default_templates_path() -> str:
    # This resolves to repo-root/config when running from source checkout.
    here = Path(__file__).resolve().parents[2]
    return os.path.join(here, "config", "announcement_templates.yml")
