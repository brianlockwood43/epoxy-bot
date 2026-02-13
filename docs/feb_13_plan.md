# Epoxy Memory Architecture Eval + M4 Readiness Plan

## Brief Summary
- Current verdict: strong M3 foundation, partial M4 scaffolding, not yet sufficient for review-gated self-managed memory.
- Goal status:
  - `gather/tag memories + episodes cleanly`: **Partial**
  - `human-in-loop confirmations (toggleable)`: **Mostly missing**
  - `connect base episodes to expandable meta buckets`: **Scaffolded but not wired**

## Current-State Eval (Repo-Grounded)
1. Gather/tag memories + episodes cleanly: **Partial**
- Working now:
  - Auto-capture and manual capture paths exist (`ingestion/service.py:37`, `misc/events_runtime.py:279`, `misc/commands/commands_memory.py:74`).
  - Topic/tag normalization exists with scope-aware writes (`memory/service.py:127`, `memory/service.py:224`, `memory/store.py:9`).
  - Episode logging is robust and structured (`controller/store.py:441`, `misc/events_runtime.py:594`).
- Gaps:
  - `memory_events.type` exists but is not used on write path (`migrations/0001_core_schema.sql:26`, `memory/store.py:28`).
  - Canonical provenance fields from roadmap are only partially represented; no evidence-span object model.
  - Tagging is flat `tags_json`; no typed taxonomy or validation contract beyond slug normalization.

2. Human-in-loop confirmations (toggleable): **Mostly missing**
- Working now:
  - Global capture toggle exists (`bot.py:142`).
- Gaps:
  - Captured memories are inserted operationally as active records; no candidate-review workflow (`ingestion/service.py:44`, `memory/store.py:28`, `migrations/0001_core_schema.sql:51`).
  - No review queue commands for approve/reject/promote.
  - No memory-level audit trail for human approvals/rejections.

3. Connect raw episodes to expandable meta buckets: **Scaffolded but not wired**
- Working now:
  - Canonical `meta_items` and `memory_links` tables exist (`migrations/0018_meta_items_links_policy_seed.py:17`, `migrations/0018_meta_items_links_policy_seed.py:40`).
  - Policy resolution is wired into runtime (`misc/events_runtime.py:395`, `misc/events_runtime.py:402`, `misc/events_runtime.py:694`).
- Gaps:
  - Narrative/link objects are not used in runtime retrieval; only policy meta is used.
  - `memory_links` have write path but no retrieval/graph expansion path in runtime.
  - `ControllerConfig.memory_budget.meta` is passed through config shape but not applied by retrieval (`misc/events_runtime.py:129`, `retrieval/service.py:23`).
  - Episodes and memories are adjacent but not first-class linked graph objects.

## Decision-Complete Implementation Plan

### Phase 1: Candidate Lifecycle + Toggleable Review Gate
- Implement review mode env:
  - `EPOXY_MEMORY_REVIEW_MODE=off|capture_only|all` (default `capture_only`).
- Behavior:
  - `off`: existing behavior.
  - `capture_only`: auto-capture + mining writes `lifecycle='candidate'`; manual `!remember` remains `active`.
  - `all`: all new memories write as `candidate`, with owner override flag on command.
- Enforce active-only retrieval unchanged so candidates stay invisible until approved.

### Phase 2: Human Review Workflow + Auditability
- Add owner/staff review commands:
  - `!memreview [limit]`
  - `!memapprove <id> [tags=...] [topic=...] [importance=0|1]`
  - `!memreject <id> [reason]`
- Add audit table:
  - `memory_audit_log(memory_id, action, actor_person_id, before_json, after_json, reason, created_at_utc)`.
- Log every lifecycle/manual metadata change through a single memory-lifecycle service.

### Phase 3: Clean Tagging Contract
- Introduce typed tag normalization contract at ingestion:
  - `kind:*`, `topic:*`, `subject:person:*`, `subject:user:*`, `source:*`.
- Continue writing `tags_json` for backward compatibility.
- Start writing `memory_events.type` from kind mappings (`decision|policy|canon|profile|note|event`).
- Add provenance payload column:
  - `provenance_json` with `origin`, `message_id`, `channel_id`, `author_id`, optional evidence offsets.

### Phase 4: Episode-to-Memory and Bucket Graph Wiring
- Add canonical ref grammar:
  - `memory:<id>`, `summary:<id>`, `episode:<id>`, `meta:<id>`, `person:<id>`.
- Add link read APIs:
  - `list_links_for_ref(ref, relation?, lifecycle='active')`
  - `list_meta_for_ref(ref, limit)`
- Add ingestion bridge:
  - episode-to-memory suggestion job writes candidate memories with `source:episode`.
- Define bucket convention with existing canonical objects:
  - Use `MetaItem(kind='narrative')` namespaced as `person:*`, `community:*`, `arc:*`, `inside_joke:*`.
  - Connect memories/episodes to buckets via `Link`.

### Phase 5: Retrieval + Controller Integration for Meta Budget
- Extend retrieval service to honor `memory_budget.meta`.
- Retrieval order:
  - policies first, then event/summaries, then narrative buckets constrained by scope and capability.
- Add formatter section:
  - “Narrative/meta buckets” with citations to linked memory/episode refs.
- Keep policy clamp behavior intact; no change to member-facing privacy gates.

### Phase 6: Eval Gates Before Promotion
- Add deterministic evals:
  - candidate invisibility before approval.
  - approve/reject lifecycle transitions.
  - review-mode toggles by source path.
  - link retrieval accuracy and scope safety.
  - meta budget enforcement.
- Add fixture suites for:
  - people bucket linkage.
  - community bucket linkage.
  - arc continuity over time windows.
  - inside-joke recall with provenance.

## Important API / Interface / Type Changes
- New env var: `EPOXY_MEMORY_REVIEW_MODE`.
- New owner/staff commands: `!memreview`, `!memapprove`, `!memreject`.
- Schema additions:
  - `memory_events.provenance_json`
  - `memory_events.reviewed_by_user_id`
  - `memory_events.reviewed_at_utc`
  - `memory_events.review_note`
  - `memory_audit_log` table
- Service additions:
  - `memory/lifecycle_service.py` for candidate->active/deprecated transitions
  - `memory/link_service.py` for graph reads/writes with ref validation
  - retrieval path update to return meta bucket pack and apply `meta` budget

## Test Cases and Scenarios
1. Auto-captured memory in `capture_only` mode is stored as `candidate` and never retrieved in normal recall.
2. `!memapprove` transitions candidate to active and makes it retrievable.
3. `!memreject` transitions candidate to deprecated and keeps audit record.
4. `all` mode causes `!remember` writes to candidate unless owner override is used.
5. Episode-derived candidate memory preserves provenance and links to `episode:<id>`.
6. `memory_budget.meta=0` returns no narrative buckets; `>0` returns bounded bucket set.
7. Member/public contexts do not retrieve cross-scope buckets or private-linked refs.
8. Policy enforcement behavior remains unchanged in existing controller eval suite.

## Assumptions and Defaults
- Default review posture: `capture_only` for safety without blocking explicit operator memory writes.
- Existing `tags_json` remains canonical until full typed-tag migration is complete.
- SQLite remains current backend; migrations are additive and backward compatible.
- No autonomous controller learning changes are included in this plan.
- All non-trivial changes include a `docs/changes/*.md` summary using `docs/epoxy_change_summary_template.md`.





=========PLAN 2 POST FEEDBACK========

# M4 Meta-Memory Plan Update (Aligned to `docs/meta_memory_design.md`)

## Brief Summary
This updates the prior plan to implement the meta-memory vision as a layered system with:
1. Two-axis structure: `layer type` + `activation mode`.
2. Hybrid backbone selection: `registry-first`, then `tag-based fill`.
3. First-class expanded meta kinds: `relational_contract`, `person_core`, `narrative`, `texture`/`inside_joke`, plus controller/org-policy kinds.
4. Situation-aware focus band allocation from `memory_budget.meta`.
5. Runtime use of meta pack and relational mode blend in mention + DM flows.

Locked choices from you:
1. Backbone source of truth: `Hybrid (registry first, tag fallback)`.
2. Kind model: `Expand Meta Kinds`.

## Scope and Outcomes
1. Keep existing policy enforcement working as-is.
2. Add layered meta retrieval without breaking current event/summary retrieval.
3. Make meta retrieval deterministic, budgeted, auditable, and test-gated.
4. Make relational contracts first-class and behavior-shaping, not just decorative memory.

## Public API / Interface / Type Changes
1. `MetaItem.kind` accepted values expand to:
`policy`, `controller_policy`, `org_identity`, `relational_contract`, `person_core`, `narrative`, `texture`, `inside_joke`.
2. `ControllerConfig.memory_budget` expands (backward compatible):
- Legacy still valid: `"meta": <int>`.
- New shape added:
```yaml
memory_budget:
  hot: 4
  warm: 3
  cold: 1
  summaries: 2
  meta:
    total: 24
    backbone: 6
    backbone_layers:
      controller: 2
      org_identity: 1
      relational_contracts: 1
      people: 1
      arcs: 1
      jokes: 0
    flex_weights:
      default: {controller: 2, org_identity: 2, relational_contracts: 3, people: 4, arcs: 3, jokes: 1}
      coaching_dm: {controller: 2, org_identity: 1, relational_contracts: 4, people: 5, arcs: 4, jokes: 0}
      lumeris_governance: {controller: 4, org_identity: 5, relational_contracts: 3, people: 2, arcs: 3, jokes: 0}
      personal_lowstakes: {controller: 2, org_identity: 1, relational_contracts: 4, people: 4, arcs: 3, jokes: 2}
```
3. New situation profile object used by controller:
```json
{
  "surface": "dm|public_channel|coach_channel|system_job",
  "topic": "coaching|governance|personal|ops|other",
  "participants": ["person:<id>", "person:<id>"],
  "seriousness": "low|medium|high",
  "context_tags": ["..."],
  "override_meta_mode": "default|coaching_dm|lumeris_governance|personal_lowstakes"
}
```
4. New structured meta pack returned to prompt assembly:
`backbone_items[]`, `focus_items_by_layer{}`, `mode_blend{}`, `refs[]`.

## Schema and Migration Plan
1. Migration A: extend `meta_items` with:
- `layer TEXT` (controller|org_identity|relational_contracts|people|arcs|jokes mapping layer)
- `tags_json TEXT DEFAULT '[]'`
- `payload_json TEXT DEFAULT '{}'`
- `importance REAL DEFAULT 0.5`
- `backbone_eligible INTEGER DEFAULT 0`
2. Migration B: add `meta_backbone_registry`:
- `id`, `layer`, `meta_item_id`, `scope`, `priority`, `lifecycle`, `created_at_utc`, `updated_at_utc`
3. Migration C: add indexes:
- `meta_items(kind, layer, lifecycle, scope)`
- `meta_items(backbone_eligible, lifecycle)`
- `meta_backbone_registry(layer, scope, lifecycle, priority)`
4. Backward compatibility:
- Existing `meta_items` rows remain valid.
- Existing `kind=policy|narrative` rows are mapped to layers automatically.
- Legacy controller configs with numeric `meta` are auto-translated to new defaults in code (no forced data rewrite).

## Retrieval and Controller Design (Decision-Complete)
1. Build situation profile from runtime context in `misc/events_runtime.py`.
2. Resolve meta budget from controller config with compatibility handling.
3. Backbone selection algorithm:
- Fill per-layer backbone slots from `meta_backbone_registry` first.
- If slots remain, fill from active tagged candidates requiring `backbone_eligible=1` or tag `kind:meta_backbone` + matching `layer:*`.
- Registry-picked items are never displaced by tagged fallback.
4. Dynamic participant layers:
- For `relational_contracts` and `people`, first attempt participant-targeted items (`subject:person:<id>` tags).
- If missing, fallback to registry/default and then tag candidates.
5. Focus band selection:
- Compute `meta_flex = max(0, total - backbone)`.
- Choose weight profile from situation (`coaching_dm`, `lumeris_governance`, `personal_lowstakes`, else `default`).
- Convert weights to per-layer quotas deterministically.
- Score candidates by context match, participant match, scope match, continuity, recency, importance.
- Apply seriousness penalty to `texture/inside_joke` when seriousness is high.
6. Mode blend computation:
- Parse `relational_contract.payload_json.default_modes` and `context_overrides`.
- Blend with situation seriousness/topic to produce final mode mix used in controller directive.
7. Runtime integration:
- Mention and DM flows add compact meta pack section to prompt assembly.
- Existing policy directive/enforcement stays enabled and precedence is unchanged.

## Service and Module Changes
1. New module `controller/situation_profile.py`:
- `build_situation_profile(...)`
- `select_meta_weight_profile(...)`
2. New module `memory/meta_retrieval.py`:
- `resolve_meta_budget(...)`
- `load_backbone_meta(...)`
- `load_focus_meta(...)`
- `build_meta_pack(...)`
3. Extend `memory/meta_store.py`:
- support expanded kinds
- tag/payload upsert/read
- registry CRUD/read helpers
4. Extend `controller/prompt_assembly.py`:
- format structured meta pack and mode blend into deterministic prompt blocks
5. Wire into `misc/events_runtime.py` for both standard mention and DM draft paths.

## Rollout Plan (Safe and Incremental)
1. Chunk 8: schema + store support + fixture seeds for new kinds/layers (no runtime behavior change).
2. Chunk 9: situation profile + budget resolver + backbone-only retrieval behind `EPOXY_META_LAYERED_RETRIEVAL=0|1`.
3. Chunk 10: focus band retrieval + seriousness gating + mode blend integration.
4. Chunk 11: registry tooling and owner commands for curation.
5. Chunk 12: eval gates required before default-on rollout.

## Commands / Ops Tooling
1. Add owner/staff commands:
- `!meta.backbone.list`
- `!meta.backbone.add <layer> <meta_id> [scope] [priority]`
- `!meta.backbone.remove <id>`
- `!meta.find <query> [layer] [kind]`
- `!meta.link <from_ref> <to_ref> <relation>`
2. Keep existing policy commands/paths unchanged.
3. Add lightweight diagnostics:
- print selected situation profile, backbone picks, flex quotas, and selected meta ids to structured episode `implicit_signals` (IDs only).

## Tests and Eval Scenarios
1. Unit tests:
- budget resolver handles legacy and new shapes
- backbone fill order is registry-first then tags
- per-layer quota math is deterministic
- seriousness suppresses jokes in high-stakes contexts
- relational contract override resolution works by surface/topic
2. Integration tests:
- mention runtime receives meta pack + mode blend
- DM draft runtime receives meta pack + mode blend
- policy clamps still apply with new meta retrieval enabled
3. Eval fixtures:
- per-person relational variation
- governance vs coaching profile selection
- high-seriousness no-joke behavior
- low-stakes texture inclusion within budget
- missing backbone entries degrade gracefully
4. Regression gates:
- existing `test_eval_memory_recall_baseline.py` and `test_eval_controller_policy_adherence.py` must remain green.

## Assumptions and Defaults
1. Default rollout mode: feature-flagged off until eval baselines pass.
2. Registry scope default: `global`.
3. If `meta.total` is unset and legacy `meta` is int N:
- `total=N`, `backbone=min(6,N)`, default layer minimums scaled down proportionally.
4. If relational contract/person core for a participant is missing, fallback to registry/tagged layer defaults rather than failing retrieval.
5. Base memory candidate-review workflow from prior plan remains a parallel workstream and is not blocked by this meta-layer rollout.



