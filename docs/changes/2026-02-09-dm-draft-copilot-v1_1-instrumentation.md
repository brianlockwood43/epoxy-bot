# Epoxy Change Summary - 2026-02-09 DM Draft Copilot v1.1 Instrumentation

## Scope Snapshot
- Added owner-only mention route `@Epoxy dm: ...` for structured DM drafting.
- Added parse, mode, blocking, and output behaviors for DM Draft Copilot v1.1.
- Added first-class episode-log instrumentation for:
  - target identity
  - mode auditability
  - blocking auditability
  - guideline provenance
  - draft lineage
  - recall provenance metadata
- Added owner feedback/evaluation hooks for DM drafts.
- Updated episode logging filters to context/caller/surface semantics with legacy fallback support.
- Updated announcement prep channel default and allowlist alignment.

## Public-Facing Behavior Changes
- Mention command route:
  - `@Epoxy dm: ...`
  - owner-only for DM draft mode
- Parse contract fields:
  - `target`
  - `objective`
  - `situation_context`
  - `my_goals[]`
  - `non_negotiables[]`
  - `tone`
  - optional `mode`
- Parse format support:
  - `key:value`
  - `key=value`
  - multiline sections with bullets for list fields
- Mode behavior:
  - explicit override wins when present (`collab|best_effort`)
  - otherwise heuristic auto mode is used
- Collab behavior:
  - default is draft + up to 2 concise questions
  - conditional pre-draft blocking for critical missing fields:
    - missing target
    - missing objective
    - missing non-negotiables when context implies hard boundary/safety relevance
- Result model:
  - `DmDraftResult.drafts` is list-based (future-ready for multi-variant output)

## Important Modules, Types, and Commands
- Modules and types:
  - `controller/dm_draft_parser.py` with `DmDraftRequest`, `DmParseResult`
  - `controller/dm_draft_service.py` with `DmDraftVariant`, `DmDraftResult` and mode/blocking/recall logic
  - `controller/dm_episode_artifact.py` with stable artifact envelope
  - `misc/events_runtime.py` DM route, target resolution, and episode payload shaping
  - `controller/store.py` and `controller/models.py` for episode persistence and model fields
- Owner commands:
  - `!dmfeedback <keep|edit|sent|discard> [note]`
  - `!dmeval tone_fit=... de_escalation=... agency_respect=... boundary_clarity=... actionability=... context_honesty=... [tags=...] [| note]`
- Legacy behavior note:
  - `EPOXY_EPISODE_LOG_SURFACES` remains supported only as fallback when `EPOXY_EPISODE_LOG_FILTERS` is unset

## Why This Changed
- DM drafting needed to be usable short-term without building a parallel cognition path outside core Epoxy memory/controller wiring.
- Instrumentation depth was increased to make behavior auditable and queryable before introducing new dedicated tables.
- Tradeoffs accepted:
  - episode logs remain the primary artifact store in v1.x
  - fixed recall labels (`thin|mixed|rich`) are retained while adding source-bucket counts
  - heuristic auto mode remains in place with explicit override support

## Config and Operational Knobs
- `EPOXY_DM_GUIDELINES_PATH` default: `config/dm_guidelines.yml`
- `EPOXY_EPISODE_LOG_FILTERS` default: `context:dm,context:public,context:member,context:staff,context:leadership`
- `EPOXY_EPISODE_LOG_SURFACES` remains legacy fallback behavior.
- `EPOXY_ENABLE_EPISODE_LOGGING` continues to gate episode logging.
- `EPOXY_ANNOUNCE_PREP_CHANNEL_ID` default updated to `1412603858835738784`.
- Guideline source values emitted as `file|env_override|fallback`.
- Missing/invalid explicit mode falls back to heuristic auto behavior.

## Data Model and Schema Touchpoints
- New first-class `episode_logs` fields:
  - `target_user_id`
  - `target_display_name`
  - `target_type`
  - `target_confidence`
  - `target_entity_key`
  - `mode_requested`
  - `mode_inferred`
  - `mode_used`
  - `blocking_collab`
  - `critical_missing_fields_json`
  - `blocking_reason`
  - `dm_guidelines_version`
  - `dm_guidelines_source`
  - `draft_version`
  - `draft_variant_id`
  - `prompt_fingerprint`
- Stable artifact payload keys in `implicit_signals_json`:
  - `episode.kind = "dm_draft"`
  - `episode.artifact.dm.parse = {...}`
  - `episode.artifact.dm.result = {...}`
- Enums and identifiers used:
  - mode: `auto|collab|best_effort`
  - target_type: `member|staff|external|self|unknown`
  - blocking reasons include `missing_target`, `missing_objective`, `missing_non_negotiables_boundary_context`, `multiple_critical_missing`
- Migrations added:
  - `0006_episode_log_target_fields.py`
  - `0007_episode_log_mode_fields.py`
  - `0008_episode_log_blocking_fields.py`
  - `0009_episode_log_guideline_fields.py`
  - `0010_episode_log_target_entity_key.py`
  - `0011_episode_log_draft_lineage_fields.py`

## Observability and Telemetry
- DM draft episodes now log:
  - target identity and fallback entity key
  - mode triplet (`mode_requested`, `mode_inferred`, `mode_used`)
  - blocking metadata (`blocking_collab`, critical fields, reason)
  - guideline provenance (`dm_guidelines_version`, `dm_guidelines_source`)
  - draft lineage (`draft_version`, `draft_variant_id`, `prompt_fingerprint`)
  - recall coverage metadata with fixed labels:
    - `thin <=2`
    - `mixed 3..7`
    - `rich >=8`
  - recall provenance source buckets:
    - `target_profile_count`
    - `recent_dm_count`
    - `public_interaction_count`
    - `notes_count`
    - `policy_count`
- Quick verification:
  - `!episodelogs 5`
  - inspect `implicit_signals_json` for `episode.artifact.dm.*` and `recall_provenance_counts`

## Rollout / Upgrade Notes
- Migration order is numeric by migration version and is additive for this change set (`0006` through `0011` over base schema migrations).
- Rollback tolerance:
  - these changes add nullable columns and indexes; existing rows remain valid with nulls
  - no destructive field drops were introduced by this change set
- Backfill expectations:
  - no data backfill is required for pre-existing rows
  - newly added fields populate on new DM-draft episodes only
- TODO:
  - define an explicit down-migration/rollback playbook if strict schema rollback is required in production

## Guidelines Versioning Semantics
- `dm_guidelines_version` is the loaded guideline pack version marker from DM guideline loading.
- `dm_guidelines_source` records load provenance: `file|fallback|env_override`.
- `prompt_fingerprint` is a hash of normalized DM request inputs used for drafting lineage correlation.
- `prompt_fingerprint` currently reflects normalized request content and mode-used fields; it does not include a guideline-version token in the hash input.

## Privacy / Retention Note
- Stored locations:
  - top-level DM audit fields are written to `episode_logs`
  - structured parse/result payloads and recall/provenance metadata are written under `implicit_signals_json`
  - feedback/eval annotations are written to `human_notes` and `implicit_signals_json.evaluation`
- Sensitive-content caution:
  - DM-related excerpts and draft artifacts are persisted for observability and iteration
- TODO:
  - retention period, redaction policy, and deletion workflow are not explicitly defined in this change summary and should be documented separately

## Blocking Contract Invariants
- When `blocking_collab=true`:
  - the flow returns a blocking response before draft generation
  - response includes blocking reason and up to 2 targeted clarification questions
  - episode is logged with blocking metadata (`blocking_collab`, `critical_missing_fields`, `blocking_reason`)
  - in blocking flow, no drafted variant is produced (`draft_variant_id` is null for the blocking event payload)
- Blocking conditions for collab mode:
  - missing target
  - missing objective
  - missing non-negotiables when boundary/safety context markers are present

## Behavioral Assumptions
- Non-DM mention handling remains unchanged.
- DM recall threshold labeling remains fixed and unchanged.
- Collab behavior remains draft-plus-questions by default, with blocking only on critical-risk missing fields.
- Subtle behavior that may vary:
  - `prompt_fingerprint` can change after best-effort assumptions are applied

## Risks and Sharp Edges
- Target resolution may misclassify `unknown` vs `external` in limited guild/member visibility.
- Boundary-context blocking trigger is keyword-based and may over/under-trigger.
- Heuristic mode inference can still mismatch user intent when language is ambiguous.
- Provenance bucket quality depends on upstream tags/channel naming/topic metadata quality.
- Guideline load fallback can alter style; provenance fields help diagnose this.

## How To Test (Smoke + Edge Cases)
- Prompt:
  - `@Epoxy dm: target=<@123456789012345678>; objective=repair trust; situation_context=conflict in coaching thread; my_goals=trust|accountability; non_negotiables=no shaming|no mind reading; tone=steady; mode=collab`
  - Expected:
    - draft returned (or clarification questions), mode uses `collab`, parse/result artifacts and target/mode fields are logged
- Prompt:
  - `@Epoxy dm: objective=calm this down; situation_context=urgent member blowup; tone=firm; mode=collab`
  - Expected:
    - blocking collab with `blocking_reason=missing_target` and critical missing fields logged
- Prompt:
  - `@Epoxy dm: just draft asap!!! situation_context=...`
  - Expected:
    - heuristic tends to `best_effort` unless explicit mode override is present
- Command:
  - `!dmfeedback sent | landed cleanly`
  - Expected:
    - latest DM-draft episode gets `explicit_rating=2` and note append
- Command:
  - `!dmeval tone_fit=2 de_escalation=1 agency_respect=2 boundary_clarity=1 actionability=2 context_honesty=2 tags=too_vague`
  - Expected:
    - latest DM-draft episode gets rubric and failure tags under `implicit_signals_json.evaluation`

## Evaluation Hooks
- Feedback score mapping:
  - `sent=+2`
  - `keep=+1`
  - `edit=0`
  - `discard=-1`
- Rubric dimensions:
  - `tone_fit`
  - `de_escalation`
  - `agency_respect`
  - `boundary_clarity`
  - `actionability`
  - `context_honesty`
- Failure tags:
  - `too_long`
  - `too_vague`
  - `too_harsh`
  - `too_soft`
  - `too_therapyspeak`
  - `misses_ask`
  - `invents_facts`
- Eval data storage:
  - latest DM-draft episode in `implicit_signals_json.evaluation` and `human_notes`

## Analytics / Query Recipes
- Recipe 1: override usage rate and heuristic disagreement.
  - SQL sketch:
    - `SELECT mode_requested, mode_inferred, mode_used, COUNT(*) FROM episode_logs WHERE tags_json LIKE '%"mode:dm_draft"%' GROUP BY mode_requested, mode_inferred, mode_used ORDER BY COUNT(*) DESC;`
- Recipe 2: collab blocking rate by reason.
  - SQL sketch:
    - `SELECT blocking_reason, COUNT(*) FROM episode_logs WHERE tags_json LIKE '%"mode:dm_draft"%' AND blocking_collab=1 GROUP BY blocking_reason ORDER BY COUNT(*) DESC;`
- Recipe 3: recall provenance distribution checks.
  - SQL sketch:
    - `SELECT AVG(COALESCE(json_extract(implicit_signals_json,'$.recall_provenance_counts.target_profile_count'),0)), AVG(COALESCE(json_extract(implicit_signals_json,'$.recall_provenance_counts.recent_dm_count'),0)), AVG(COALESCE(json_extract(implicit_signals_json,'$.recall_provenance_counts.public_interaction_count'),0)), AVG(COALESCE(json_extract(implicit_signals_json,'$.recall_provenance_counts.notes_count'),0)), AVG(COALESCE(json_extract(implicit_signals_json,'$.recall_provenance_counts.policy_count'),0)) FROM episode_logs WHERE tags_json LIKE '%"mode:dm_draft"%';`

## Debt and Follow-Ups
- Episode logs currently double as artifact storage; dedicated DM artifact storage is still deferred.
- Context-dependent recall thresholding is still deferred.
- Blocking-context detection remains lexical and should eventually be policy-driven.
- Target identity resolution could use richer resolver logic beyond current Discord/guild inference path.

## Open Questions for Brian/Seri
- Should `mode=auto` be surfaced as explicit default in operator UX/docs?
- Should blocked-collab ever emit a temporary minimal draft in urgency cases, or remain strictly block-first?
- When should DM artifacts be promoted from episode logs to a dedicated analytics table/view?
- When should adaptive/context-dependent recall thresholds replace fixed thresholds?
