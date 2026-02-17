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
        dry_run: bool,
    ) -> None:
        self.enabled_flag = bool(enabled)
        self.risk_ack = str(risk_ack or "").strip()
        self.text_channel_id = int(text_channel_id or 0)
        self.voice_channel_id = int(voice_channel_id or 0)
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
        self.dry_run = bool(dry_run)

        self.queue: deque[MusicQueueItem] = deque()
        self.current_item: MusicQueueItem | None = None
        self.voice_client: discord.VoiceClient | None = None
        self.connected_guild_id: int | None = None
        self.last_queue_at_by_user: dict[int, float] = {}

        self._idle_disconnect_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def disabled_reason(self) -> str | None:
        if not self.enabled_flag:
            return "music feature flag is off"
        if self.risk_ack != RISK_ACK_VALUE:
            return "risk acknowledgment missing"
        if self.text_channel_id <= 0 or self.voice_channel_id <= 0:
            return "music channel IDs are not configured"
        if yt_dlp is None:
            return "yt-dlp is not installed"
        return None

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

    async def queue_youtube(self, *, raw_url: str, submitted_by_user_id: int, force: bool = False) -> tuple[bool, str]:
        reason = self.disabled_reason()
        if reason:
            return (False, f"Music is disabled: {reason}.")

        ok, canonical_url, video_id, err = self.normalize_youtube_url(raw_url)
        if not ok or not canonical_url or not video_id:
            return (False, f"Queue rejected: {err or 'invalid URL'}")

        user_id = int(submitted_by_user_id)
        now_monotonic = time.monotonic()
        async with self._lock:
            for item in self.queue:
                if item.video_id == video_id:
                    return (False, "Queue rejected: this video is already in the queue.")
            if len(self.queue) >= self.queue_max:
                return (False, f"Queue rejected: queue is full ({self.queue_max} max).")
            if not force:
                user_pending = sum(1 for item in self.queue if item.submitted_by_user_id == user_id)
                if user_pending >= self.max_per_user:
                    return (False, f"Queue rejected: per-user queue limit is {self.max_per_user}.")
                last_ts = float(self.last_queue_at_by_user.get(user_id, 0.0))
                wait_left = int((last_ts + self.queue_cooldown_seconds) - now_monotonic)
                if wait_left > 0:
                    return (False, f"Queue rejected: wait {wait_left}s before queueing again.")

        ok_meta, metadata, meta_err = await self.fetch_video_metadata(canonical_url)
        if not ok_meta or metadata is None:
            return (False, f"Queue rejected: {meta_err or 'metadata check failed'}")

        heuristic = self.evaluate_metadata_heuristic(metadata)
        if not force and not heuristic["passes"]:
            return (
                False,
                (
                    "Queue rejected: metadata did not pass calm-genre heuristic "
                    f"(score={heuristic['score']}, allow_hits={len(heuristic['allow_hits'])}, "
                    f"deny_hits={len(heuristic['deny_hits'])})."
                ),
            )

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
            score=int(heuristic["score"]),
            allow_hits=list(heuristic["allow_hits"]),
            deny_hits=list(heuristic["deny_hits"]),
            category_music=bool(heuristic["category_music"]),
            forced=bool(force),
        )

        should_kick_playback = False
        async with self._lock:
            for existing in self.queue:
                if existing.video_id == video_id:
                    return (False, "Queue rejected: this video is already in the queue.")
            if len(self.queue) >= self.queue_max:
                return (False, f"Queue rejected: queue is full ({self.queue_max} max).")
            self.queue.append(item)
            self.last_queue_at_by_user[user_id] = now_monotonic
            vc = self.voice_client
            should_kick_playback = bool(
                vc is not None and vc.is_connected() and (not vc.is_playing()) and (not vc.is_paused()) and self.current_item is None
            )
            if should_kick_playback:
                self._cancel_idle_disconnect_task_locked()

        print(f"[MUSIC] action=queue result=ok user={user_id} video_id={video_id} score={item.score} forced={item.forced}")
        if should_kick_playback and not self.dry_run:
            await self._play_next()
        return (
            True,
            f"Queued: {item.title} (score={item.score}, by={item.uploader}). Position: {len(self.queue)}.",
        )

    async def start(self, *, bot, guild: discord.Guild, actor_user_id: int) -> tuple[bool, str]:
        reason = self.disabled_reason()
        if reason:
            return (False, f"Music is disabled: {reason}.")
        if guild is None:
            return (False, "Start failed: this command only works in a server.")

        self._loop = asyncio.get_running_loop()

        if self.dry_run:
            async with self._lock:
                self.connected_guild_id = int(guild.id)
                if self.current_item is None and self.queue:
                    self.current_item = self.queue.popleft()
                self._cancel_idle_disconnect_task_locked()
            print(f"[MUSIC] action=start result=dry_run user={actor_user_id} guild={int(guild.id)}")
            if self.current_item is not None:
                return (True, f"[dry-run] Music started. Now playing: {self.current_item.title}")
            return (True, "[dry-run] Music started. Queue is empty.")

        voice_channel = guild.get_channel(self.voice_channel_id)
        if voice_channel is None:
            try:
                voice_channel = await bot.fetch_channel(self.voice_channel_id)
            except Exception:
                voice_channel = None
        if (
            voice_channel is None
            or not hasattr(voice_channel, "id")
            or not hasattr(voice_channel, "connect")
        ):
            return (False, f"Start failed: configured voice channel {self.voice_channel_id} was not found.")

        try:
            vc = guild.voice_client
            if vc is None:
                vc = await voice_channel.connect()
            elif int(getattr(vc.channel, "id", 0) or 0) != self.voice_channel_id:
                await vc.move_to(voice_channel)
        except Exception as e:
            return (False, f"Start failed: could not connect voice ({str(e)[:180]}).")

        async with self._lock:
            self.voice_client = vc
            self.connected_guild_id = int(guild.id)
            self._cancel_idle_disconnect_task_locked()

        print(f"[MUSIC] action=start result=ok user={actor_user_id} guild={int(guild.id)}")
        await self._play_next()
        async with self._lock:
            current_title = self.current_item.title if self.current_item is not None else None
            queued_n = len(self.queue)
        if current_title:
            return (True, f"Music started. Now playing: {current_title} (queue={queued_n}).")
        return (True, "Music started. Queue is empty.")

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
        return (
            "Music status:\n"
            f"- enabled: {'yes' if reason is None else 'no'}\n"
            f"- disabled_reason: {reason or '(none)'}\n"
            f"- dry_run: {'yes' if self.dry_run else 'no'}\n"
            f"- text_channel_id: {self.text_channel_id}\n"
            f"- voice_channel_id: {self.voice_channel_id}\n"
            f"- connected: {'yes' if is_connected else 'no'}\n"
            f"- playing: {'yes' if is_playing else 'no'}\n"
            f"- paused: {'yes' if is_paused else 'no'}\n"
            f"- now: {current_title}\n"
            f"- queue_len: {q_len}\n"
            f"- queue_limits: total={self.queue_max}, per_user={self.max_per_user}, cooldown_s={self.queue_cooldown_seconds}"
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
                print(
                    f"[MUSIC] action=play_next result=resolve_error "
                    f"video_id={item.video_id} error={err or 'unknown'}"
                )
                async with self._lock:
                    if self.current_item is not None and self.current_item.video_id == item.video_id:
                        self.current_item = None
                continue

            try:
                source = discord.FFmpegPCMAudio(
                    stream_url,
                    before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
                    options="-vn",
                )
            except Exception as e:
                print(
                    f"[MUSIC] action=play_next result=ffmpeg_error "
                    f"video_id={item.video_id} error={str(e)[:180]}"
                )
                async with self._lock:
                    if self.current_item is not None and self.current_item.video_id == item.video_id:
                        self.current_item = None
                continue

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
                print(
                    f"[MUSIC] action=play_next result=voice_play_error "
                    f"video_id={item.video_id} error={str(e)[:180]}"
                )
                async with self._lock:
                    if self.current_item is not None and self.current_item.video_id == item.video_id:
                        self.current_item = None
                continue

            print(f"[MUSIC] action=play_next result=ok video_id={item.video_id} title={item.title[:80]}")
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
            self.connected_guild_id = None
        try:
            if vc.is_connected():
                await vc.disconnect(force=True)
            print("[MUSIC] action=idle_disconnect result=ok")
        except Exception as e:
            print(f"[MUSIC] action=idle_disconnect result=error error={str(e)[:180]}")
