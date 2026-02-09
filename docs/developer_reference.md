# Epoxy Developer Reference

This file is the maintained developer reference for:

- full command documentation (`!` commands),
- full environment variable documentation (`os.getenv`-driven runtime config).

Use this with:

- `docs/architecture.md` (module layout/runtime flow),
- `docs/announcement_automation_runbook.md` (announcement rollout and daily ops),
- `.env.example` (starter env template).

## Command Conventions

- Prefix: `!`
- Most commands are restricted to `allowed channels` (from `EPOXY_ALLOWED_CHANNEL_IDS` or `config/defaults.py` fallback).
- Announcement commands also work inside threads whose parent is an allowed channel.
- “Owner-only” checks use `EPOXY_OWNER_USER_IDS` / `EPOXY_OWNER_USERNAMES`.

---

## Commands

### Owner Commands

1. `!episodelogs [limit]`
- Access: owner-only, allowed channels
- Default: `limit=20` (clamped `1..100`)
- Purpose: show recent controller episode logs

2. `!dbmigrations [limit]`
- Access: owner-only, allowed channels
- Default: `limit=30` (clamped `1..200`)
- Purpose: show applied DB schema migrations

3. `!dmfeedback <keep|edit|sent|discard> [note]`
- Access: owner-only, allowed channels
- Purpose: attach explicit outcome signal to the latest DM draft episode log

4. `!dmeval tone_fit=<0|1|2> de_escalation=<0|1|2> agency_respect=<0|1|2> boundary_clarity=<0|1|2> actionability=<0|1|2> context_honesty=<0|1|2> [tags=<...>] [| note]`
- Access: owner-only, allowed channels
- Purpose: attach rubric scores and failure tags to the latest DM draft episode log
- Allowed tags:
  - `too_long`, `too_vague`, `too_harsh`, `too_soft`, `too_therapyspeak`, `misses_ask`, `invents_facts`

### Memory Commands

1. `!memstage`
- Access: allowed channels
- Purpose: show memory stage and capture/summary toggles

2. `!topics [limit]`
- Access: allowed channels
- Default: `limit=15` (clamped `1..30`)
- Purpose: show topic allowlist and topic counts

3. `!remember <tags>|<text>`
4. `!remember <text>`
5. `!remember tags=<...> importance=<0|1> text=<...>`
- Access: allowed channels
- Requires: memory stage `M1+`
- Purpose: create memory event manually

6. `!recall <query>`
- Access: allowed channels
- Requires: memory stage `M1+`
- Purpose: retrieve relevant memory events/summaries

7. `!topic <topic_id>`
- Access: allowed channels
- Requires: memory stage `M3`
- Purpose: fetch stored topic summary

8. `!summarize <topic_id> [min_age_days]`
- Access: allowed channels
- Requires: memory stage `M3`
- Default: `min_age_days=14`
- Purpose: force-generate topic summary

9. `!profile @User | <text>`
- Access: allowed channels
- Purpose: store per-user profile memory notes

10. `!memlast [n]`
- Access: allowed channels
- Default: `n=5`
- Purpose: debug view of latest memory events

11. `!memfind <query>`
- Access: allowed channels
- Purpose: quick recall debug output

### Mining Commands

1. `!mine [<#channel|channel_id>] [limit] [duration]`
- Access: allowed channels only
- Requires: memory stage `M1+`
- `limit`: clamped `50..500` (default `200`)
- `duration` tokens:
  - `hot` / `--hot` -> `30m`
  - `<N>m`, `<N>h` (for example `45m`, `2h`)
- Purpose: extract candidate durable memories from message windows

2. `!ctxpeek [n]`
- Access: allowed channels
- Default: `n=10` (clamped `1..40`)
- Purpose: view recent context rows used for prompting

3. `!topicsuggest [<#channel|channel_id>] [limit] [duration] [mem|memory|memories]`
- Access: allowed channels only
- Purpose: suggest new topic IDs from message or memory windows

### Community Commands

1. `!setup_welcome_panel`
- Access: guild-only, administrator permission, must run in `WELCOME_CHANNEL_ID`
- Purpose: post welcome panel embed/buttons

2. `!lfg public <message>`
3. `!lfg members <message>`
- Access: guild-only, must run in `LFG_SOURCE_CHANNEL_ID`, requires member role
- Purpose: post LFG ping to configured destination channel

### Announcement Commands

1. `!announce.status [YYYY-MM-DD]`
- Access: allowed channels or allowed-channel threads
- Purpose: show cycle status/details for date (`today` default)

2. `!announce.answers [YYYY-MM-DD]`
- Access: allowed channels or allowed-channel threads
- Purpose: show collected answers (`today` default)

3. `!announce.answer <question_id> | <answer>`
- Access: allowed channels or allowed-channel threads
- Purpose: set answer for active cycle (thread-scoped date resolution supported)

4. `!announce.generate [YYYY-MM-DD]`
- Access: allowed channels or allowed-channel threads
- Purpose: generate draft from template + answers (+ memory if `M1+`)

5. `!announce.override | <full_text>`
- Access: allowed channels or allowed-channel threads
- Purpose: set final override text

6. `!announce.clear_override [YYYY-MM-DD]`
- Access: allowed channels or allowed-channel threads
- Purpose: clear override text

7. `!announce.approve [YYYY-MM-DD]`
- Access: owner-only, allowed channels or allowed-channel threads
- Purpose: approve cycle for scheduled bot posting

8. `!announce.unapprove [YYYY-MM-DD]`
- Access: owner-only, allowed channels or allowed-channel threads
- Purpose: revert `approved -> draft_ready`

9. `!announce.done [self|draft] [message_link] | [note]`
- Access: owner-only, allowed channels or allowed-channel threads
- Default mode: `self` when omitted
- Modes:
  - `self` -> `manual_self_posted`
  - `draft` -> `manual_draft_posted`
- Purpose: mark day completed manually; suppress scheduled auto-post

10. `!announce.undo_done [YYYY-MM-DD]`
- Access: owner-only, allowed channels or allowed-channel threads
- Constraint: only before publish cutoff
- Purpose: revert `manual_done` to previous non-terminal status

11. `!announce.post_now [YYYY-MM-DD]`
- Access: owner-only, allowed channels or allowed-channel threads
- Purpose: force immediate post path for approved cycle

---

## Environment Variables

`ID/username list format`: comma, space, or semicolon separated values.

### Core Runtime

1. `DISCORD_TOKEN`
- Required
- Discord bot token

2. `OPENAI_API_KEY`
- Required
- OpenAI API key

3. `OPENAI_MODEL`
- Default: `gpt-5.1`
- Chat completion model

### Memory Stage + Capture

1. `EPOXY_MEMORY_STAGE`
- Default: `M0`
- Values used: `M0 | M1 | M2 | M3`

2. `EPOXY_MEMORY_ENABLE_AUTO_CAPTURE`
- Default: `0`
- `1` enables automatic memory capture patterns

3. `EPOXY_MEMORY_ENABLE_AUTO_SUMMARY`
- Default: `0`
- `1` enables automatic summary jobs

4. `EPOXY_BOOTSTRAP_BACKFILL_CAPTURE`
- Default: `0`
- Enable auto-capture during bootstrap history backfill

5. `EPOXY_BOOTSTRAP_CHANNEL_RESET`
- Default: `0`
- Reset channel backfill state before per-channel backfill

6. `EPOXY_BOOTSTRAP_CHANNEL_RESET_ALL`
- Default: `0`
- Reset all channel backfill flags on startup

### Topics

1. `EPOXY_TOPIC_SUGGEST`
- Default: `0`
- Enable topic suggestion classifier

2. `EPOXY_TOPIC_MIN_CONF`
- Default: `0.85`
- Minimum confidence for suggestion acceptance

3. `EPOXY_TOPIC_ALLOWLIST`
- Default: `config/defaults.py` topic list
- If explicitly set to empty string: no explicit allowlist; fallback to known DB topics

### Database

1. `EPOXY_DB_PATH`
- Default: `epoxy_memory.db`
- SQLite path

### Access Control + Context Grouping

1. `EPOXY_ALLOWED_CHANNEL_IDS`
- Optional override for command/runtime allowlist
- If empty/unset: fallback to `DEFAULT_ALLOWED_CHANNEL_IDS`

2. `EPOXY_LEADERSHIP_CHANNEL_IDS`
3. `EPOXY_STAFF_CHANNEL_IDS`
4. `EPOXY_MEMBER_CHANNEL_IDS`
5. `EPOXY_PUBLIC_CHANNEL_IDS`
- Optional channel grouping for context classification/policy surface

### Owner / Founder Identity

1. `EPOXY_OWNER_USER_IDS`
- Default: `237008609773486080`
- Primary owner gate for sensitive commands

2. `EPOXY_OWNER_USERNAMES`
- Default: `blockwood43`
- Fallback owner identity gate when owner IDs list is empty

3. `EPOXY_FOUNDER_USER_IDS`
- Optional
- If unset and owner IDs present, founders fallback to owner IDs

### Episode Logging

1. `EPOXY_ENABLE_EPISODE_LOGGING`
- Default: `1`
- Toggle controller episode logging

2. `EPOXY_EPISODE_LOG_SURFACES`
- Legacy variable. Used only when `EPOXY_EPISODE_LOG_FILTERS` is unset.

3. `EPOXY_EPISODE_LOG_FILTERS`
- Default: `context:dm,context:public,context:member,context:staff,context:leadership`
- Dimension-aware allowlist for episode logs.
- Supported selectors:
  - `context:<dm|public|member|staff|leadership|unknown>`
  - `caller:<founder|core_lead|coach|member|external>`
  - `surface:<dm|coach_channel|public_channel|system_job>`
- `all` logs every context.
- Bare tokens are also accepted for backward compatibility (for example: `dm`, `coach_channel`, `member`, `founder`).

For DM draft episodes, `implicit_signals_json` includes structured artifact keys:
- `episode.kind = "dm_draft"`
- `episode.artifact.dm.parse = {...}`
- `episode.artifact.dm.result = {...}`
- DM draft `recall_coverage` metadata retains fixed threshold labels (`thin|mixed|rich`) and includes provenance bucket counts:
  - `target_profile_count`
  - `recent_dm_count`
  - `public_interaction_count`
  - `notes_count`
  - `policy_count`
- Episode logs now also persist first-class DM target fields:
  - `target_user_id`
  - `target_display_name`
  - `target_type` (`member|staff|external|self|unknown`)
  - `target_confidence` (set when target identity/type is inferred)
  - `target_entity_key` (stable fallback join key; for example `discord:123...`, `member:caleb`, `external:chloe`)
- Episode logs also persist first-class mode audit fields:
  - `mode_requested` (explicit mode input or `null`)
  - `mode_inferred` (heuristic mode)
  - `mode_used` (final mode applied)
- Episode logs also persist first-class blocking-collab audit fields:
  - `blocking_collab` (`true|false`)
  - `critical_missing_fields` (list)
  - `blocking_reason` (for example `missing_target`, `missing_objective`, `missing_non_negotiables_boundary_context`)
- Episode logs also persist DM guideline provenance fields:
  - `dm_guidelines_version` (loaded guideline version/hash marker)
  - `dm_guidelines_source` (`file|fallback|env_override`)
- Episode logs also persist draft lineage fields:
  - `draft_version` (for example `1.1`)
  - `draft_variant_id` (`primary` in v1 single-draft flow; future-ready for multi-variant)
  - `prompt_fingerprint` (sha256 hash of normalized DM request used for generation)

### DM Draft Copilot

1. Mention mode: `@Epoxy dm: ...`
- Access: owner-only mode
- Purpose: high-emotional-load DM drafting with structured parse:
  - `target`
  - `objective`
  - `situation_context`
  - `my_goals`
  - `non_negotiables`
  - `tone`
  - optional `mode` (`auto|collab|best_effort`; supports `mode:` and `mode=`)
- Collab behavior:
  - default: draft + up to 2 concise follow-up questions
  - conditional blocking before draft if critical fields are missing:
    - missing `target`
    - missing `objective`
    - missing `non_negotiables` when context implies boundary/safety risk

2. `EPOXY_DM_GUIDELINES_PATH`
- Default: `config/dm_guidelines.yml`
- Versioned policy/guideline source for DM drafting behavior

### Maintenance + Summaries

1. `EPOXY_MAINTENANCE_INTERVAL_SECONDS`
- Default: `3600`
- Memory maintenance loop interval

2. `EPOXY_SUMMARY_MIN_AGE_DAYS`
- Default: `14`
- Minimum age for auto-summarized events

### Backfill + Context Window Tuning

1. `EPOXY_BACKFILL_LIMIT`
- Default: `DEFAULT_BACKFILL_LIMIT` (`2000`)
- Per-channel history rows for bootstrap backfill

2. `EPOXY_RECENT_CONTEXT_LIMIT`
- Default: `DEFAULT_RECENT_CONTEXT_LIMIT` (`40`)
- Recent context rows loaded for mentions

3. `EPOXY_RECENT_CONTEXT_CHARS`
- Default: `DEFAULT_RECENT_CONTEXT_MAX_CHARS` (`6000`)
- Max chars for context block

4. `EPOXY_RECENT_CONTEXT_LINE_CHARS`
- Default: `DEFAULT_RECENT_CONTEXT_LINE_CHARS` (`600`)
- Per-line truncation size

### Announcement Automation (v1.1)

1. `EPOXY_ANNOUNCE_ENABLED`
- Default: `0`
- Master toggle for announcement loop/commands integration

2. `EPOXY_ANNOUNCE_DRY_RUN`
- Default: `0`
- If `1`, posting path records transitions without sending live post

3. `EPOXY_ANNOUNCE_TIMEZONE`
- Default: `UTC`
- Timezone for prep/publish scheduling

4. `EPOXY_ANNOUNCE_PREP_TIME_LOCAL`
- Default: `09:00`
- Daily prep ping trigger time (`HH:MM`)

5. `EPOXY_ANNOUNCE_PREP_CHANNEL_ID`
- Default: `1412603858835738784`
- Prep host channel ID (required for practical use)

6. `EPOXY_ANNOUNCE_PREP_ROLE_NAME`
- Default: empty
- Optional role name to mention in prep ping

7. `EPOXY_ANNOUNCE_TICK_SECONDS`
- Default: `30`
- Announcement loop tick interval

8. `EPOXY_ANNOUNCE_TEMPLATES_PATH`
- Default: `config/announcement_templates.yml`
- Template file path override

---

## Operational Tips

1. Start announcement rollout with:
- `EPOXY_ANNOUNCE_ENABLED=1`
- `EPOXY_ANNOUNCE_DRY_RUN=1`

2. Validate command wiring after refactors:
- `python scripts/smoke_runtime_wiring.py`

3. Validate runtime import/syntax:
- `python -m compileall -q bot.py config controller db ingestion jobs memory misc retrieval scripts tests`

4. Validate test suite:
- `python -m unittest -v`

---

## Docs Maintenance Checklist

When shipping any runtime or behavior change, update docs in the same PR.

1. Command surface changes:
- If adding/removing/renaming a `@bot.command`, update the relevant command section here.
- Include usage format, access scope, and owner-only status.
- If command behavior changed (defaults, validation, target resolution), update that note too.

2. Environment variable changes:
- If adding/changing/removing any `os.getenv(...)` key, update the env table here.
- Include default value, accepted format, and operational impact.
- If a var was deprecated, keep a short deprecation note for one release cycle.

3. Schema/migration changes:
- If adding a migration that changes runtime behavior, add a short note under this file’s operational tips.
- If the change is announcement-specific, also update `docs/announcement_automation_runbook.md`.

4. Runtime flow changes:
- If module wiring/startup behavior changes, update `docs/architecture.md`.
- Keep module paths and runtime flow steps aligned with actual imports/wiring.

5. Rollout and ops changes:
- If rollout steps changed, update `.env.example` and `docs/announcement_automation_runbook.md`.
- Keep dry-run/live guidance synchronized across docs.

6. Validation before merge:
- Run:
  - `python -m compileall -q bot.py config controller db ingestion jobs memory misc retrieval scripts tests`
  - `python -m unittest -v`
- Confirm command docs and env docs still match current code paths.
