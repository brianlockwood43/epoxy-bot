# Epoxy M3 Stabilization -> M4 Readiness Plan

Date: 2026-02-13
Owner: Codex + Brian
Status: In progress (Chunks 1-7 complete)

## Purpose

This document turns the roadmap gap review into an execution plan we can run chunk-by-chunk.
It prioritizes privacy/scope safety and controller wiring first, then lifecycle correctness, then M4 scaffolding.

## Priority Findings Driving This Plan

1. Retrieval scope leakage risk across contexts.
2. DM route effectively blocked by allowlist gating.
3. Memory cleanup hard-deletes instead of lifecycle transitions.
4. Summary upsert key too broad (`topic_id` only).
5. `ControllerConfig.memory_budget` not applied in retrieval flow.
6. Policy/capability mostly prompt-level, not enforced via canonical meta layer.

## Chunked Execution Plan

### Chunk 1 (P0): DM Routing + Scope Plumbing

- Goal:
  - Ensure DM interactions can pass runtime gate.
  - Ensure recall path can receive context constraints needed for safe filtering.
- Files:
  - `misc/discord_gates.py`
  - `misc/events_runtime.py`
  - `memory/runtime_recall.py`
  - `bot.py`
- Tests:
  - `tests/test_discord_gates.py` (new)
  - extend `tests/test_events_runtime_dm_route.py` for DM reachability
- Acceptance criteria:
  - DM mention route is reachable without channel allowlist membership.
  - Runtime has enough scope data to pass context-aware retrieval constraints.

### Chunk 2 (P0): Scope-Safe Retrieval by Default

- Goal:
  - Apply channel/guild/scope gates to event and summary retrieval.
  - Prevent cross-context memory bleed by default.
- Files:
  - `memory/store.py`
  - `retrieval/service.py`
  - `bot.py`
- Migrations:
  - backfill and enforce usable `scope` values where missing.
- Tests:
  - `tests/test_memory_scope_filters.py` (new)
  - `tests/test_summary_scope_filters.py` (new)
- Acceptance criteria:
  - Member/public context cannot retrieve private/unrelated channel memories unless explicitly allowed.
  - Summary retrieval obeys scope constraints.

### Chunk 3 (P1): Lifecycle-First Cleanup (No Hard Deletes)

- Goal:
  - Replace age-based hard deletes with lifecycle transitions (`active -> archived/deprecated`) and tier updates.
- Files:
  - `memory/store.py`
  - `jobs/service.py`
- Migrations:
  - optional index for lifecycle maintenance performance.
- Tests:
  - `tests/test_memory_lifecycle_cleanup.py` (new)
- Acceptance criteria:
  - Cleanup jobs preserve auditable history.
  - Expired/low-priority memory is hidden operationally without destructive loss.

### Chunk 4 (P1): Correct Summary Partitioning

- Goal:
  - Stop summary collisions across contexts by changing identity key from `topic_id` to partitioned identity.
- Files:
  - `memory/store.py`
  - `jobs/service.py`
- Migrations:
  - composite unique index (for example `topic_id + scope + summary_type`).
- Tests:
  - `tests/test_summary_upsert_partitioning.py` (new)
- Acceptance criteria:
  - Same topic in different scopes cannot overwrite each other.

### Chunk 5 (P1): Apply Controller Retrieval Budgets

- Goal:
  - Make selected `ControllerConfig.memory_budget` influence retrieval behavior.
- Files:
  - `misc/events_runtime.py`
  - `memory/runtime_recall.py`
  - `retrieval/service.py`
- Tests:
  - `tests/test_controller_budget_application.py` (new)
- Acceptance criteria:
  - Different configs produce measurably different recall mixes/limits.

### Chunk 6 (P1): M4 Canonical Meta Scaffolding + Policy Enforcement Path

- Goal:
  - Introduce canonical `MetaItem` + `Link` persistence and runtime policy resolution hook.
- Files:
  - `memory/meta_store.py` (new)
  - `memory/meta_service.py` (new)
  - `misc/events_runtime.py`
  - `migrations/` (new migration files)
- Tests:
  - `tests/test_meta_policy_resolution.py` (new)
  - `tests/test_policy_enforcement_runtime.py` (new)
- Acceptance criteria:
  - Policy constraints are resolved from canonical stored objects (not only prompt text).

### Chunk 7 (P2): Eval Harness Baseline Gates

- Goal:
  - Add deterministic/replayable evaluation checks for memory + controller behavior changes.
- Files:
  - `eval/` (new package)
  - `tests/fixtures/` (new fixtures)
- Tests:
  - `tests/test_eval_memory_recall_baseline.py` (new)
  - `tests/test_eval_controller_policy_adherence.py` (new)
- Acceptance criteria:
  - Config/policy changes can be validated before promotion.

## Recommended Order

1. Chunk 1
2. Chunk 2
3. Chunk 3
4. Chunk 4
5. Chunk 5
6. Chunk 6
7. Chunk 7

## Operating Rules For This Plan

1. Ship each chunk as its own small PR-sized change.
2. Add tests in the same chunk that introduces behavior changes.
3. Run validation each chunk:
   - `python -m compileall -q bot.py config controller db ingestion jobs memory misc retrieval scripts tests`
   - `python -m unittest -v`
4. For each non-trivial chunk, add a change summary in `docs/changes/` using `docs/epoxy_change_summary_template.md`.

## Current Execution State

- Chunk 1: completed (2026-02-13)
  - Delivered: DM gate fix, scope composer, runtime wiring, tests, docs update.
- Chunk 2: completed (2026-02-13)
  - Delivered: scope-aware event/summary retrieval filters, lifecycle active-only retrieval guard, scope defaults on memory write paths, command scope token composition (`!recall`, `!memfind`), migration `0016_scope_backfill_hardening.py`, and new scope/lifecycle tests.
  - Known carry-forward risk: current M3 summary generation writes mostly `global` scope while scoped recalls prioritize context scopes; this is privacy-safe but reduces summary recall hit rate until scope-partitioned summaries (Chunk 4).
- Chunk 3: pending
- Chunk 3: completed (2026-02-13)
  - Delivered: cleanup now performs lifecycle transitions (`active -> archived/deprecated`) instead of hard deletes, keeps tier maintenance, updates maintenance logging semantics, and excludes non-active events from auto-summary candidate scans.
  - Validation: added lifecycle cleanup test coverage for no-delete archival behavior, expiry-driven deprecation, and active-only topic event selection.
- Chunk 4: completed (2026-02-13)
  - Delivered: summary identity is now partitioned by `(topic_id, scope, summary_type)` across reads/writes, including scope-aware topic lookup and summarize flows.
  - Added migration `0017_summary_partition_uniqueness.py` with active-partition unique index and duplicate-active backfill handling.
  - Added tests for partition behavior and uniqueness enforcement.
- Chunk 5: completed (2026-02-13)
  - Delivered: `ControllerConfig.memory_budget` is now applied to retrieval limits and tier mix in mention runtime and DM draft flows.
  - Added deterministic budget application tests to verify different configs produce different recall counts/mixes and that runtime pack-building forwards budget controls.
- Chunk 6: completed (2026-02-13)
  - Delivered: canonical meta persistence (`meta_items`) + link persistence (`memory_links`) with migration-backed policy seeds and runtime policy-resolution hook.
  - Mention runtime now resolves policies from canonical storage and applies a concrete member-facing enforcement clamp path.
  - Added tests for meta-policy resolution and runtime enforcement behavior.
- Chunk 7: completed (2026-02-13)
  - Delivered: deterministic/replayable eval harness modules under `eval/` for memory recall baselines and controller policy-adherence baselines.
  - Added fixture-backed gate tests under `tests/test_eval_memory_recall_baseline.py` and `tests/test_eval_controller_policy_adherence.py`.
  - Added reusable fixtures under `tests/fixtures/` so retrieval/policy behavior changes can be validated before config or policy promotion.
