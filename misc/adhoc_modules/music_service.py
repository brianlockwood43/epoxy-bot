from __future__ import annotations

import asyncio
import re
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs
from urllib.parse import urlparse

import discord

try:
    import yt_dlp
except ModuleNotFoundError:  # pragma: no cover - dependency may be absent in some test envs
    yt_dlp = None


RISK_ACK_VALUE = "I_ACCEPT_YOUTUBE_RISK"
YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


@dataclass(slots=True)
class MusicQueueItem:
    video_id: str
    canonical_url: str
    title: str
    uploader: str
    duration_seconds: int
    submitted_by_user_id: int
    submitted_at_utc: str
    score: int
    allow_hits: list[str]
    deny_hits: list[str]
    category_music: bool
    forced: bool


class MusicService:
    def __init__(
        self,
        *,
        enabled: bool,
        risk_ack: str,
        text_channel_id: int,
        voice_channel_id: int,
        voice_channel_aliases: dict[str, int] | None = None,
        operator_user_ids: set[int],
        queue_max: int,
        max_per_user: int,
        queue_cooldown_seconds: int,
        idle_disconnect_seconds: int,
        yt_min_score: int,
        yt_allow_keywords: list[str],
        yt_deny_keywords: list[str],
        min_duration_seconds: int,
        max_duration_seconds: int,
        playlist_max_items: int,
        dry_run: bool,
    ) -> None:
        self.enabled_flag = bool(enabled)
        self.risk_ack = str(risk_ack or "").strip()
        self.text_channel_id = int(text_channel_id or 0)
        self.voice_channel_id = int(voice_channel_id or 0)
        self.voice_channel_aliases = self._build_voice_channel_aliases(
            default_voice_channel_id=self.voice_channel_id,
            aliases=voice_channel_aliases or {},
        )
        self.operator_user_ids = {int(uid) for uid in (operator_user_ids or set()) if int(uid) > 0}
        self.queue_max = max(1, int(queue_max or 25))
        self.max_per_user = max(1, int(max_per_user or 3))
        self.queue_cooldown_seconds = max(0, int(queue_cooldown_seconds or 30))
        self.idle_disconnect_seconds = max(0, int(idle_disconnect_seconds or 600))
        self.yt_min_score = int(yt_min_score or 2)
        self.yt_allow_keywords = [str(x).strip().lower() for x in (yt_allow_keywords or []) if str(x).strip()]
        self.yt_deny_keywords = [str(x).strip().lower() for x in (yt_deny_keywords or []) if str(x).strip()]
        self.min_duration_seconds = max(0, int(min_duration_seconds or 90))
        self.max_duration_seconds = max(self.min_duration_seconds, int(max_duration_seconds or 7200))
        self.playlist_max_items = max(1, int(playlist_max_items or 10))
        self.dry_run = bool(dry_run)

        self.queue: deque[MusicQueueItem] = deque()
        self.current_item: MusicQueueItem | None = None
        self.voice_client: discord.VoiceClient | None = None
        self.active_voice_channel_id: int | None = None
        self.active_voice_target: str | None = None
        self.connected_guild_id: int | None = None
        self.last_queue_at_by_user: dict[int, float] = {}
        self.pending_intake_count: int = 0
        self.last_playback_error: str | None = None

        self._idle_disconnect_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def disabled_reason(self) -> str | None:
        if not self.enabled_flag:
            return "music feature flag is off"
        if self.risk_ack != RISK_ACK_VALUE:
            return "risk acknowledgment missing"
        if self.text_channel_id <= 0 or not self.voice_channel_aliases:
            return "music channel IDs are not configured"
        if yt_dlp is None:
            return "yt-dlp is not installed"
        return None

    @staticmethod
    def _normalize_voice_alias(raw: str) -> str:
        return re.sub(r"[\s_-]+", "", str(raw or "").strip().lower())

    @classmethod
    def _build_voice_channel_aliases(
        cls,
        *,
        default_voice_channel_id: int,
        aliases: dict[str, int],
    ) -> dict[str, int]:
        out: dict[str, int] = {}
        if int(default_voice_channel_id or 0) > 0:
            out["calm"] = int(default_voice_channel_id)
        for key, value in (aliases or {}).items():
            alias = cls._normalize_voice_alias(str(key or ""))
            channel_id = int(value or 0)
            if alias and channel_id > 0:
                out[alias] = channel_id
        return out

    def resolve_voice_target(self, selection: str | None) -> tuple[bool, str | None, int | None, str | None]:
        if not self.voice_channel_aliases:
            return (False, None, None, "no music voice channels are configured")

        normalized = self._normalize_voice_alias(str(selection or ""))
        if not normalized:
            if "calm" in self.voice_channel_aliases:
                return (True, "calm", int(self.voice_channel_aliases["calm"]), None)
            fallback = sorted(self.voice_channel_aliases.items())[0]
            return (True, str(fallback[0]), int(fallback[1]), None)

        channel_id = self.voice_channel_aliases.get(normalized)
        if channel_id is None:
            choices = ", ".join(sorted(self.voice_channel_aliases.keys()))
            return (False, None, None, f"unknown voice target '{selection}'. Options: {choices}")
        return (True, normalized, int(channel_id), None)

    def is_operator(self, user_id: int) -> bool:
        return int(user_id) in self.operator_user_ids

    def in_music_text_channel(self, channel_id: int) -> bool:
        return int(channel_id) == self.text_channel_id

    @staticmethod
    def _utc_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def normalize_youtube_url(self, raw_url: str) -> tuple[bool, str | None, str | None, str | None]:
        text = str(raw_url or "").strip()
        if not text:
            return (False, None, None, "missing URL")
        parsed = urlparse(text)
        if parsed.scheme not in {"http", "https"}:
            return (False, None, None, "URL must start with http:// or https://")

        host = (parsed.netloc or "").lower()
        path = parsed.path or ""
        video_id: str | None = None
        query = parse_qs(parsed.query or "")

        if "youtu.be" in host:
            token = path.strip("/").split("/", 1)[0]
            video_id = token or None
            if "list" in query:
                return (False, None, None, "playlist links are not supported in v1")
        elif "youtube.com" in host:
            if path == "/watch":
                video_id = (query.get("v") or [None])[0]
                if "list" in query:
                    return (False, None, None, "playlist links are not supported in v1")
            else:
                return (False, None, None, "unsupported YouTube URL format")
        else:
            return (False, None, None, "URL must be a youtube.com or youtu.be link")

        if not video_id or not YOUTUBE_ID_RE.fullmatch(video_id):
            return (False, None, None, "could not parse a valid YouTube video id")

        canonical = f"https://www.youtube.com/watch?v={video_id}"
        return (True, canonical, video_id, None)

    def parse_youtube_intake(self, raw_url: str) -> tuple[bool, dict[str, Any] | None, str | None]:
        text = str(raw_url or "").strip()
        if not text:
            return (False, None, "missing URL")
        parsed = urlparse(text)
        if parsed.scheme not in {"http", "https"}:
            return (False, None, "URL must start with http:// or https://")

        host = (parsed.netloc or "").lower()
        path = parsed.path or ""
        query = parse_qs(parsed.query or "")
        playlist_id = str((query.get("list") or [""])[0] or "").strip()

        if "youtu.be" in host:
            token = path.strip("/").split("/", 1)[0]
            if playlist_id:
                if not token or not YOUTUBE_ID_RE.fullmatch(token):
                    return (False, None, "could not parse a valid YouTube video id")
                return (
                    True,
                    {
                        "kind": "playlist",
                        "playlist_id": playlist_id,
                        "playlist_url": f"https://www.youtube.com/watch?v={token}&list={playlist_id}",
                        "seed_video_id": token,
                    },
                    None,
                )
            if not token or not YOUTUBE_ID_RE.fullmatch(token):
                return (False, None, "could not parse a valid YouTube video id")
            return (
                True,
                {
                    "kind": "video",
                    "video_id": token,
                    "canonical_url": f"https://www.youtube.com/watch?v={token}",
                },
                None,
            )

        if "youtube.com" not in host:
            return (False, None, "URL must be a youtube.com or youtu.be link")

        if path == "/playlist":
            if not playlist_id:
                return (False, None, "playlist URL is missing list id")
            return (
                True,
                {
                    "kind": "playlist",
                    "playlist_id": playlist_id,
                    "playlist_url": f"https://www.youtube.com/playlist?list={playlist_id}",
                },
                None,
            )

        if path == "/watch":
            video_id = str((query.get("v") or [""])[0] or "").strip()
            if playlist_id:
                if video_id and not YOUTUBE_ID_RE.fullmatch(video_id):
                    return (False, None, "could not parse a valid YouTube video id")
                playlist_url = (
                    f"https://www.youtube.com/watch?v={video_id}&list={playlist_id}"
                    if video_id
                    else f"https://www.youtube.com/playlist?list={playlist_id}"
                )
                return (
                    True,
                    {
                        "kind": "playlist",
                        "playlist_id": playlist_id,
                        "playlist_url": playlist_url,
                        "seed_video_id": video_id or None,
                    },
                    None,
                )
            if not video_id or not YOUTUBE_ID_RE.fullmatch(video_id):
                return (False, None, "could not parse a valid YouTube video id")
            return (
                True,
                {
                    "kind": "video",
                    "video_id": video_id,
                    "canonical_url": f"https://www.youtube.com/watch?v={video_id}",
                },
                None,
            )

        return (False, None, "unsupported YouTube URL format")

    def evaluate_metadata_heuristic(self, metadata: dict[str, Any]) -> dict[str, Any]:
        title = str(metadata.get("title") or "")
        uploader = str(metadata.get("uploader") or metadata.get("channel") or "")
        description = str(metadata.get("description") or "")
        tags = metadata.get("tags")
        if not isinstance(tags, list):
            tags = []
        categories = metadata.get("categories")
        if not isinstance(categories, list):
            categories = []
        duration_raw = metadata.get("duration")
        duration = int(duration_raw) if isinstance(duration_raw, (int, float)) else 0

        corpus_parts = [title, uploader, description]
        corpus_parts.extend(str(t) for t in tags if str(t).strip())
        corpus_parts.extend(str(c) for c in categories if str(c).strip())
        corpus = " ".join(corpus_parts).lower()

        allow_hits = sorted({kw for kw in self.yt_allow_keywords if kw in corpus})
        deny_hits = sorted({kw for kw in self.yt_deny_keywords if kw in corpus})
        score = len(allow_hits) - (2 * len(deny_hits))
        category_music = any("music" in str(c or "").strip().lower() for c in categories)
        duration_ok = self.min_duration_seconds <= duration <= self.max_duration_seconds

        passes = (
            score >= self.yt_min_score
            and len(deny_hits) == 0
            and duration_ok
            and (category_music or score >= (self.yt_min_score + 1))
        )
        return {
            "passes": bool(passes),
            "score": int(score),
            "allow_hits": allow_hits,
            "deny_hits": deny_hits,
            "category_music": bool(category_music),
            "duration_ok": bool(duration_ok),
            "duration_seconds": int(duration),
        }

    async def fetch_video_metadata(self, canonical_url: str) -> tuple[bool, dict[str, Any] | None, str | None]:
        try:
            info = await asyncio.to_thread(self._extract_video_info_sync, canonical_url, True)
        except Exception as e:
            return (False, None, f"metadata lookup failed: {str(e)[:160]}")

        if not isinstance(info, dict):
            return (False, None, "extractor returned invalid response")
        if info.get("_type") in {"playlist", "multi_video"} or info.get("entries"):
            return (False, None, "playlist/container links are not supported")

        live_status = str(info.get("live_status") or "").strip().lower()
        is_live = bool(info.get("is_live")) or live_status in {"is_live", "is_upcoming", "post_live"}
        if is_live:
            return (False, None, "live streams are not supported")

        if int(info.get("age_limit") or 0) > 0:
            return (False, None, "age-gated videos are not supported")

        availability = str(info.get("availability") or "").strip().lower()
        if availability in {"private", "premium_only", "subscriber_only", "needs_auth"}:
            return (False, None, "video is unavailable for playback")

        return (True, info, None)

    async def resolve_stream_url(self, canonical_url: str) -> tuple[bool, str | None, str | None]:
        try:
            info = await asyncio.to_thread(self._extract_video_info_sync, canonical_url, False)
        except Exception as e:
            return (False, None, f"stream resolution failed: {str(e)[:160]}")

        if not isinstance(info, dict):
            return (False, None, "extractor returned invalid stream response")
        if info.get("_type") in {"playlist", "multi_video"} or info.get("entries"):
            return (False, None, "playlist/container links are not supported")

        url = str(info.get("url") or "").strip()
        if not url:
            formats = info.get("formats")
            if isinstance(formats, list):
                for row in reversed(formats):
                    if not isinstance(row, dict):
                        continue
                    candidate = str(row.get("url") or "").strip()
                    if not candidate:
                        continue
                    if str(row.get("vcodec") or "").strip().lower() == "none":
                        url = candidate
                        break
        if not url:
            return (False, None, "no playable audio stream URL found")
        return (True, url, None)

    async def fetch_playlist_video_ids(
        self,
        playlist_url: str,
        *,
        max_items: int,
    ) -> tuple[bool, list[str] | None, str | None, str | None]:
        try:
            info = await asyncio.to_thread(self._extract_playlist_info_sync, playlist_url, max_items)
        except Exception as e:
            return (False, None, None, f"playlist lookup failed: {str(e)[:160]}")

        if not isinstance(info, dict):
            return (False, None, None, "extractor returned invalid playlist response")

        playlist_title = str(info.get("title") or "").strip() or "YouTube playlist"
        entries = info.get("entries")
        if not isinstance(entries, list) or not entries:
            return (False, None, playlist_title, "playlist has no playable entries")

        seen: set[str] = set()
        out: list[str] = []
        for row in entries:
            if len(out) >= max_items:
                break
            if not isinstance(row, dict):
                continue
            video_id = str(row.get("id") or "").strip()
            if not video_id:
                url_field = str(row.get("url") or "").strip()
                if YOUTUBE_ID_RE.fullmatch(url_field):
                    video_id = url_field
            if not video_id or not YOUTUBE_ID_RE.fullmatch(video_id):
                continue
            if video_id in seen:
                continue
            seen.add(video_id)
            out.append(video_id)

        if not out:
            return (False, None, playlist_title, "playlist has no valid YouTube video entries")
        return (True, out, playlist_title, None)

    def _extract_video_info_sync(self, canonical_url: str, metadata_only: bool) -> dict[str, Any]:
        if yt_dlp is None:
            raise RuntimeError("yt-dlp dependency missing")
        opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "skip_download": True,
            "extract_flat": False,
            "nocheckcertificate": True,
        }
        if not metadata_only:
            opts["format"] = "bestaudio/best"

        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(canonical_url, download=False)

    def _extract_playlist_info_sync(self, playlist_url: str, max_items: int) -> dict[str, Any]:
        if yt_dlp is None:
            raise RuntimeError("yt-dlp dependency missing")
        safe_max = max(1, int(max_items or 1))
        opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": False,
            "skip_download": True,
            "extract_flat": "in_playlist",
            "playlistend": safe_max,
            "nocheckcertificate": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(playlist_url, download=False)

    async def queue_youtube(self, *, raw_url: str, submitted_by_user_id: int, force: bool = False) -> tuple[bool, str]:
        reason = self.disabled_reason()
        if reason:
            return (False, f"Music is disabled: {reason}.")

        ok_input, intake, err_input = self.parse_youtube_intake(raw_url)
        if not ok_input or not isinstance(intake, dict):
            return (False, f"Queue rejected: {err_input or 'invalid URL'}")

        source_kind = str(intake.get("kind") or "")
        playlist_title = ""
        candidate_video_ids: list[str] = []

        if source_kind == "video":
            video_id = str(intake.get("video_id") or "").strip()
            if not video_id or not YOUTUBE_ID_RE.fullmatch(video_id):
                return (False, "Queue rejected: invalid YouTube video id.")
            candidate_video_ids = [video_id]
        elif source_kind == "playlist":
            playlist_url = str(intake.get("playlist_url") or "").strip()
            if not playlist_url:
                return (False, "Queue rejected: invalid playlist URL.")
            ok_list, list_ids, title, list_err = await self.fetch_playlist_video_ids(
                playlist_url,
                max_items=self.playlist_max_items,
            )
            if not ok_list or not list_ids:
                return (False, f"Queue rejected: {list_err or 'playlist lookup failed'}")
            candidate_video_ids = list(list_ids)
            playlist_title = str(title or "").strip()
        else:
            return (False, "Queue rejected: unsupported YouTube URL type.")

        user_id = int(submitted_by_user_id)
        now_monotonic = time.monotonic()

        async with self._lock:
            if not force:
                last_ts = float(self.last_queue_at_by_user.get(user_id, 0.0))
                wait_left = int((last_ts + self.queue_cooldown_seconds) - now_monotonic)
                if wait_left > 0:
                    return (False, f"Queue rejected: wait {wait_left}s before queueing again.")
            if source_kind == "video":
                if any(item.video_id == candidate_video_ids[0] for item in self.queue):
                    return (False, "Queue rejected: this video is already in the queue.")
                if len(self.queue) >= self.queue_max:
                    return (False, f"Queue rejected: queue is full ({self.queue_max} max).")
                if not force:
                    user_pending = sum(1 for item in self.queue if item.submitted_by_user_id == user_id)
                    if user_pending >= self.max_per_user:
                        return (False, f"Queue rejected: per-user queue limit is {self.max_per_user}.")

        async with self._lock:
            self.pending_intake_count += 1

        try:
            should_kick_playback = False
            has_connected_voice = False
            added_items: list[MusicQueueItem] = []
            skipped_duplicate = 0
            skipped_limit = 0
            skipped_metadata = 0
            rejection_sample = ""
            seen_this_request: set[str] = set()

            for video_id in candidate_video_ids:
                if video_id in seen_this_request:
                    skipped_duplicate += 1
                    continue
                seen_this_request.add(video_id)
                canonical_url = f"https://www.youtube.com/watch?v={video_id}"

                async with self._lock:
                    if any(item.video_id == video_id for item in self.queue):
                        skipped_duplicate += 1
                        continue
                    if len(self.queue) >= self.queue_max:
                        skipped_limit += 1
                        continue
                    if not force:
                        user_pending_now = sum(1 for item in self.queue if item.submitted_by_user_id == user_id)
                        if user_pending_now >= self.max_per_user:
                            skipped_limit += 1
                            continue

                ok_meta, metadata, meta_err = await self.fetch_video_metadata(canonical_url)
                if not ok_meta or metadata is None:
                    skipped_metadata += 1
                    if not rejection_sample:
                        rejection_sample = str(meta_err or "metadata check failed")
                    continue

                heuristic = self.evaluate_metadata_heuristic(metadata)
                expected_score = len(list(heuristic.get("allow_hits", []))) - (2 * len(list(heuristic.get("deny_hits", []))))
                score_value = int(heuristic.get("score", expected_score))
                if score_value != expected_score:
                    print(
                        f"[MUSIC] action=heuristic_score_mismatch "
                        f"reported={score_value} expected={expected_score} "
                        f"video_id={video_id}"
                    )
                    score_value = expected_score

                if not force and not heuristic["passes"]:
                    skipped_metadata += 1
                    if not rejection_sample:
                        reason_bits: list[str] = []
                        if score_value < self.yt_min_score:
                            reason_bits.append(f"score<{self.yt_min_score}")
                        if len(list(heuristic.get("deny_hits", []))) > 0:
                            reason_bits.append("deny_hits>0")
                        if not bool(heuristic.get("duration_ok", False)):
                            reason_bits.append(
                                f"duration_outside_{self.min_duration_seconds}-{self.max_duration_seconds}s"
                            )
                        if not (
                            bool(heuristic.get("category_music", False))
                            or score_value >= (self.yt_min_score + 1)
                        ):
                            reason_bits.append("category_not_music_and_score_below_bonus_threshold")
                        if not reason_bits:
                            reason_bits.append("unknown")
                        rejection_sample = (
                            "metadata did not pass calm-genre heuristic "
                            f"(score={score_value}, allow_hits={len(heuristic['allow_hits'])}, "
                            f"deny_hits={len(heuristic['deny_hits'])}, "
                            f"duration_ok={bool(heuristic.get('duration_ok', False))}, "
                            f"category_music={bool(heuristic.get('category_music', False))}, "
                            f"reasons={','.join(reason_bits)})."
                        )
                    continue

                duration_seconds = int(heuristic.get("duration_seconds") or 0)
                title = str(metadata.get("title") or "Unknown title").strip() or "Unknown title"
                uploader = str(metadata.get("uploader") or metadata.get("channel") or "Unknown uploader").strip() or "Unknown uploader"
                item = MusicQueueItem(
                    video_id=video_id,
                    canonical_url=canonical_url,
                    title=title,
                    uploader=uploader,
                    duration_seconds=duration_seconds,
                    submitted_by_user_id=user_id,
                    submitted_at_utc=self._utc_iso(),
                    score=score_value,
                    allow_hits=list(heuristic["allow_hits"]),
                    deny_hits=list(heuristic["deny_hits"]),
                    category_music=bool(heuristic["category_music"]),
                    forced=bool(force),
                )

                async with self._lock:
                    if any(existing.video_id == item.video_id for existing in self.queue):
                        skipped_duplicate += 1
                        continue
                    if len(self.queue) >= self.queue_max:
                        skipped_limit += 1
                        continue
                    if not force:
                        user_pending_now = sum(1 for existing in self.queue if existing.submitted_by_user_id == user_id)
                        if user_pending_now >= self.max_per_user:
                            skipped_limit += 1
                            continue
                    self.queue.append(item)
                    added_items.append(item)
                    vc = self.voice_client
                    has_connected_voice = bool(vc is not None and vc.is_connected())
                    should_kick_playback = should_kick_playback or bool(
                        vc is not None and vc.is_connected() and (not vc.is_playing()) and (not vc.is_paused()) and self.current_item is None
                    )
                    if should_kick_playback:
                        self._cancel_idle_disconnect_task_locked()

            if not added_items:
                if rejection_sample:
                    return (False, f"Queue rejected: {rejection_sample}")
                if skipped_duplicate > 0:
                    return (False, "Queue rejected: all requested tracks were already in the queue.")
                if skipped_limit > 0:
                    return (False, "Queue rejected: queue/per-user limits prevented adding tracks.")
                return (False, "Queue rejected: no playable tracks were accepted from request.")

            async with self._lock:
                self.last_queue_at_by_user[user_id] = now_monotonic
                final_queue_len = len(self.queue)

            for item in added_items:
                print(
                    f"[MUSIC] action=queue result=ok user={user_id} "
                    f"video_id={item.video_id} score={item.score} forced={item.forced}"
                )

            if should_kick_playback and not self.dry_run:
                await self._play_next()

            suffix = ""
            if not has_connected_voice:
                suffix = " Epoxy is not in voice yet. Operator: run `!music.start`."

            if source_kind == "video":
                item = added_items[0]
                return (
                    True,
                    f"Queued: {item.title} (score={item.score}, by={item.uploader}). Position: {final_queue_len}.{suffix}",
                )

            total_requested = len(candidate_video_ids)
            skipped_total = total_requested - len(added_items)
            detail_bits: list[str] = []
            if skipped_duplicate:
                detail_bits.append(f"duplicates={skipped_duplicate}")
            if skipped_metadata:
                detail_bits.append(f"metadata={skipped_metadata}")
            if skipped_limit:
                detail_bits.append(f"limits={skipped_limit}")
            detail_suffix = f" ({', '.join(detail_bits)})" if detail_bits else ""
            label = playlist_title or "playlist"
            return (
                True,
                (
                    f"Queued playlist: {label}. "
                    f"Added {len(added_items)}/{total_requested} tracks; skipped {skipped_total}{detail_suffix}.{suffix}"
                ),
            )
        finally:
            async with self._lock:
                self.pending_intake_count = max(0, int(self.pending_intake_count) - 1)

    async def start(
        self,
        *,
        bot,
        guild: discord.Guild,
        actor_user_id: int,
        channel_selection: str | None = None,
    ) -> tuple[bool, str]:
        reason = self.disabled_reason()
        if reason:
            return (False, f"Music is disabled: {reason}.")
        if guild is None:
            return (False, "Start failed: this command only works in a server.")
        ok_target, target_name, target_channel_id, target_err = self.resolve_voice_target(channel_selection)
        if not ok_target or target_channel_id is None:
            return (False, f"Start failed: {target_err or 'invalid voice target'}")

        self._loop = asyncio.get_running_loop()

        if self.dry_run:
            async with self._lock:
                self.connected_guild_id = int(guild.id)
                self.active_voice_channel_id = int(target_channel_id)
                self.active_voice_target = str(target_name or "unknown")
                if self.current_item is None and self.queue:
                    self.current_item = self.queue.popleft()
                self._cancel_idle_disconnect_task_locked()
            print(f"[MUSIC] action=start result=dry_run user={actor_user_id} guild={int(guild.id)}")
            if self.current_item is not None:
                return (
                    True,
                    f"[dry-run] Music started in {target_name}. Now playing: {self.current_item.title}",
                )
            return (True, f"[dry-run] Music started in {target_name}. Queue is empty.")

        voice_channel = guild.get_channel(target_channel_id)
        if voice_channel is None:
            try:
                voice_channel = await bot.fetch_channel(target_channel_id)
            except Exception:
                voice_channel = None
        if (
            voice_channel is None
            or not hasattr(voice_channel, "id")
            or not hasattr(voice_channel, "connect")
        ):
            return (False, f"Start failed: configured voice channel {target_channel_id} was not found.")

        try:
            vc = guild.voice_client
            if vc is None:
                vc = await voice_channel.connect()
            elif int(getattr(vc.channel, "id", 0) or 0) != target_channel_id:
                await vc.move_to(voice_channel)
        except Exception as e:
            return (False, f"Start failed: could not connect voice ({str(e)[:180]}).")

        async with self._lock:
            self.voice_client = vc
            self.active_voice_channel_id = int(target_channel_id)
            self.active_voice_target = str(target_name or "unknown")
            self.connected_guild_id = int(guild.id)
            self._cancel_idle_disconnect_task_locked()

        print(f"[MUSIC] action=start result=ok user={actor_user_id} guild={int(guild.id)}")
        await self._play_next()
        # Queue intake can still be in-flight while start is called; give it a short window.
        for _ in range(20):
            async with self._lock:
                pending = int(self.pending_intake_count)
                has_current = self.current_item is not None
                queued_n = len(self.queue)
            if has_current or queued_n > 0 or pending <= 0:
                break
            await asyncio.sleep(0.25)
            await self._play_next()
        async with self._lock:
            current_title = self.current_item.title if self.current_item is not None else None
            queued_n = len(self.queue)
            pending_n = int(self.pending_intake_count)
            last_error = self.last_playback_error
        if current_title:
            return (True, f"Music started in {target_name}. Now playing: {current_title} (queue={queued_n}).")
        if pending_n > 0:
            return (
                True,
                f"Music started in {target_name}. Queue intake in progress ({pending_n}); run `!music.now` in a moment.",
            )
        if last_error:
            return (True, f"Music started in {target_name}, but playback failed: {last_error}")
        return (True, f"Music started in {target_name}. Queue is empty.")

    async def stop(self, *, actor_user_id: int) -> tuple[bool, str]:
        reason = self.disabled_reason()
        if reason:
            return (False, f"Music is disabled: {reason}.")

        vc: discord.VoiceClient | None = None
        async with self._lock:
            self.queue.clear()
            self.current_item = None
            self._cancel_idle_disconnect_task_locked()
            vc = self.voice_client
            self.voice_client = None
            self.active_voice_channel_id = None
            self.active_voice_target = None
            self.connected_guild_id = None

        if vc is not None:
            try:
                if vc.is_playing() or vc.is_paused():
                    vc.stop()
                if vc.is_connected():
                    await vc.disconnect(force=True)
            except Exception:
                pass

        print(f"[MUSIC] action=stop result=ok user={actor_user_id}")
        return (True, "Music stopped. Queue cleared and voice disconnected.")

    async def skip(self, *, actor_user_id: int) -> tuple[bool, str]:
        reason = self.disabled_reason()
        if reason:
            return (False, f"Music is disabled: {reason}.")

        if self.dry_run:
            async with self._lock:
                if self.queue:
                    self.current_item = self.queue.popleft()
                    print(f"[MUSIC] action=skip result=dry_run user={actor_user_id} next={self.current_item.video_id}")
                    return (True, f"[dry-run] Skipped. Now playing: {self.current_item.title}")
                self.current_item = None
                return (True, "[dry-run] Skipped. Queue is now empty.")

        async with self._lock:
            vc = self.voice_client
            if vc is None or (not vc.is_playing() and not vc.is_paused()):
                return (False, "Skip failed: nothing is currently playing.")
            vc.stop()
        print(f"[MUSIC] action=skip result=ok user={actor_user_id}")
        return (True, "Skipped current track.")

    async def pause(self, *, actor_user_id: int) -> tuple[bool, str]:
        reason = self.disabled_reason()
        if reason:
            return (False, f"Music is disabled: {reason}.")
        if self.dry_run:
            return (True, "[dry-run] Paused.")

        async with self._lock:
            vc = self.voice_client
            if vc is None or not vc.is_playing():
                return (False, "Pause failed: nothing is currently playing.")
            vc.pause()
        print(f"[MUSIC] action=pause result=ok user={actor_user_id}")
        return (True, "Paused playback.")

    async def resume(self, *, actor_user_id: int) -> tuple[bool, str]:
        reason = self.disabled_reason()
        if reason:
            return (False, f"Music is disabled: {reason}.")
        if self.dry_run:
            return (True, "[dry-run] Resumed.")

        async with self._lock:
            vc = self.voice_client
            if vc is None or not vc.is_paused():
                return (False, "Resume failed: playback is not paused.")
            vc.resume()
        print(f"[MUSIC] action=resume result=ok user={actor_user_id}")
        return (True, "Resumed playback.")

    async def clear_queue(self, *, actor_user_id: int) -> tuple[bool, str]:
        reason = self.disabled_reason()
        if reason:
            return (False, f"Music is disabled: {reason}.")
        async with self._lock:
            n = len(self.queue)
            self.queue.clear()
            if self.current_item is None:
                self._schedule_idle_disconnect_locked()
        print(f"[MUSIC] action=clearqueue result=ok user={actor_user_id} removed={n}")
        return (True, f"Queue cleared ({n} removed).")

    async def now_text(self) -> str:
        async with self._lock:
            if self.current_item is None:
                return "Now playing: (none)"
            item = self.current_item
            return (
                f"Now playing: {item.title} ({item.canonical_url})\n"
                f"- uploader: {item.uploader}\n"
                f"- queued_by: {item.submitted_by_user_id}\n"
                f"- score: {item.score}{' [forced]' if item.forced else ''}"
            )

    async def queue_list_text(self, *, limit: int = 10) -> str:
        lim = max(1, min(int(limit or 10), 50))
        async with self._lock:
            rows = list(self.queue)[:lim]
        if not rows:
            return "Queue is empty."
        lines = [f"Queue (next {len(rows)}):"]
        for idx, item in enumerate(rows, start=1):
            lines.append(
                f"{idx}. {item.title} ({item.canonical_url}) "
                f"[score={item.score}{' forced' if item.forced else ''}]"
            )
        return "\n".join(lines)

    async def status_text(self) -> str:
        reason = self.disabled_reason()
        async with self._lock:
            vc = self.voice_client
            is_connected = bool(vc is not None and vc.is_connected()) if vc is not None else False
            is_playing = bool(vc is not None and vc.is_playing()) if vc is not None else False
            is_paused = bool(vc is not None and vc.is_paused()) if vc is not None else False
            current_title = self.current_item.title if self.current_item is not None else "(none)"
            q_len = len(self.queue)
            active_voice_channel_id = self.active_voice_channel_id
            active_voice_target = self.active_voice_target
        voice_targets = ", ".join(
            f"{name}:{channel_id}" for name, channel_id in sorted(self.voice_channel_aliases.items())
        ) or "(none)"
        return (
            "Music status:\n"
            f"- enabled: {'yes' if reason is None else 'no'}\n"
            f"- disabled_reason: {reason or '(none)'}\n"
            f"- dry_run: {'yes' if self.dry_run else 'no'}\n"
            f"- text_channel_id: {self.text_channel_id}\n"
            f"- default_voice_channel_id: {self.voice_channel_id}\n"
            f"- voice_targets: {voice_targets}\n"
            f"- active_voice_target: {active_voice_target or '(none)'}\n"
            f"- active_voice_channel_id: {active_voice_channel_id or 0}\n"
            f"- connected: {'yes' if is_connected else 'no'}\n"
            f"- playing: {'yes' if is_playing else 'no'}\n"
            f"- paused: {'yes' if is_paused else 'no'}\n"
            f"- now: {current_title}\n"
            f"- queue_len: {q_len}\n"
            f"- queue_intake_inflight: {self.pending_intake_count}\n"
            f"- last_playback_error: {self.last_playback_error or '(none)'}\n"
            f"- queue_limits: total={self.queue_max}, per_user={self.max_per_user}, cooldown_s={self.queue_cooldown_seconds}, playlist_max_items={self.playlist_max_items}"
        )

    async def _play_next(self) -> None:
        while True:
            async with self._lock:
                vc = self.voice_client
                if vc is None or not vc.is_connected():
                    self.current_item = None
                    return
                if vc.is_playing() or vc.is_paused():
                    return
                if not self.queue:
                    self.current_item = None
                    self._schedule_idle_disconnect_locked()
                    return
                item = self.queue.popleft()
                self.current_item = item
                self._cancel_idle_disconnect_task_locked()

            ok, stream_url, err = await self.resolve_stream_url(item.canonical_url)
            if not ok or not stream_url:
                self.last_playback_error = str(err or "stream URL resolution failed")[:220]
                print(
                    f"[MUSIC] action=play_next result=resolve_error "
                    f"video_id={item.video_id} error={err or 'unknown'}"
                )
                async with self._lock:
                    if self.current_item is not None and self.current_item.video_id == item.video_id:
                        self.current_item = None
                    # Keep failed item at head so operators can retry after fixing runtime/env issues.
                    self.queue.appendleft(item)
                return

            try:
                source = discord.FFmpegPCMAudio(
                    stream_url,
                    before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
                    options="-vn",
                )
            except Exception as e:
                self.last_playback_error = f"ffmpeg init failed: {str(e)[:180]}"
                print(
                    f"[MUSIC] action=play_next result=ffmpeg_error "
                    f"video_id={item.video_id} error={str(e)[:180]}"
                )
                async with self._lock:
                    if self.current_item is not None and self.current_item.video_id == item.video_id:
                        self.current_item = None
                    self.queue.appendleft(item)
                return

            loop = self._loop
            if loop is None:
                loop = asyncio.get_running_loop()
                self._loop = loop

            def _after_playback(error: Exception | None):
                if loop.is_closed():
                    return
                loop.call_soon_threadsafe(asyncio.create_task, self._on_track_finished(item.video_id, error))

            try:
                vc.play(source, after=_after_playback)
            except Exception as e:
                self.last_playback_error = f"voice play failed: {str(e)[:180]}"
                print(
                    f"[MUSIC] action=play_next result=voice_play_error "
                    f"video_id={item.video_id} error={str(e)[:180]}"
                )
                async with self._lock:
                    if self.current_item is not None and self.current_item.video_id == item.video_id:
                        self.current_item = None
                    self.queue.appendleft(item)
                return

            print(f"[MUSIC] action=play_next result=ok video_id={item.video_id} title={item.title[:80]}")
            self.last_playback_error = None
            return

    async def _on_track_finished(self, video_id: str, error: Exception | None) -> None:
        if error is not None:
            print(f"[MUSIC] action=track_finished result=error video_id={video_id} error={str(error)[:180]}")
        else:
            print(f"[MUSIC] action=track_finished result=ok video_id={video_id}")
        async with self._lock:
            if self.current_item is not None and self.current_item.video_id == video_id:
                self.current_item = None
        await self._play_next()

    def _cancel_idle_disconnect_task_locked(self) -> None:
        task = self._idle_disconnect_task
        if task is not None and not task.done():
            task.cancel()
        self._idle_disconnect_task = None

    def _schedule_idle_disconnect_locked(self) -> None:
        if self.idle_disconnect_seconds <= 0 or self.dry_run:
            return
        self._cancel_idle_disconnect_task_locked()
        self._idle_disconnect_task = asyncio.create_task(self._idle_disconnect_after_delay())

    async def _idle_disconnect_after_delay(self) -> None:
        await asyncio.sleep(self.idle_disconnect_seconds)
        vc: discord.VoiceClient | None = None
        async with self._lock:
            if self.queue or self.current_item is not None:
                return
            vc = self.voice_client
            if vc is None:
                return
            if vc.is_playing() or vc.is_paused():
                return
            self.voice_client = None
            self.active_voice_channel_id = None
            self.active_voice_target = None
            self.connected_guild_id = None
        try:
            if vc.is_connected():
                await vc.disconnect(force=True)
            print("[MUSIC] action=idle_disconnect result=ok")
        except Exception as e:
            print(f"[MUSIC] action=idle_disconnect result=error error={str(e)[:180]}")
