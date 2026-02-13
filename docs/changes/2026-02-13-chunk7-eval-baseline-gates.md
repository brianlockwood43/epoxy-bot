# Chunk 7 Change Summary: Eval Harness Baseline Gates

## What changed (concrete)
- Added new evaluation package:
  - `eval/memory_recall_baseline.py`
  - `eval/controller_policy_adherence.py`
- Added deterministic fixtures:
  - `tests/fixtures/eval_memory_recall_baseline.json`
  - `tests/fixtures/eval_controller_policy_adherence.json`
- Added baseline gate tests:
  - `tests/test_eval_memory_recall_baseline.py`
  - `tests/test_eval_controller_policy_adherence.py`
- Updated plan/docs:
  - marked Chunk 7 complete in `docs/m3-stabilization-m4-readiness-plan.md`
  - added eval gate command in `docs/developer_reference.md`

## Why it changed (rationale)
- Chunk 7 requires deterministic/replayable checks for memory and controller behavior so changes can be validated before promotion.
- The new harnesses provide fixture-backed gate reports:
  - memory recall behavior (scope, lifecycle, tier/budget, summary budget)
  - policy adherence behavior (resolved policies, directive output, enforcement clamp behavior)

Tradeoffs:
- Pros:
  - Fast, deterministic baseline checks tied to explicit fixtures.
  - Clear pass/fail report payloads for pre-promotion decision points.
- Cons:
  - Fixture scenarios are intentionally small and do not cover all production edge cases.
  - Policy adherence checks are focused on current clamp behavior and directive presence.

## Config / operational knobs
- No new env vars.
- Eval behavior is fixture-driven:
  - stage in memory fixture (`"stage": "M3"`, etc.)
  - per-case memory budgets and expected outcomes
  - per-case policy context and expected enforcement/adherence outcomes

## Data model / schema touchpoints
- No schema changes.
- Migrations: none.

## Observability / telemetry
- Harnesses return structured reports with:
  - `passed`, `failed`, `total`
  - per-case reasons and observed outputs (retrieved ids/tiers, resolved policy ids, applied clamps)
- Intended use is CI/local gating via unit tests.

## Behavioral assumptions
- Intended unchanged:
  - Production runtime behavior for retrieval and policy enforcement.
- Intended changed:
  - New baseline gate checks now fail fast when expected retrieval/policy behavior regresses.

## Risks and sharp edges
- Fixtures can become stale if policy statements or retrieval ranking heuristics change significantly.
- Memory recall gate checks exact IDs for baseline scenarios; this is useful for regression detection but sensitive to fixture setup quality.
- Policy adherence harness validates current enforcement path (mention-redaction clamp), not full semantic privacy detection.

## How to test (smoke + edge cases)
- `python -m unittest -v tests.test_eval_memory_recall_baseline tests.test_eval_controller_policy_adherence`
  - Expect both eval baseline suites to pass.
- `python -m unittest -v`
  - Full suite should pass.
- `python -m compileall -q bot.py config controller db ingestion jobs memory misc retrieval scripts tests`
  - No compile errors expected.

## Evaluation hooks
- Memory gate:
  - `eval.memory_recall_baseline.run_memory_recall_baseline_from_fixture(...)`
- Controller gate:
  - `eval.controller_policy_adherence.run_controller_policy_adherence_baseline_from_fixture(...)`
- Data source:
  - deterministic fixture files under `tests/fixtures/`

## Debt / follow-ups
- Add richer replay fixtures for contradiction-resolution and summary drill-down behavior.
- Add a small CLI wrapper for running eval gates as a single command.
- Expand controller eval coverage to include no-fly-zone leak patterns beyond mention token redaction.

## Open questions for Brian/Seri
- Should policy-adherence gates remain strict on exact statement text snippets, or should they target policy IDs/rules only?
- Do we want gate thresholds (for example minimum pass rate) for larger scenario suites before config promotion?
