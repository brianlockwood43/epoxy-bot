# Epoxy M4 Chunk Tracker (Execution Checklist)

Date: 2026-02-13  
Primary Plan: `docs/feb_13_chunked_decision_complete_plan.md`  
Purpose: Operational tracker for chunk-by-chunk implementation, validation, and review.

## 1) How To Use

1. Before starting a chunk, set owner + status + start date.
2. During implementation, check items as they are completed.
3. Before merge, complete validation and docs checks.
4. After merge, set end date and add short outcome note.

Status values:
- `planned`
- `in_progress`
- `blocked`
- `in_review`
- `done`

## 2) Chunk Status Board

| Chunk | Title | Owner | Status | Start Date | End Date | PR/Branch | Notes |
|---|---|---|---|---|---|---|---|
| 8 | Memory Review Mode + Candidate Lifecycle | Codex | in_review | 2026-02-15 |  |  | Deferred follow-up: !profile -> meta-memory store after meta-layer expansion; not part of Chunk 8. |
| 9 | Review Workflow Commands + Audit Log | TBD | planned |  |  |  |  |
| 10 | Typed Tag Contract + Provenance Field | TBD | planned |  |  |  |  |
| 11 | Meta Model Expansion + Backbone Registry | TBD | planned |  |  |  |  |
| 12 | Situation Profile + Meta Budget Resolver | TBD | planned |  |  |  |  |
| 13 | Backbone Retrieval (Registry First, Tag Fallback) | TBD | planned |  |  |  |  |
| 14 | Focus Band Retrieval + Seriousness Gating | TBD | planned |  |  |  |  |
| 15 | Mode Blend from Relational Contracts | TBD | planned |  |  |  |  |
| 16 | Runtime Integration (Mention + DM Draft) | TBD | planned |  |  |  |  |
| 17 | Ops Commands for Backbone and Meta Graph | TBD | planned |  |  |  |  |
| 18 | Eval Harness + Promotion Gates | TBD | planned |  |  |  |  |

## 3) Per-Chunk Checklist Template

Copy this block for each chunk in your execution notes if you want detailed run tracking.

```md
### Chunk <N>: <Title>
- Owner: <name>
- Status: planned|in_progress|blocked|in_review|done
- Start: YYYY-MM-DD
- End: YYYY-MM-DD
- Branch/PR: <id>

Implementation
- [ ] Scope implemented per plan.
- [ ] No out-of-scope behavior changes.
- [ ] Backward compatibility preserved.

Schema / Migration
- [ ] Migration added (if required).
- [ ] Migration is additive and rollback-safe.
- [ ] Existing rows/backfills validated.

Tests
- [ ] New tests added for changed behavior.
- [ ] Existing related tests still pass.
- [ ] Regression risks covered by deterministic fixture(s).

Validation
- [ ] `python -m compileall -q bot.py config controller db ingestion jobs memory misc retrieval scripts tests eval`
- [ ] targeted tests run:
- [ ] full suite run:

Docs / Change Summary
- [ ] `docs/changes/YYYY-MM-DD-<chunk-name>.md` created from template.
- [ ] Developer docs updated if operator behavior changed.
- [ ] Plan doc references remain accurate.

Release Decision
- [ ] Ready for merge.
- [ ] Follow-ups logged.
- Outcome notes:
```

## 4) Chunk-Specific Acceptance Checks

## Chunk 8
- [ ] Review mode env supported: `off|capture_only|all`.
- [ ] `capture_only`: auto-capture/mining -> `candidate`; manual `!remember` -> `active`.
- [ ] `all`: default writes -> `candidate` unless explicit owner override.
- [ ] Recall paths remain `active`-only.

## Chunk 9
- [ ] Commands implemented: `!memreview`, `!memapprove`, `!memreject`.
- [ ] `memory_audit_log` table exists and is written on every review action.
- [ ] Review metadata fields persisted on `memory_events`.

## Chunk 10
- [ ] Typed tag contract introduced and validated.
- [ ] `memory_events.type` mapped consistently from kind tags.
- [ ] `provenance_json` stored for new memory writes.

## Chunk 11
- [ ] Expanded meta kinds accepted by store APIs.
- [ ] `meta_items` layering/payload/tag fields added.
- [ ] `meta_backbone_registry` schema + CRUD support added.
- [ ] Existing policy resolution behavior unchanged.

## Chunk 12
- [ ] Situation profile builder implemented and deterministic.
- [ ] Legacy and new `memory_budget.meta` shapes both supported.
- [ ] Feature flag wired: `EPOXY_META_LAYERED_RETRIEVAL`.

## Chunk 13
- [ ] Backbone retrieval uses registry-first selection.
- [ ] Tag fallback fills only unfilled layer slots.
- [ ] Registry-selected items are not displaced.

## Chunk 14
- [ ] Flex quotas computed from selected weight profile.
- [ ] Focus-band retrieval respects quotas and layer priorities.
- [ ] High-seriousness contexts suppress `texture/inside_joke`.

## Chunk 15
- [ ] Relational contract payload parsed (`default_modes`, `context_overrides`).
- [ ] Mode blend output is normalized and stable.
- [ ] Missing contracts degrade to safe defaults.

## Chunk 16
- [ ] Mention runtime includes meta pack + mode blend when flag enabled.
- [ ] DM draft runtime includes meta pack + mode blend when flag enabled.
- [ ] Policy directive/clamps remain intact and regression-safe.
- [ ] Episode logs include selected meta IDs/layers (no sensitive text dump).

## Chunk 17
- [ ] Commands implemented:
  - `!meta.backbone.list`
  - `!meta.backbone.add`
  - `!meta.backbone.remove`
  - `!meta.find`
  - `!meta.link`
- [ ] Ref grammar validation enforced:
  - `memory:<id>`, `summary:<id>`, `episode:<id>`, `meta:<id>`, `person:<id>`

## Chunk 18
- [ ] New layered-meta eval harness + fixtures implemented.
- [ ] Existing eval baselines still pass.
- [ ] Promotion gate decision criteria documented and applied.

## 5) Blocker / Risk Log

| Date | Chunk | Severity | Blocker / Risk | Owner | Mitigation / Next Step | Status |
|---|---|---|---|---|---|---|
| 2026-02-15 | 8 | low | !profile currently writes atomic memory_events; intended long-term target is meta-memory. | Brian + Codex | Track migration design after Chunk 11 schema expansion. | open |
|  |  |  |  |  |  | open |

## 6) Final Rollout Checklist

- [ ] All chunks 8-18 are `done`.
- [ ] All chunk change summaries exist under `docs/changes/`.
- [ ] Staging run with `EPOXY_META_LAYERED_RETRIEVAL=1` completed.
- [ ] Eval gates pass for layered meta retrieval + existing baselines.
- [ ] Production default decision recorded (date + owner).
