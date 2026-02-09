# Epoxy Patch Notes (February 9, 2026)

This file summarizes the implementation work completed in this session so a separate planning agent (for example, Seri) can do conceptual/test planning without re-reading the full code diff.

## 1) DM Draft Copilot v1.1

### What was added
- Mention-mode DM drafting flow: `@Epoxy dm: ...`
- Owner-only gate for DM drafting mode.
- Structured parse contract with fields:
  - `target`
  - `objective`
  - `situation_context`
  - `my_goals[]`
  - `non_negotiables[]`
  - `tone`
- Partial parse fork behavior:
  - tone/urgency-based inference of `collab` vs `best_effort`
  - `collab`: include up to 2 concise follow-up questions
  - `best_effort`: fill missing fields with explicit assumptions
- Flexible result model for future multi-draft output:
  - `DmDraftVariant`
  - `DmDraftResult` (list of drafts + risk notes + optional tighten + recall coverage metadata)

### Recall coverage behavior (Risk Notes)
- Coverage is always computed and surfaced.
- Thresholds:
  - `thin` (`<=2`): "Recall is thin; leaning mostly on manual context."
  - `mixed` (`3..7`)
  - `rich` (`>=8`)
- Assumptions line is appended when inference filled missing parse fields.

### Guideline/policy source
- Added versioned DM guideline loader + default fallback behavior.
- Runtime reads from `config/dm_guidelines.yml` (overridable with env var).

### Key files
- `controller/dm_guidelines.py`
- `config/dm_guidelines.yml`
- `controller/dm_draft_parser.py`
- `controller/dm_draft_service.py`
- `misc/mention_routes.py`
- `misc/events_runtime.py`


## 2) DM Draft Feedback Loop

### What was added
- Owner command:
  - `!dmfeedback <keep|edit|sent|discard> [note]`
- Feedback writes to latest DM draft episode:
  - updates `explicit_rating`
  - appends optional note to `human_notes`
- Rating mapping:
  - `sent=+2`, `keep=+1`, `edit=0`, `discard=-1`

### Key files
- `controller/store.py` (`update_latest_dm_draft_feedback_sync`)
- `misc/commands/commands_owner.py`
- wiring/deps updates:
  - `misc/commands/command_deps.py`
  - `misc/runtime_wiring.py`
  - `misc/runtime_deps.py`
  - `bot.py`


## 3) Episode Logging Filters (Context/People-Oriented)

### Why changed
- Previous default filtering was surface-only (`dm,coach_channel,public_channel`).
- New model supports filtering by:
  - who (`caller:*`)
  - context (`context:*`)
  - transport surface (`surface:*`)

### What was added
- New env var:
  - `EPOXY_EPISODE_LOG_FILTERS` (preferred)
- Legacy compatibility:
  - `EPOXY_EPISODE_LOG_SURFACES` still works if `EPOXY_EPISODE_LOG_FILTERS` is unset.
- Filter syntax supports:
  - `caller:founder|core_lead|coach|member|external`
  - `context:dm|public|member|staff|leadership|unknown`
  - `surface:dm|coach_channel|public_channel|system_job`
  - `all`
  - legacy bare tokens (`dm`, `coach_channel`, `member`, etc.)

### New default
- `context:dm,context:public,context:member,context:staff,context:leadership`

### Key files
- `controller/episode_log_filters.py`
- `misc/events_runtime.py`
- `bot.py`
- `misc/runtime_deps.py`
- `misc/runtime_wiring.py`
- `.env.example`
- `docs/developer_reference.md`


## 4) Announcement Prep Channel Default + Allowlist

### What changed
- Default prep channel ID is now:
  - `1412603858835738784`
- That ID was added to default allowed channels.
- Clarified that prep channel default is announcement-specific and not tied to access role keyword logic.

### Key files
- `config/defaults.py`
- `bot.py`
- `.env.example`
- `docs/developer_reference.md`


## 5) Docs/Reference Updates

- Added DM copilot command/env documentation and structures.
- Added episode logging filter docs and legacy note.
- Updated announce prep channel default docs.
- Minor architecture doc updates for new controller/runtime modules.

### Key files
- `docs/developer_reference.md`
- `docs/architecture.md`


## 6) Tests Added/Updated

### New tests
- `tests/test_dm_draft_parser.py`
- `tests/test_dm_draft_service.py`
- `tests/test_events_runtime_dm_route.py`
- `tests/test_controller_store_dm_feedback.py`
- `tests/test_episode_log_filters.py`

### Validation run status
- Compile check executed successfully.
- Unit test suite executed successfully.
- One existing announcement auth test remains skipped when `discord.py` is not installed (expected in this environment).


## 7) No Migrations Added

- No new DB schema migration files were added in this session.
- Feedback flow reuses existing `episode_logs` columns (`explicit_rating`, `human_notes`).


## 8) Good Planning Questions for Seri

1. Should DM draft mode eventually require explicit `mode=collab|best_effort|auto` override instead of pure heuristic inference?
2. Should `collab` mode block draft generation until missing critical fields are answered, or keep current "draft + follow-ups" behavior?
3. Should we persist structured DM draft artifacts separately from generic episode logs for eval/reporting?
4. What evaluation rubric should score draft quality (tone-fit, de-escalation, boundary clarity, policy adherence)?
5. Should recall coverage thresholds stay fixed (`<=2`, `3..7`, `>=8`) or become context-dependent?
6. Should `target_user` become a first-class field in episode logs (vs current tag approach) for analytics?


## 9) Suggested Testing-Plan Focus Areas (Conceptual)

1. Parse robustness across messy real prompts (single-line, multiline, mixed formatting, incomplete fields).
2. Mode inference accuracy under high-intensity vs reflective prompt language.
3. Draft quality under thin recall vs rich recall.
4. Safety/communication constraints under emotionally loaded scenarios.
5. Episode filter correctness across caller/context/surface combinations.
6. Operator workflow latency: how many turns needed from request to usable DM draft.


## 10) Seri + Brian Decisions (Agreed Direction)

This section captures explicit answers to Section 8, with `do now` vs `later`.

### Do now

1. Mode override support:
   - Add optional explicit mode override in DM parse contract:
     - `mode: auto|collab|best_effort`
     - short alias forms also acceptable (`mode=collab`)
   - Precedence:
     - explicit mode (if present) > heuristic inference
     - default remains `auto` (heuristic)

2. Collab behavior:
   - Keep default collab behavior as:
     - draft + up to 2 concise questions
   - Add conditional `blocking_collab` only for critical missing fields where drafting is risky:
     - missing target
     - missing objective
     - missing non-negotiables when context implies hard boundary/safety relevance

3. Logging structure (without new tables yet):
   - Continue using episode logs for speed.
   - Store structured DM payload under stable keys inside episode artifact JSON shape:
     - `episode.kind = "dm_draft"`
     - `episode.artifact.dm.parse = {...}`
     - `episode.artifact.dm.result = {...}`

4. Evaluation rubric (0–2 each):
   - Tone-fit
   - De-escalation
   - Agency & respect
   - Boundary clarity
   - Actionability
   - Context honesty
   - Also track compact failure tags:
     - `too_long`, `too_vague`, `too_harsh`, `too_soft`, `too_therapyspeak`, `misses_ask`, `invents_facts`

5. Recall coverage:
   - Keep fixed thresholds for now (`thin/mixed/rich` as currently implemented).
   - Add provenance counts in metadata (source buckets) before changing threshold logic.

6. Target user:
   - Promote target user to first-class episode log fields:
     - `target_user_id`
     - `target_display_name`
     - `target_type` (`member|staff|external|self|unknown`)
     - `target_confidence` (if inferred)

7. Mode auditability fields:
   - Record:
     - `mode_requested` (explicit override or `null`)
     - `mode_inferred` (what heuristic selected)
     - `mode_used` (final mode applied)
   - Purpose:
     - make override frequency and heuristic quality directly queryable.

8. Blocking-collab audit fields:
   - Record:
     - `blocking_collab: bool`
     - `critical_missing_fields: [...]`
     - `blocking_reason` (short enum-like value)
   - Suggested reasons:
     - `missing_target`
     - `missing_objective`
     - `missing_non_negotiables_boundary_context`

9. Guidelines provenance fields:
   - Record:
     - `dm_guidelines_version` (or hash)
     - `dm_guidelines_source` (`file|fallback|env_override`)
   - Purpose:
     - avoid “behavior drift with unknown source” issues.

10. Target identity fallback key:
   - Record:
     - `target_entity_key` (stable string; examples: `discord:123...`, `member:caleb`, `external:chloe`)
   - Purpose:
     - preserve joinability when canonical Discord ID cannot be resolved.

11. Draft lineage fields:
   - Record:
     - `draft_version` (example: `1.1`)
     - `draft_variant_id` (for multi-variant generation)
     - optional `prompt_fingerprint` (hash of normalized request)
   - Purpose:
     - correlate repeated attempts and compare variant outcomes.

12. Recall provenance metadata:
   - Add bucketed counts under recall metadata (while keeping fixed thin/mixed/rich thresholds):
     - `target_profile_count`
     - `recent_dm_count`
     - `public_interaction_count`
     - `notes_count`
     - `policy_count`
   - Purpose:
     - improve diagnosability without changing threshold logic yet.

### Later

1. Dedicated DM artifacts store/table:
   - Defer until analytics/eval pressure increases; keep v1.x iteration speed.

2. Context-dependent recall thresholds:
   - Defer until enough data exists to define expected baseline by DM type/context.

3. Convergence architecture target:
   - DM drafting should converge into normal Epoxy controller wiring as a specialized view:
     - DM-specific guideline source
     - DM-specific output schema
     - DM-specific guardrails
   - Avoid permanent “separate brain” architecture.


## 11) Execution Sanity Checklist (for Implementation Pass)

1. Parser supports explicit mode override aliases:
   - `mode: collab|best_effort|auto`
   - `mode=collab` style forms
2. Episode log marks DM kind and stores structured artifact payload:
   - `kind = dm_draft`
   - `artifact.dm.parse`
   - `artifact.dm.result`
3. Episode artifact includes mode triplet and blocking audit fields:
   - `mode_requested`, `mode_inferred`, `mode_used`
   - `blocking_collab`, `critical_missing_fields`, `blocking_reason`
4. Episode artifact includes guideline provenance:
   - `dm_guidelines_version`, `dm_guidelines_source`
5. Target identity fields include fallback key:
   - `target_user_id`, `target_display_name`, `target_type`, `target_confidence`, `target_entity_key`
6. Draft lineage fields are present:
   - `draft_version`, `draft_variant_id`
   - optional `prompt_fingerprint`
7. Blocking collab only triggers on agreed critical-missing set.
8. Recall metadata includes bucketed provenance counts.
