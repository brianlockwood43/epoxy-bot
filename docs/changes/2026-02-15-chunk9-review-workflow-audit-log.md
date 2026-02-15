## What changed (concrete)
- Added Chunk 9 review commands in `misc/commands/commands_memory.py`:
  - `!memreview [limit]`
  - `!memapprove <id> [tags=...] [topic=...] [importance=<0..4 or 0.0..1.0>] [note=...]`
  - `!memreject <id> [reason=...]`
- Added owner-only gates for all review commands.
- Added transactional candidate lifecycle transitions:
  - approve: `candidate -> active`
  - reject: `candidate -> deprecated`
- Added review metadata writes on `memory_events`:
  - `reviewed_by_user_id`
  - `reviewed_at_utc`
  - `review_note`
- Added `memory_audit_log` persistence with before/after snapshots for approve/reject.
- Added new lifecycle module: `memory/lifecycle_service.py`.
- Added runtime wiring for lifecycle operations via `CommandDeps` and `wire_bot_runtime`.
- Added migration `migrations/0019_memory_review_audit.py`.
- Modernized `memory_events.importance` to continuous `REAL` semantics in `[0.0, 1.0]`.
- Added test coverage:
  - `tests/test_memory_audit_log.py`
  - `tests/test_memory_review_commands.py`

## Why it changed (rationale)
- Chunk 9 makes review mode operational by adding explicit human approval/rejection workflows.
- Audit rows with before/after snapshots preserve traceability and rollback confidence.
- Owner-only access keeps review behavior conservative while procedures are new.

## Config / operational knobs
- No new env vars in this chunk.
- Permissions for review commands are owner-only.
- Review queue is global for authorized reviewers.

## Data model / schema touchpoints
- Migration: `0019_memory_review_audit.py`.
- `memory_events` additive columns:
  - `reviewed_by_user_id INTEGER`
  - `reviewed_at_utc TEXT`
  - `review_note TEXT`
- `memory_events.importance` now uses `REAL` semantics with migration-time normalization/clamp.
- New table:
  - `memory_audit_log(id, memory_id, action, actor_person_id, before_json, after_json, reason, created_at_utc)`
- New indexes:
  - `idx_memory_audit_memory_id`
  - `idx_memory_audit_created_at`

## Observability / telemetry
- Every approve/reject now writes one `memory_audit_log` row.
- Command responses confirm lifecycle transitions and applied edit summary.

## Behavioral assumptions
- Normal recall behavior is unchanged and remains active-only.
- Review commands only operate on `candidate` memories.
- Non-candidate approve/reject attempts are rejected with explicit errors.
- `!memapprove` importance supports:
  - tiers `0..4` mapped to `0.00/0.25/0.50/0.75/1.00`
  - raw float clamped to `[0.0, 1.0]`
  - omitted importance defaulting to `0.50`

## Risks and sharp edges
- Global queue is intentional for now; scope-aware queues are deferred.
- `memory_summaries.importance` remains unchanged in this chunk.

## How to test (smoke + edge cases)
- `python -m unittest -v tests.test_memory_audit_log`
- `python -m unittest -v tests.test_memory_review_commands`
- `python -m unittest -v tests.test_memory_review_mode_capture_only`
- `python -m unittest -v tests.test_memory_review_mode_all`
- `python -m unittest -v tests.test_memory_review_mode_off`
- `python -m compileall -q bot.py config controller db ingestion jobs memory misc retrieval scripts tests eval`

## Evaluation hooks
- No new eval harness in Chunk 9.
- Existing baseline eval and policy tests should remain unchanged.

## Debt / follow-ups
- Migrate `!profile` write path from `memory_events` to meta-memory store once expanded `MetaItem` layering is available; include compatibility bridge for existing profile recall.
- Consider staff-gated reviewer permissions after owner-only flow is proven stable.

## Open questions for Brian/Seri
- Should review queue filtering eventually support scope/channel subsets for large volume operations?
