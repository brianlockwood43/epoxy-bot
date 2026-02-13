# Chunk 5 Change Summary: Apply Controller Retrieval Budgets

## What changed (concrete)
- Applied `ControllerConfig.memory_budget` to retrieval behavior in runtime mention flows and DM draft flows.
- Added budget normalization in retrieval service:
  - converts `memory_budget` into concrete `tier_caps`, `event_limit`, `summary_limit`, and search window limit.
- Updated event diversification to accept explicit tier caps from controller budget.
- Updated `recall_memory(...)` path to accept optional `memory_budget` and enforce:
  - event retrieval budget by tier (`hot/warm/cold`),
  - summary retrieval budget (`summaries`).
- Updated runtime memory-pack helper to forward `memory_budget`.
- Updated mention runtime to:
  - derive normalized budget from selected `controller_cfg`,
  - pass budget to both normal reply recall and DM-draft recall,
  - include budget metadata in runtime logging and episode implicit signals.
- Added tests:
  - `tests/test_controller_budget_application.py`

## Why it changed (rationale)
- Chunk 5 requires controller configs to materially alter retrieval behavior.
- Prior flow selected controller config but did not apply its memory budget knobs, so configs were mostly descriptive.

Tradeoffs:
- Pros:
  - Controller scope/persona now has measurable retrieval impact.
  - Budget behavior is deterministic and testable.
- Cons:
  - More coupling between controller config shape and retrieval tuning logic.
  - Misconfigured budgets can starve memory context if set too low.

## Config / operational knobs
- No new env vars.
- Existing controller config field now active:
  - `controller_configs.memory_budget_json` keys used: `hot`, `warm`, `cold`, `summaries` (with safe defaults).

## Data model / schema touchpoints
- No new migration required for this chunk.
- Existing episode log payload now includes `implicit_signals.memory_budget` in relevant runtime paths.

## Observability / telemetry
- Runtime log line now prints active budget mix for mention responses.
- Episode logs now capture applied memory budget under `implicit_signals.memory_budget`.
- This enables per-context analysis of budget vs. response quality.

## Behavioral assumptions
- Intended unchanged:
  - Scope gating and lifecycle filters still constrain retrieval first.
  - If no controller budget is provided, retrieval uses defaults equivalent to prior behavior.
- Intended changed:
  - Different controller configs now produce different event/summary counts and tier composition.

## Risks and sharp edges
- Very small budgets may over-prune context in complex requests.
- Tier caps apply after search filtering; if temporal scope is narrow (for example `hot`), effective total can be lower than `hot+warm+cold`.
- Budget keys outside expected set are ignored.

## How to test (smoke + edge cases)
- `python -m unittest -v tests.test_controller_budget_application`
  - Verifies tier mix/count differences between small/large budgets.
  - Verifies runtime helper forwards memory budget.
- `python -m unittest -v`
  - Full suite should pass.
- `python -m compileall -q bot.py config controller db ingestion jobs memory misc retrieval scripts tests`
  - No compile errors expected.

## Evaluation hooks
- No new external eval harness artifacts added.
- Episode logs now carry budget info for downstream weekly controller reporting.

## Debt / follow-ups
- Chunk 6 should apply canonical policy/meta constraints into controller retrieval shaping (beyond budget-only tuning).
- Consider adding guardrails/alerts for budget configs that collapse to near-zero usable recall.

## Open questions for Brian/Seri
- Should founder/staff contexts have higher default summary budgets than current defaults?
- Do we want per-route overrides (for example DM draft vs. general reply) on top of controller-config memory budgets?
