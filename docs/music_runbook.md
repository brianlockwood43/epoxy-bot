# Calm/Chill Music Runbook (YouTube Prototype)

This runbook covers setup and safe rollout for `!music.*`.

## 1) Configure Environment

Required:

- `EPOXY_MUSIC_ENABLED=1`
- `EPOXY_MUSIC_RISK_ACK=I_ACCEPT_YOUTUBE_RISK`
- `EPOXY_MUSIC_TEXT_CHANNEL_ID=<calm_text_channel_id>`
- `EPOXY_MUSIC_VOICE_CHANNEL_ID=<calm_voice_channel_id>`
- `EPOXY_MUSIC_GENERAL_VOICE_CHANNEL_ID=1411275538978308246` (or your desired general voice channel)
- `EPOXY_MUSIC_PLAYLIST_MAX_ITEMS=10` (recommended initial cap)

Recommended initial rollout:

- `EPOXY_MUSIC_DRY_RUN=1`
- `EPOXY_MUSIC_OPERATOR_USER_IDS=<owner_or_staff_ids>`

## 2) Dependencies

- Install Python deps: `yt-dlp`, `PyNaCl`
- Ensure FFmpeg is available in runtime image/path
- Railway/Nixpacks default path: include repo `nixpacks.toml` with `ffmpeg` in setup packages
  - Alternative: set Railway build env `NIXPACKS_PKGS=ffmpeg`

If FFmpeg is missing, voice playback commands fail at runtime.

## 3) Dry-Run Validation

With dry-run enabled:

1. Run `!music.status` and confirm feature is enabled.
2. Test channel gate:
   - run `!music.queue <url>` inside calm channel (should process)
   - run `!music.queue <playlist_url>` and confirm capped expansion behavior
   - run same outside calm channel (should reject)
3. Test role gate:
   - non-operator should be blocked from `!music.start`
4. Test queue controls:
   - `!music.queue`, `!music.queue_list`, `!music.now`

## 4) Live Canary

Switch:

- `EPOXY_MUSIC_DRY_RUN=0`

Then:

1. Operator runs `!music.start` (calm) or `!music.start general`
2. Members queue links via `!music.queue <youtube_url>`
3. Operator tests transport:
   - `!music.skip`
   - `!music.pause`
   - `!music.resume`
4. Confirm idle disconnect after queue drains

## 5) Immediate Rollback

Set:

- `EPOXY_MUSIC_ENABLED=0`

Restart bot. All `!music.*` commands return disabled state.
