# Epoxy Change Summary - 2026-02-09 M3.1 Identity Refactor

## What changed (concrete)
- [x] High-level bullet list of key changes.
- Introduced canonical identity core:
  - `people` as durable internal identity (`person_id`).
  - `person_identifiers` as external masks (`platform`, `external_id`).
- Migrated profile keying:
  - `user_profiles` is now keyed by `person_id` (legacy `id` migrated).
- Added episode person columns:
  - `person_id`, `target_person_id` (legacy `user_id`, `target_user_id` retained for compatibility).
- Updated runtime hot path:
  - mention ingress resolves actor `person_id` via deterministic mapping.
  - controller selection supports strict person-first scope.
  - DM route resolves `target_person_id` from `target_user_id` when present.
- Updated profile tag bridge:
  - `!profile` writes required `subject:person:<id>` first, plus compatibility `subject:user:<discord_id>`.
  - profile recall reads both tags and dedupes by memory id.
- [x] Public-facing behavior changes: commands/routes, parse contract fields, output schema.
- Public-facing updates:
  - `!profile` continues same command shape but now writes dual subject tags with person-first ordering.
  - DM draft route behavior is unchanged functionally, but episode instrumentation now includes `person_id` and `target_person_id`.
- [x] Name important new modules/types/functions.
- New/updated modules and functions:
  - `controller/identity_store.py`
  - `get_or_create_person_sync`
  - `resolve_person_id_sync`
  - `canonical_person_id_sync`
  - `revoke_identifier_sync`
  - `touch_person_seen_sync`
  - `dedupe_memory_events_by_id`
  - `list_person_facts_sync` (M3.1 stub, returns empty list)
- [x] Note any removed or deprecated pieces.
- Deprecated/transition notes:
  - no removals yet; legacy `user_id` paths are kept as compatibility write-through during side-by-side rollout.

## Why it changed (rationale)
- The old identity model coupled personhood to Discord user IDs, which blocked clean multi-account and cross-surface evolution.
- This change introduces deterministic canonical identity (`person_id`) while preserving backward compatibility.
- Tradeoffs:
  - Pro: future-proof core identity and cleaner joins for memory/controller/episodes.
  - Pro: safe cutover by retaining legacy user fields during transition.
  - Con: temporary dual-write/dual-read complexity until legacy dependencies are retired.
  - Con: no probabilistic linking or rich facts inference in M3.1 by design.

## Config / operational knobs
- [x] New env vars, defaults, and safe values.
- No new env vars were added for this refactor.
- [x] Feature gates / allowlists / owner-only behavior.
- Existing runtime gates/owner behavior are unchanged.
- [x] Fallback behavior when config is missing.
- Identity resolution remains deterministic and local:
  - unresolved identifiers return `None` in resolve paths.
  - creation path (`get_or_create_person_sync`) creates deterministic mappings when needed.

## Data model / schema touchpoints
- [x] Any new fields written to episode logs / artifacts (include stable key paths).
- New episode columns:
  - `episode_logs.person_id`
  - `episode_logs.target_person_id`
- Existing compatibility fields retained:
  - `episode_logs.user_id`
  - `episode_logs.target_user_id`
- [x] New enums / identifiers (e.g., mode, target_type).
- New/used identity identifiers:
  - controller config scope key: `person_id:<id>`
  - transition tag: `subject:person:<id>` (required person-first)
  - compatibility tag: `subject:user:<discord_id>` (optional write-through)
- `people.status` values supported by schema/defaults:
  - default `active`; schema also supports future states via text field and merge-chain pointer.
- [x] Migrations: none / list them.
- Migrations added:
  - `0012_people_identity_core.py`
  - `0013_user_profiles_person_id.py`
  - `0014_episode_logs_person_columns.py`
  - `0015_profile_tag_person_bridge.py`

## Observability / telemetry
- [x] What gets logged now (episode.kind, artifact keys).
- Identity telemetry additions:
  - episode writes now include actor `person_id` and DM `target_person_id` when available.
  - DM tags now include person references where available (`actor_person:*`, `target_person:*`).
- [x] Any new derived metadata (recall coverage, provenance counts).
- No new recall coverage label logic was introduced in this refactor.
- Profile recall now dedupes dual-tag hits by memory id to prevent double counting.
- [x] Where to look to verify quickly.
- Quick checks:
  - `episode_logs` columns `person_id`, `target_person_id` populated on new events.
  - `person_identifiers` active uniqueness constraint enforced.
  - profile memories include `subject:person:<id>` and may include compatibility `subject:user:<id>`.

## Behavioral assumptions
- Mention route behavior and DM draft output logic remain functionally the same.
- Existing commands remain callable with the same syntax.
- Expected subtle behavior changes:
  - controller config selection can prefer person-scoped config over legacy user-scoped config when both exist.
  - profile recall can return de-duplicated results across dual tags instead of duplicate entries.
### Identity invariants:
- (`platform`, `external_id`) resolves to exactly one active `person_id` (revocations excluded).
- `person_id` is the only canonical join key; `user_id` is compatibility-only and must not become authoritative in new readers.
- New profile memories must include `subject:person:<id>`; `subject:user:<discord_id>` is optional compatibility.

## Risks and sharp edges
- Corrupt historical data (e.g., duplicate active identifiers) can trigger warnings and require cleanup.
- Tag bridge migration depends on parseable `tags_json`; malformed rows are skipped with logging.
- Merge-chain cycles are guarded and deterministic, but a cycle warning indicates data hygiene issues to fix.
- Temporary side-by-side complexity remains until full legacy dependency removal.
- Rollback posture:
  - Legacy `user_id` fields remain written for compatibility, but rollback safety depends on whether any new readers now assume `person_id` presence. If person resolution is disabled, ensure DM/mention flows degrade gracefully rather than hard-failing.

## How to test (smoke + edge cases)
- [x] 3-5 copy/paste test prompts or commands.
- Commands/tests:
  - `python -m unittest -v tests.test_identity_refactor`
  - `python -m unittest discover -s tests -p "test_*.py" -v`
  - `python -m compileall -q controller misc migrations tests bot.py`
- [x] Expected outputs (one line each).
- Expected:
  - identity suite passes including idempotent person resolution, canonicalization, revoke semantics, migration backfills, and dual-tag dedupe.
  - full suite passes with existing `discord.py`-dependent skips unchanged.
  - compile step completes with no syntax errors.
- [x] Any special local/dev setup notes.
- Setup notes:
  - no special env required for migration unit tests; tests use SQLite in-memory connections.
  - some runtime-target tests skip when `discord.py` is not installed.
- Edge-case scenarios:
  - Create duplicate active (`platform`, `external_id`) identifiers → expect deterministic canonical resolution + warning, no new person creation.
  - Insert malformed `tags_json` on a legacy memory row → migration skips with logging; runtime recall still returns correct results via remaining valid tags.

## Evaluation hooks
- [x] Feedback commands / rating mapping.
- No new feedback command was introduced in this refactor.
- Existing DM evaluation/feedback command behavior is unchanged.
- [x] Rubric or failure-tag capture (if applicable).
- No rubric schema changes were introduced in this refactor.
- [x] Where eval data is stored.
- Existing eval-related data remains in `episode_logs` fields and `implicit_signals_json`; this refactor adds person identity join keys for analysis.

## Debt / follow-ups
- `person_facts` remains deferred in M3.1 (stub-only interface exists, no table/pipeline yet).
- Legacy `user_id` and `subject:user:*` compatibility should be retired after full person-first cutover across all readers/writers.
- Merge/split workflows are still out of scope beyond schema support (`merged_into_person_id`).
- Down-migration playbook is not implemented in this change set.

## Open questions for Brian/Seri
- When do we declare legacy `user_id` compatibility complete enough to stop writing `subject:user:*` on new profile memories?
- Should we formalize a migration checkpoint where person-scoped controller configs are required and user-scoped configs become read-only fallback?
- When should `person_facts` move from stub to real table + ingestion policy?
