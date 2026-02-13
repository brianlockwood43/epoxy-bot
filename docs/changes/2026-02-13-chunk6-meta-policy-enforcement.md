# Chunk 6 Change Summary: M4 Meta Scaffolding + Policy Enforcement Path

## What changed (concrete)
- Added canonical meta persistence module:
  - `memory/meta_store.py`
  - supports `MetaItem` upsert/list, policy bundle resolution, and `Link` insertion.
- Added runtime meta/policy service module:
  - `memory/meta_service.py`
  - formats policy directives and applies member-facing enforcement clamps.
- Added migration:
  - `migrations/0018_meta_items_links_policy_seed.py`
  - creates `meta_items` and `memory_links` tables + indexes
  - seeds baseline policy rows scoped to existing sensitivity policy IDs.
- Wired runtime policy resolution into mention handling:
  - resolve policy bundle from canonical store based on `sensitivity_policy_id`, `caller_type`, `surface`
  - append canonical policy directive text to controller directive
  - apply enforcement clamp before sending output in mention flows
  - log resolved policy ids and applied clamps in episode implicit signals.
- Added runtime wiring/deps integration:
  - `misc/runtime_deps.py`
  - `misc/runtime_wiring.py`
  - `bot.py` wrappers and wiring.
- Added tests:
  - `tests/test_meta_policy_resolution.py`
  - `tests/test_policy_enforcement_runtime.py`

## Why it changed (rationale)
- Chunk 6 requires policy constraints to come from canonical stored objects, not only prompt text.
- This adds an explicit policy retrieval path and a concrete enforcement hook in runtime.

Tradeoffs:
- Pros:
  - Policy behavior is now inspectable/auditable in DB (`meta_items`) and in episode logs.
  - Runtime has a deterministic enforcement path for member-facing privacy guardrails.
- Cons:
  - Enforcement clamp is intentionally conservative and currently narrow (mention-token redaction).
  - More runtime dependencies and wiring complexity.

## Config / operational knobs
- No new environment variables.
- Policy behavior now depends on active rows in `meta_items` for relevant scopes (`policy:*`, `global`, caller/surface scopes).

## Data model / schema touchpoints
- New tables:
  - `meta_items`
  - `memory_links`
- Seeded policy scopes:
  - `policy:member_privacy`
  - `policy:public_safe`
  - `policy:dm_privacy`
  - `policy:staff_confidential`
  - `policy:leadership_confidential`
  - `policy:default`
- New episode implicit fields in runtime:
  - `resolved_policy_ids`
  - `applied_policy_clamps`

## Observability / telemetry
- Runtime now logs policy-driven enforcement side effects via episode implicit signals.
- Policy resolution output can be inspected directly with `meta_items` queries.

## Behavioral assumptions
- Intended unchanged:
  - Existing context classification and controller config selection flow.
  - Existing retrieval/lifecycle enforcement behavior.
- Intended changed:
  - Controller directive now includes policy text resolved from canonical meta store.
  - Member-facing outputs may be clamped via mention redaction when policy rules require it.

## Risks and sharp edges
- Current enforcement clamp only handles Discord mention token redaction; other private-detail leak patterns remain policy-guided but not hard-clamped yet.
- Overly broad seeded policies could cause over-redaction in member/public contexts if future output formats rely on mention tokens.

## How to test (smoke + edge cases)
- `python -m unittest -v tests.test_meta_policy_resolution tests.test_policy_enforcement_runtime`
  - Expect policy resolution + clamp behavior tests to pass.
- `python -m unittest -v`
  - Full suite should pass.
- `python -m compileall -q bot.py config controller db ingestion jobs memory misc retrieval scripts tests`
  - No compile errors expected.

## Evaluation hooks
- Episode logs now capture policy resolution/enforcement metadata in implicit signals.
- Existing feedback/eval commands remain unchanged.

## Debt / follow-ups
- Expand machine-checkable policy rules beyond mention redaction (for example sensitive phrase/risk classifiers).
- Add owner/staff commands to create/edit/link meta items and policies directly (manual M4 management UX).
- Consider policy conflict-resolution reporting tooling for transparency.

## Open questions for Brian/Seri
- Should member/public clamp behavior block-and-ask instead of redacting in certain high-risk patterns?
- Do we want explicit policy precedence metadata in `meta_items` beyond `priority` + conflict rule text?
