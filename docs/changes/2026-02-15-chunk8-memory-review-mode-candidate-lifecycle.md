## What changed (concrete)
- Added `EPOXY_MEMORY_REVIEW_MODE=off|capture_only|all` runtime config, defaulting to `capture_only`.
- Added lifecycle routing on memory writes by source path:
  - `manual_remember`
  - `manual_profile`
  - `auto_capture`
  - `mining`
- Extended `!remember` with optional `force_active=1` (owner-only).
- Updated memory inserts to persist explicit `lifecycle` from payload.
- Updated `!memstage` output to include `REVIEW_MODE`.
- Added test coverage:
  - `tests/test_memory_review_mode_capture_only.py`
  - `tests/test_memory_review_mode_all.py`
  - `tests/test_memory_review_mode_off.py`

## Why it changed (rationale)
- Chunk 8 requires review-gated memory capture while preserving existing recall safety.
- Candidate-first capture for non-`!remember` paths reduces accidental promotion of mined/automated/profile content.
- Owner-only override allows intentional operational exceptions in `all` mode without opening broad bypasses.

## Config / operational knobs
- New env var: `EPOXY_MEMORY_REVIEW_MODE`.
- Allowed values: `off`, `capture_only`, `all`.
- Default/fallback: `capture_only`.
- Invalid values log a warning and fall back to `capture_only`.
- `!remember force_active=1` is owner-only.

## Data model / schema touchpoints
- No migration required.
- Existing `memory_events.lifecycle` column is now explicitly written on insert.

## Observability / telemetry
- Startup config log now includes `review_mode=<value>`.
- `!memstage` now shows `REVIEW_MODE=<value>`.
- `!remember` response now echoes saved `lifecycle`.

## Behavioral assumptions
- Recall behavior remains active-only (`candidate` memories are not returned in normal recall).
- `capture_only` behavior:
  - `!remember` -> `active`
  - auto-capture/mining/`!profile` -> `candidate`
- `all` behavior:
  - default -> `candidate`
  - `!remember force_active=1` by owner -> `active`

## Risks and sharp edges
- Operators may forget `force_active=1` in `all` mode and wonder why memories are not recalled.
- `!profile` still writes into `memory_events` in Chunk 8 by design; this is a temporary architectural compromise.

## How to test (smoke + edge cases)
- `python -m unittest -v tests.test_memory_review_mode_capture_only`
- `python -m unittest -v tests.test_memory_review_mode_all`
- `python -m unittest -v tests.test_memory_review_mode_off`
- `python -m unittest -v`
- `python -m compileall -q bot.py config controller db ingestion jobs memory misc retrieval scripts tests eval`

## Evaluation hooks
- No new eval harness introduced in Chunk 8.
- Existing baseline eval suites remain unchanged and should stay green.

## Debt / follow-ups
- Future follow-up: route !profile writes to meta-memory (MetaItem-based person/relational layer) instead of memory_events. Keep !profile on memory_events during Chunk 8 for safety/minimal diff; migrate after meta-layer expansion is in place.
- Migrate !profile write path from memory_events to meta-memory store once expanded MetaItem layering is available; include compatibility bridge for existing profile recall.

## Chunk 8 behavior remains unchanged
- `capture_only`: only `!remember` is active; `!profile` remains `candidate` (for now).
- This addendum is documentation and roadmap alignment, not a Chunk 8 implementation expansion.

## Open questions for Brian/Seri
- For the future `!profile` migration, should profile recall read from both legacy `memory_events` and new meta-memory during transition, or cut over with one-time backfill?
