# Chunk 3 Change Summary: Lifecycle-First Cleanup (No Hard Deletes)

## What changed (concrete)
- Replaced hard-delete cleanup behavior with lifecycle transitions for memory events.
- Cleanup now transitions:
  - `active -> deprecated` for expired events (`expiry_at_utc` in the past).
  - `active -> archived` for low-importance old events based on stage threshold.
- Preserved tier maintenance and expanded it to summaries (`tier` recalculation from `end_ts/start_ts`).
- Added summary lifecycle archival for old, low-importance summaries in M2+ cleanup.
- Updated maintenance-loop logging to report lifecycle transitions instead of deletions.
- Updated auto-summary candidate query to include only `active` memory events.
- Updated topic event fetch to include only `active` memory events.
- Added tests:
  - `tests/test_memory_lifecycle_cleanup.py`

## Why it changed (rationale)
- Chunk 3 objective is auditability and reversibility: operational hiding should not destroy historical memory rows.
- Hard deletes made rollback/audit impossible and conflicted with roadmap lifecycle semantics.

Tradeoffs:
- Pros:
  - Preserves history while still reducing operational surface area.
  - Better alignment with canonical lifecycle model and future governance requirements.
- Cons:
  - Database size grows more over time than delete-based cleanup.
  - Additional lifecycle/tier rules increase cleanup complexity slightly.

## Config / operational knobs
- No new environment variables.
- Existing stage thresholds remain in effect:
  - M1-only behavior archives low-importance events older than 14 days.
  - M2+ behavior archives low-importance events older than 90 days.

## Data model / schema touchpoints
- No schema migration required for this chunk.
- Existing fields used more fully:
  - `memory_events.lifecycle`, `memory_events.expiry_at_utc`, `memory_events.tier`, `memory_events.updated_at_utc`
  - `memory_summaries.lifecycle`, `memory_summaries.tier`, `memory_summaries.updated_at_utc`

## Observability / telemetry
- Maintenance log line changed from delete-focused to transition-focused:
  - now logs `events=<n> summaries=<n>` transitions.
- Cleanup behavior can be validated by querying lifecycle state distributions over time.

## Behavioral assumptions
- Intended unchanged:
  - Retrieval paths still rely on lifecycle filtering (`active` only).
  - Tier aging windows remain consistent with prior behavior.
- Intended changed:
  - Old low-importance memory is archived/deprecated rather than deleted.
  - Auto-summary pipeline now ignores non-active events by default.

## Risks and sharp edges
- Lifecycle transitions now do more policy work; incorrect thresholds could hide too much or too little memory.
- Existing debug/admin reads that do not filter lifecycle may still show archived/deprecated rows (intentional for audit visibility).
- Summary lifecycle archiving currently targets low-importance summaries only; policy may need refinement once summary partitioning is complete.

## How to test (smoke + edge cases)
- `python -m unittest -v tests.test_memory_lifecycle_cleanup`
  - Expect `3` tests passing.
- `python -m unittest -v`
  - Expect full suite passing.
- `python -m compileall -q bot.py config controller db ingestion jobs memory misc retrieval scripts tests`
  - Expect no compile errors.
- Manual check:
  1. Insert old low-importance memory rows.
  2. Run cleanup cycle.
  3. Verify lifecycle changes to `archived` and row count remains unchanged.

## Evaluation hooks
- No new evaluation artifacts added in this chunk.
- Existing episode logging unchanged.

## Debt / follow-ups
- Chunk 4 should complete summary partitioning so lifecycle/tiering behavior can operate per scope partition cleanly.
- Add explicit admin reporting command for lifecycle state counts (active/archived/deprecated) to improve ops visibility.

## Open questions for Brian/Seri
- Should expiry-based deprecation remain immediate, or require multi-signal confirmation in some contexts?
- Should there be distinct archive windows by scope/caller context (for example, member vs leadership memories)?
