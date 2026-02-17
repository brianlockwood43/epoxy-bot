# Epoxy Architecture (Current)

This document reflects the current post-refactor layout of the bot runtime.

## Goals of This Refactor

- Split the monolithic `bot.py` into focused modules.
- Keep runtime behavior unchanged while improving maintainability.
- Preserve a clean path toward the roadmap in `AGENTS.md` (memory + controller architecture).

## Module Layout

- `bot.py`
  - Process entrypoint.
  - Loads env/config.
  - Builds shared dependencies (DB connection, OpenAI client, policy sets, helper adapters).
  - Calls `wire_bot_runtime(...)` to register commands/events.

- `config/`
  - `defaults.py`: central default constants (channels, role labels, stage/topic defaults, runtime tuning defaults).
  - `announcement_templates.yml`: per-day announcement structure/tone/questions + publish target/time.

- `memory/`
  - Memory data services and store functions (events, summaries, search, topic helpers).

- `retrieval/`
  - Retrieval formatting and budget/diversity logic.

- `ingestion/`
  - Message ingestion, logging, backfill helpers, and related store functions.

- `jobs/`
  - Background maintenance and summarization jobs.
  - Announcement automation loop (`jobs/announcements.py`).

- `controller/`
  - Context classification and controller/episode-log persistence.
  - DM draft copilot parsing + orchestration (`dm_draft_parser.py`, `dm_draft_service.py`) and versioned guideline loading (`dm_guidelines.py`).

- `misc/`
  - `runtime_wiring.py`: central command/event registration orchestration.
  - `runtime_deps.py`: dataclass bundles for runtime event dependencies (`RuntimeDeps`, `RuntimeBootDeps`).
  - `commands/command_deps.py`: dataclass bundles for command registration dependencies (`CommandDeps`, `CommandGates`).
  - `events_runtime.py`: `on_ready` and `on_message` runtime handlers.
  - `mention_routes.py`: mention-mode routing helpers (default chat vs `dm:` draft mode).
  - `commands/`
    - `commands_owner.py`: owner-only commands (`!episodelogs`, `!dbmigrations`).
    - `commands_memory.py`: memory and topic commands.
    - `commands_mining.py`: mining/context/topic suggestion commands.
    - `commands_community.py`: community ops commands (welcome panel, `!lfg`).
    - `commands_announcements.py`: announcement automation commands (`!announce.*`).
    - `commands_music.py`: constrained calm/chill music commands (`!music.*`).
    - each module exposes `register(bot, *, deps: CommandDeps, gates: CommandGates)`.
  - `adhoc_modules/`
    - `announcements_service.py`: announcement template loading, draft generation, scheduler logic.
    - `announcements_store.py`: persistence helpers for announcement cycles/answers/audit logs.
    - `music_service.py`: constrained YouTube metadata/queue/voice playback orchestration.
    - `welcome_panel.py`: welcome panel view + role lookup helper.

- `db/`
  - DB bootstrap and migration runner integration.

- `migrations/`
  - Explicit SQL migration files.

- `scripts/`
  - `smoke_runtime_wiring.py`: smoke-checks command/event wiring without connecting to Discord.

## Runtime Wiring Flow

1. `bot.py` computes runtime config and dependency adapters.
2. `bot.py` calls `wire_bot_runtime(...)`.
3. `wire_bot_runtime(...)`:
   - builds `in_allowed_channel(...)`,
   - builds `CommandDeps` / `CommandGates`,
   - registers owner/memory/mining/community command groups,
   - builds `RuntimeDeps` / `RuntimeBootDeps`,
   - registers runtime events,
   - injects shared dependencies into all modules.

This keeps behavior centralized while avoiding circular imports and giant command blocks in `bot.py`.

## Owner Access and Auditability

- Owner IDs/usernames are loaded from env in `bot.py`.
- Owner-only command `!dbmigrations` shows applied schema migrations from the migration history table.
- Owner-only command `!episodelogs` shows recent controller episode logs.

## Smoke and Validation

- Compile check:
  - `python -m compileall -q bot.py config controller db ingestion jobs memory misc retrieval scripts`

- Wiring smoke test:
  - `python scripts/smoke_runtime_wiring.py`
  - Prerequisite: dependencies installed (notably `discord.py`) from `requirements.txt`.

## Announcement Ops

- Runbook:
  - `docs/announcement_automation_runbook.md`
- Environment template:
  - `.env.example`
- Developer reference (all commands + env vars):
  - `docs/developer_reference.md`

## Next Architectural Target

This refactor organizes the runtime around service boundaries so the next steps can focus on roadmap alignment (M3 stabilization, then M4 policy/meta integration) rather than structural cleanup.
