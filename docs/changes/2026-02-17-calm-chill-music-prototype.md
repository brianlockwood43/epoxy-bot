# Change Summary: Calm/Chill YouTube Music Prototype

Date: 2026-02-17

## What shipped

1. Added constrained `!music.*` command surface:
- `music.start`, `music.stop`, `music.skip`, `music.pause`, `music.resume`, `music.clearqueue`, `music.forcequeue`
- `music.queue`, `music.queue_list`, `music.now`, `music.status`

2. Added new ad-hoc music service:
- `misc/adhoc_modules/music_service.py`
- in-memory queue/session state only (no schema changes)
- YouTube URL normalization (`youtube.com/watch` + `youtu.be`)
- metadata heuristic gating for calm genres (allow/deny keywords + duration/category checks)
- voice playback pipeline via FFmpeg + `discord.py` voice client

3. Added runtime wiring:
- `misc/commands/commands_music.py`
- `misc/runtime_wiring.py` integration
- `CommandDeps.music_service`
- `bot.py` env parsing + service construction + wiring

4. Added configuration/docs:
- `.env.example` music env vars
- `docs/developer_reference.md` command + env docs
- `docs/music_runbook.md`
- `docs/architecture.md` module map update

5. Added tests/scaffolding:
- `tests/test_music_service.py`
- `tests/test_music_commands.py`
- `scripts/smoke_runtime_wiring.py` expected command set update

## Safety and constraints

1. Feature is disabled unless:
- `EPOXY_MUSIC_ENABLED=1`
- `EPOXY_MUSIC_RISK_ACK=I_ACCEPT_YOUTUBE_RISK`

2. Commands are constrained to one configured text channel, playback to one configured voice channel.

3. Operator-only transport controls; non-operators can queue/read status in constrained channel.

4. No memory/controller DB writes added.

## Known operational prerequisites

1. Runtime must include:
- `yt-dlp`
- `PyNaCl`
- FFmpeg binary

2. In environments without `discord.py`, command tests and smoke wiring checks skip.
