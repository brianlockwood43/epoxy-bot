# Epoxy M4 Memory + Meta Layer: Chunked Decision-Complete Implementation Plan

Date: 2026-02-13  
Owner: Brian + Codex  
Status: Planned (implementation-ready)

## 1) Summary

This plan merges:
- `docs/feb_13_plan.md` (memory lifecycle + human review + graph wiring),
- `docs/meta_memory_design.md` (layered meta with backbone + focus band).

It is intentionally chunked so each chunk is PR-sized, test-gated, and rollback-safe.
Chunks 1-7 from `docs/m3-stabilization-m4-readiness-plan.md` are already complete.
This plan starts at **Chunk 8** and is decision-complete through rollout.

## 2) Locked Decisions

1. Meta architecture uses two axes:
- `layer type` and `activation mode (backbone vs focus)`.

2. Backbone source of truth is **hybrid**:
- Registry-first.
- Tag fallback to fill open per-layer backbone slots.
- Registry-picked items cannot be displaced by tag fallback.

3. Meta kind model is **expanded first-class kinds** (not tag-only):
- `policy`, `controller_policy`, `org_identity`, `relational_contract`, `person_core`, `narrative`, `texture`, `inside_joke`.

4. Memory review posture default:
- `EPOXY_MEMORY_REVIEW_MODE=capture_only`.

5. No autonomous learning changes in this plan:
- M6+ controller learning remains out of scope.

## 3) Cross-Chunk Invariants

1. Privacy/policy precedence remains unchanged:
- Existing policy resolution and runtime clamp paths stay authoritative.

2. Retrieval remains scope-safe and lifecycle-safe:
- `active` lifecycle only for normal recall.

3. Schema changes are additive and backward compatible:
- No destructive field removals or semantic redefinition.

4. Every chunk must ship with:
- tests,
- docs change note under `docs/changes/`,
- compile + unit validation commands.

## 4) Canonical Shapes (Target End State)

## 4.1 Memory review controls

- New env var:
  - `EPOXY_MEMORY_REVIEW_MODE=off|capture_only|all` (default: `capture_only`)
- Write behavior:
  - `off`: current behavior (writes `active`).
  - `capture_only`: auto-capture/mining writes `candidate`; explicit manual `!remember` writes `active`.
  - `all`: all writes default to `candidate`, with owner override flag on command.

## 4.2 Controller meta budget (backward compatible)

Legacy:
```json
{ "meta": 2 }
```

New:
```json
{
  "meta": {
    "total": 24,
    "backbone": 6,
    "backbone_layers": {
      "controller": 2,
      "org_identity": 1,
      "relational_contracts": 1,
      "people": 1,
      "arcs": 1,
      "jokes": 0
    },
    "flex_weights": {
      "default": {
        "controller": 2,
        "org_identity": 2,
        "relational_contracts": 3,
        "people": 4,
        "arcs": 3,
        "jokes": 1
      },
      "coaching_dm": {
        "controller": 2,
        "org_identity": 1,
        "relational_contracts": 4,
        "people": 5,
        "arcs": 4,
        "jokes": 0
      },
      "lumeris_governance": {
        "controller": 4,
        "org_identity": 5,
        "relational_contracts": 3,
        "people": 2,
        "arcs": 3,
        "jokes": 0
      },
      "personal_lowstakes": {
        "controller": 2,
        "org_identity": 1,
        "relational_contracts": 4,
        "people": 4,
        "arcs": 3,
        "jokes": 2
      }
    }
  }
}
```

## 4.3 Situation profile

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

## 4.4 Meta pack shape for prompt assembly

```json
{
  "backbone_items": [{ "id": 0, "kind": "", "layer": "", "scope": "", "refs": [] }],
  "focus_items_by_layer": {
    "controller": [],
    "org_identity": [],
    "relational_contracts": [],
    "people": [],
    "arcs": [],
    "jokes": []
  },
  "mode_blend": { "guide": 0.0, "coach": 0.0, "lab": 0.0, "strategist": 0.0, "scribe": 0.0, "friend": 0.0 },
  "refs": ["meta:<id>", "memory:<id>", "episode:<id>", "person:<id>"]
}
```

## 5) Chunk Plan

## Chunk 8: Memory Review Mode + Candidate Lifecycle

### Objective
Introduce toggleable human-in-loop gating for newly captured memories without changing current recall behavior.

### Scope
1. Add env + wiring for `EPOXY_MEMORY_REVIEW_MODE`.
2. Route lifecycle on insert (`candidate` vs `active`) based on source path and mode.
3. Keep retrieval `active`-only unchanged.

### Implementation
1. Update config/runtime wiring:
- `bot.py`, `misc/runtime_wiring.py`, `misc/runtime_deps.py`, `misc/commands/command_deps.py`.

2. Extend memory insert path to accept explicit lifecycle:
- `memory/service.py` -> include `lifecycle`.
- `memory/store.py` -> persist provided lifecycle.

3. Source-path policy:
- auto-capture (`ingestion/service.py`) and mining (`misc/commands/commands_mining.py`) obey review mode.
- manual `!remember` stays active in `capture_only`.

### Acceptance Criteria
1. In `capture_only`, auto-captured and mined memories are written as `candidate`.
2. In `capture_only`, manual `!remember` writes `active`.
3. In `all`, all new memory writes default to `candidate` unless owner override is passed.
4. `!recall` and runtime mention retrieval still exclude candidates.

### Tests
1. `tests/test_memory_review_mode_capture_only.py`
2. `tests/test_memory_review_mode_all.py`
3. `tests/test_memory_review_mode_off.py`

### Risks
1. Accidental invisibility of operator-inserted memory.
Mitigation: explicit tests and command-level override.

---

## Chunk 9: Review Workflow Commands + Audit Log

### Objective
Make candidate review operational with explicit approve/reject actions and auditable history.

### Scope
1. Add review commands:
- `!memreview [limit]`
- `!memapprove <id> [tags=...] [topic=...] [importance=<0..4 or 0.0..1.0>] [note=...]`
- `!memreject <id> [reason=...]`

2. Add audit persistence for lifecycle and metadata edits.

### Schema
Migration: `0019_memory_review_audit.py`
1. Add columns to `memory_events`:
- `reviewed_by_user_id INTEGER`
- `reviewed_at_utc TEXT`
- `review_note TEXT`

2. Add table:
- `memory_audit_log(id, memory_id, action, actor_person_id, before_json, after_json, reason, created_at_utc)`

3. Modernize `memory_events.importance` to REAL semantics:
- `importance REAL DEFAULT 0.5`
- Normalize and clamp copied values into `[0.0, 1.0]` during migration rebuild.

### Implementation
1. New module: `memory/lifecycle_service.py`
- `list_candidate_memories_sync`
- `approve_memory_sync`
- `reject_memory_sync`
- `write_memory_audit_sync`

2. Commands in `misc/commands/commands_memory.py`.
3. Wire person identity for actor ids via existing identity store.
4. `!memapprove` importance parsing rules:
- integer tier `0..4` maps to `0.00, 0.25, 0.50, 0.75, 1.00`.
- otherwise parse float and clamp to `[0.0, 1.0]`.
- omitted importance on approve defaults to `0.50`.

### Acceptance Criteria
1. `!memreview` lists candidate items only.
2. `!memapprove` transitions candidate -> active and applies optional metadata edits.
3. `!memreject` transitions candidate -> deprecated.
4. Each action writes one `memory_audit_log` row with before/after snapshots.
5. `!memapprove importance=3` stores `0.75`.
6. `!memapprove importance=0.9` stores `0.9`.
7. `!memapprove` with omitted importance stores `0.5`.
8. Invalid importance input returns deterministic parse error.
9. Audit snapshots store normalized float importance values.

### Tests
1. `tests/test_memory_review_commands.py`
2. `tests/test_memory_audit_log.py`

### Risks
1. Review command misuse in non-owner contexts.
Mitigation: enforce owner/staff gates.

---

## Chunk 10: Typed Tag Contract + Provenance Field

### Objective
Standardize memory tags and add explicit provenance payload for future graph/evidence work.

### Scope
1. Introduce typed tag conventions:
- `kind:*`, `topic:*`, `subject:person:*`, `subject:user:*`, `source:*`.
2. Continue writing existing tags for compatibility.
3. Start writing `memory_events.type` from kind mapping.
4. Add `provenance_json` for structured source metadata.

### Schema
Migration: `0020_memory_provenance_and_type_backfill.py`
1. Add `memory_events.provenance_json TEXT DEFAULT '{}'`.
2. Backfill `type` where null/blank using existing tags.

### Implementation
1. New helper module: `memory/tagging.py`
- normalize + validate tag shape
- kind/topic extraction

2. Update insertion call sites:
- `memory/service.py`
- `ingestion/service.py`
- `misc/commands/commands_memory.py`
- `misc/commands/commands_mining.py`

### Acceptance Criteria
1. New memories include `provenance_json`.
2. `memory_events.type` is non-empty and mapped consistently.
3. Legacy tags still searchable via existing retrieval.

### Tests
1. `tests/test_memory_typed_tags.py`
2. `tests/test_memory_provenance_write.py`

### Risks
1. Tag cardinality bloat.
Mitigation: validation + dedupe in tag helper.

---

## Chunk 11: Meta Model Expansion + Backbone Registry

### Objective
Upgrade meta storage to support layered retrieval and hybrid backbone selection.

### Scope
1. Expand allowed `meta_items.kind`.
2. Add meta layer metadata and payload/tags.
3. Add explicit backbone registry table.

### Schema
Migration: `0021_meta_layering_and_backbone_registry.py`
1. Add to `meta_items`:
- `layer TEXT`
- `tags_json TEXT DEFAULT '[]'`
- `payload_json TEXT DEFAULT '{}'`
- `importance REAL DEFAULT 0.5`
- `backbone_eligible INTEGER DEFAULT 0`

2. Add `meta_backbone_registry` table:
- `id, layer, meta_item_id, scope, priority, lifecycle, created_at_utc, updated_at_utc`

3. Add indexes:
- `(kind, layer, lifecycle, scope)` on `meta_items`
- `(backbone_eligible, lifecycle)` on `meta_items`
- `(layer, scope, lifecycle, priority)` on `meta_backbone_registry`

### Implementation
1. Extend `memory/meta_store.py`:
- expanded kind validation
- layer/tag/payload CRUD
- registry CRUD/read methods

2. Keep policy bundle resolution API stable.

### Acceptance Criteria
1. Existing policy behavior remains unchanged.
2. New kinds upsert/list successfully.
3. Registry rows can be created/read/deactivated safely.

### Tests
1. `tests/test_meta_store_expanded_kinds.py`
2. `tests/test_meta_backbone_registry.py`
3. `tests/test_meta_policy_resolution.py` remains green unchanged.

### Risks
1. Migration compatibility with existing seeded policies.
Mitigation: no rewrite of old rows; only additive columns.

---

## Chunk 12: Situation Profile + Meta Budget Resolver

### Objective
Implement deterministic profile and budget resolution for layered meta retrieval.

### Scope
1. Build situation profile from runtime context.
2. Support legacy and new `memory_budget.meta` shapes.
3. Add feature flag for layered meta retrieval rollout.

### Implementation
1. New module: `controller/situation_profile.py`
- `build_situation_profile(...)`
- `select_meta_weight_profile(...)`

2. New module: `memory/meta_budget.py`
- normalize legacy numeric meta budget
- compute backbone/flex quotas

3. Add env flag:
- `EPOXY_META_LAYERED_RETRIEVAL=0|1` (default `0`).

### Acceptance Criteria
1. Profile generation deterministic for same input context.
2. Legacy configs continue to work (no runtime errors).
3. New budget shape produces stable quota outputs.

### Tests
1. `tests/test_situation_profile_builder.py`
2. `tests/test_meta_budget_normalization.py`

### Risks
1. Overfitting topic heuristics.
Mitigation: simple deterministic mapping + explicit override path.

---

## Chunk 13: Backbone Retrieval (Registry First, Tag Fallback)

### Objective
Deliver always-on meta backbone retrieval exactly matching hybrid selection rules.

### Scope
1. Load backbone by per-layer mins.
2. Fill from registry first, then fallback tags.
3. Preserve registry priority and non-displacement.

### Implementation
1. New module: `memory/meta_retrieval.py`
- `load_backbone_meta(...)`
- `score_backbone_fallback_candidates(...)`

2. Tag fallback requirements:
- active lifecycle.
- matching layer.
- either `backbone_eligible=1` or tag `kind:meta_backbone`.

### Acceptance Criteria
1. Registry fills each layer first.
2. Missing slots fill from fallback candidates.
3. Registry-selected items remain pinned when total exceeds candidates.

### Tests
1. `tests/test_meta_backbone_selection.py`
2. `tests/test_meta_backbone_registry_precedence.py`

### Risks
1. Sparse layers causing underfilled backbone.
Mitigation: graceful degrade and log underfill diagnostics.

---

## Chunk 14: Focus Band Retrieval + Seriousness Gating

### Objective
Use flex budget dynamically by situation profile and layer weights.

### Scope
1. Compute per-layer flex quotas.
2. Score/rank candidates by participant/topic/scope/importance/recency.
3. Penalize or suppress jokes for high seriousness.
4. Importance scoring contract:
- apply importance as a multiplier (`score *= (0.6 + 0.4 * importance)`).
- do not use importance as a hard exclusion gate.

### Implementation
1. Extend `memory/meta_retrieval.py`:
- `load_focus_meta(...)`
- seriousness compatibility scoring

2. Participant-aware selection:
- prioritize `subject:person:<id>` for relational contracts and people core.

### Acceptance Criteria
1. Focus selection respects per-layer quotas.
2. High seriousness requests include zero or near-zero joke layer items.
3. Low-stakes requests can include texture within budget.

### Tests
1. `tests/test_meta_focus_quota_allocation.py`
2. `tests/test_meta_seriousness_gating.py`
3. `tests/test_meta_participant_priority.py`

### Risks
1. Overly rigid allocation.
Mitigation: deterministic rebalancing when some layers are sparse.
2. Stale high-importance items could dominate without recency balance.
Mitigation: keep importance multiplicative and preserve recency/policy/lifecycle gating.

---

## Chunk 15: Mode Blend from Relational Contracts

### Objective
Compute runtime mode blend from relational contracts + situation overlays and expose to controller.

### Scope
1. Parse contract payload:
- `default_modes`, `context_overrides`, tone bounds and constraints.
2. Merge actor/target contracts where relevant.
3. Emit normalized mode weights for prompt assembly.

### Implementation
1. New module: `controller/mode_blend.py`
- `compute_mode_blend(...)`
- `apply_context_overrides(...)`

2. Integrate into retrieval pack return:
- `build_meta_pack(...)` returns `mode_blend`.

### Acceptance Criteria
1. Context override applies when matching channel/surface/topic.
2. Output mode blend sums to ~1.0 and remains stable.
3. Missing contracts degrade to default blend.

### Tests
1. `tests/test_mode_blend_resolution.py`
2. `tests/test_relational_contract_overrides.py`

### Risks
1. Conflicting actor/target contracts.
Mitigation: explicit merge precedence (actor primary in DMs, actor+target balanced in coaching).

---

## Chunk 16: Runtime Integration (Mention + DM Draft)

### Objective
Use meta pack + mode blend in live prompt assembly while preserving policy constraints and existing flows.

### Scope
1. Mention runtime path integration.
2. DM draft runtime path integration.
3. Episode log instrumentation of selected meta ids/layers and mode profile.

### Implementation
1. Update `misc/events_runtime.py`:
- call meta retrieval when feature flag enabled.
- append compact meta/mode blocks to prompt.

2. Update `controller/prompt_assembly.py`:
- deterministic formatting blocks:
  - backbone
  - focus by layer
  - mode blend

3. Keep existing policy enforcement path unchanged.

### Acceptance Criteria
1. Runtime responses include meta guidance path only when flag enabled.
2. Policy clamp behavior remains unchanged from baseline.
3. Episode logs include meta selection IDs only (no raw sensitive payload dumps).

### Tests
1. `tests/test_events_runtime_meta_pack.py`
2. `tests/test_dm_draft_meta_pack.py`
3. Existing policy tests remain green.

### Risks
1. Prompt bloat.
Mitigation: strict char caps and per-layer item caps.

---

## Chunk 17: Ops Commands for Backbone and Meta Graph

### Objective
Give operators practical tooling to curate backbone and links.

### Scope
1. Add commands:
- `!meta.backbone.list`
- `!meta.backbone.add <layer> <meta_id> [scope] [priority]`
- `!meta.backbone.remove <id>`
- `!meta.find <query> [layer] [kind]`
- `!meta.link <from_ref> <to_ref> <relation>`

2. Validate ref grammar:
- `memory:<id>`, `summary:<id>`, `episode:<id>`, `meta:<id>`, `person:<id>`.

### Implementation
1. `misc/commands/commands_memory.py` and/or new `commands_meta.py`.
2. `memory/link_service.py` for ref validation and link writes.

### Acceptance Criteria
1. Operators can curate registry without direct SQL.
2. Invalid refs are rejected with clear errors.
3. Link writes remain lifecycle-aware and auditable.

### Tests
1. `tests/test_meta_commands_backbone.py`
2. `tests/test_meta_link_ref_validation.py`

### Risks
1. Command misuse or accidental global edits.
Mitigation: owner-only and explicit confirmation text patterns.

---

## Chunk 18: Eval Harness + Promotion Gates

### Objective
Gate rollout using deterministic evals specific to layered meta behavior.

### Scope
1. Add layered-meta eval harness.
2. Add fixture suites and regression gates.
3. Define go/no-go criteria for default-on.

### Implementation
1. New eval module:
- `eval/meta_layered_retrieval.py`

2. Fixtures:
- `tests/fixtures/eval_meta_layered_retrieval.json`

3. Tests:
- `tests/test_eval_meta_layered_retrieval.py`

### Go/No-Go Criteria
1. Existing baseline tests pass:
- memory recall baseline,
- controller policy adherence baseline.

2. New meta eval passes:
- registry precedence,
- quota allocation,
- seriousness gating,
- contract override behavior.

3. Policy violation count remains zero in fixture scenarios.

### Rollout
1. Enable `EPOXY_META_LAYERED_RETRIEVAL=1` in staging only.
2. Observe episode logs and eval outputs for 3-7 days.
3. Promote to production default only after stable pass window.

## 6) File-Level Change Map

Core touched paths across chunks:
1. `bot.py`
2. `config/defaults.py`
3. `memory/service.py`
4. `memory/store.py`
5. `memory/meta_store.py`
6. `memory/meta_retrieval.py` (new)
7. `memory/meta_budget.py` (new)
8. `memory/lifecycle_service.py` (new)
9. `memory/link_service.py` (new)
10. `controller/situation_profile.py` (new)
11. `controller/mode_blend.py` (new)
12. `controller/prompt_assembly.py`
13. `misc/events_runtime.py`
14. `misc/runtime_wiring.py`
15. `misc/commands/commands_memory.py` (and/or `commands_meta.py` new)
16. `migrations/0019_*.py` onward
17. `eval/*.py`, `tests/*`, `tests/fixtures/*`

## 7) Validation Commands Per Chunk

Run every chunk:
1. `python -m compileall -q bot.py config controller db ingestion jobs memory misc retrieval scripts tests eval`
2. `python -m unittest -v`

Run targeted tests for changed chunk before full suite.

## 8) Documentation Deliverables Per Chunk

For each non-trivial chunk:
1. Add `docs/changes/YYYY-MM-DD-<chunk-name>.md`
2. Fill using `docs/epoxy_change_summary_template.md`.

Also keep these docs synchronized when behavior changes:
1. `docs/developer_reference.md`
2. `docs/architecture.md`
3. `MEMORY.md` for stable design decisions.

## 9) Explicit Out-of-Scope Items

1. Autonomous controller self-training (M6+).
2. Postgres migration execution (schema remains SQLite-compatible now).
3. New broad capabilities unrelated to memory/controller architecture.

## 10) End-State Definition of Done

Done means all are true:
1. Memory capture can run in review-gated modes with audit trail.
2. Operators can approve/reject candidate memories safely.
3. Layered meta retrieval runs with hybrid backbone and dynamic focus band.
4. Relational contracts directly influence runtime mode blend.
5. Policy constraints remain hard-precedence and regression-tested.
6. Eval gates exist and are required before enabling layered retrieval by default.
