# Chunk 2 Change Summary: Scope-Safe Retrieval Defaults

## What changed (concrete)
- Enforced context-aware scope filtering in memory event retrieval.
- Enforced context-aware scope filtering in summary retrieval.
- Added lifecycle guard (`active` only) for events and summaries during retrieval.
- Added scope persistence defaults on new memory events.
- Updated summary upsert behavior to include `scope` + `summary_type` in lookup/update semantics.
- Updated command recall paths (`!recall`, `!memfind`) to include channel/guild scope tokens by default.
- Added migration `0016_scope_backfill_hardening.py` to backfill missing scope/lifecycle data.
- Added tests:
  - `tests/test_memory_scope_filters.py`
  - `tests/test_summary_scope_filters.py`

## Why it changed (rationale)
- Prior retrieval paths could return memories across unrelated channels/contexts unless explicit scope tokens were present.
- Summary retrieval previously had no scope gating at all.
- Scope-safe defaults are required for privacy and contextual boundary integrity.

Tradeoffs:
- Pros:
  - Stronger default privacy boundaries.
  - Deterministic scope behavior in both mention and command recall flows.
- Cons:
  - Scoped contexts will now see fewer summary hits when legacy summaries are globally scoped or improperly scoped.
  - Some previously visible cross-channel memories are intentionally no longer returned.

## Config / operational knobs
- No new env vars.
- Behavior change:
  - Contextual recall now composes scope tokens from runtime context and command context.

## Data model / schema touchpoints
- Migration added:
  - `migrations/0016_scope_backfill_hardening.py`
- Backfills:
  - `memory_events.scope` from `channel_id/guild_id/global` when missing.
  - `memory_events.lifecycle` -> `active` when missing.
  - `memory_summaries.scope` -> `global` when missing or `topic:*` legacy values.
  - `memory_summaries.lifecycle` -> `active` when missing.
- Indexes reinforced:
  - `idx_mem_events_scope`, `idx_mem_events_lifecycle`
  - `idx_mem_summaries_scope`, `idx_mem_summaries_lifecycle`

## Observability / telemetry
- No new episode log keys.
- Scope effect can be observed by comparing recall results from different channels for same query.

## Behavioral assumptions
- Intended unchanged:
  - FTS query behavior and tier budgeting logic remain intact.
  - Command syntax unchanged.
- Intended changed:
  - `!recall` and `!memfind` now default to context-scoped retrieval.
  - Mention recall returns only context-matching events/summaries by default.

## Risks and sharp edges
- Legacy summary coverage may appear reduced in scoped contexts due stricter filtering.
- Summary scope semantics are safer but still coarse until chunk 4 summary partitioning is completed.
- Cross-channel analysis use cases may need explicit future pathways rather than implicit retrieval bleed.

## How to test (smoke + edge cases)
- `python -m unittest -v`
  - Expect passing tests; includes new scope filter coverage.
- `python -m compileall -q bot.py config controller db ingestion jobs memory misc retrieval scripts tests`
  - Expect no compile errors.
- Manual checks:
  1. Save similar memories in two channels.
  2. Run `!recall` in channel A.
  3. Verify channel B memory is not returned.

## Evaluation hooks
- Existing episode log flow unchanged.
- Existing owner feedback/eval commands unchanged.

## Debt / follow-ups
- Chunk 3: lifecycle cleanup should stop hard deletes and move to archival transitions.
- Chunk 4: summary partitioning by `(topic_id, scope, summary_type)` at schema/index level should be finalized.
- Future: controlled/explicit cross-scope retrieval for authorized contexts.

## Open questions for Brian/Seri
- Should founder/leadership contexts get an explicit opt-in cross-scope retrieval mode with strict policy controls?
- For summaries, should `global` ever be allowed in scoped recalls, or should that remain blocked by default indefinitely?
