# Epoxy Agents Overview

This document orients AI coding assistants (and human contributors) to the **Epoxy** project: what it is, where it will be used, and what we’re trying to build over the long term.

Epoxy is not “just another chatbot.” It is intended to become a **resident teammate** inside the Lumeris ecosystem, with persistent memory, an explicit model of human development, and a controller layer that learns how to show up well for different people and contexts over time.

This document is the **canonical design reference** for Epoxy’s memory + controller system. Unless for an **explicitly separate function** (for example, automated Discord announcements), new code should align with this architecture (or explicitly extend it) rather than introducing parallel ad-hoc mechanisms.


---

## 1. Context: Where Epoxy Lives

**Primary environment**

- Epoxy runs as a bot inside the **Lumeris** community (Discord + future surfaces).
- Lumeris is a high-trust motorsport / human-development community with:
  - structured coaching,
  - explicit norms around conflict and care,
  - long-term personal and organizational arcs.

**Roles Epoxy will play**

- Personal assistant / co-pilot for:
  - founder and core leads (Brian, Tom, etc.),
  - coaches,
  - individual members (in a more bounded way).
- Organizational analyst:
  - surfacing patterns across channels and time,
  - helping plan workshops, announcements, and experiments.
- Developmental support:
  - helping track contracts, arcs, and awareness-level shifts,
  - offering context-appropriate reflections and suggestions.

**Surfaces (current and planned)**

- Discord bot (DMs, public channels, coach/ops channels).
- Offline jobs (nightly “sleep” / integration runs, analysis jobs).
- Future: additional integrations (e.g. docs, dashboards) that all speak to the **same underlying memory + controller system**.

---

## 2. Overall Goals

High-level goals for Epoxy:

1. **Continuity:**  
   Maintain rich, long-lived memory of people, events, decisions, and organizational arcs, with provenance and the ability to audit “why do we believe this?”

2. **Situated intelligence:**  
   Epoxy should behave differently in different contexts:
   - founder DM vs member DM,
   - public announcement vs conflict debrief,
   - light “glue-eating” banter vs serious contract work.

3. **Human-development aware:**  
   Epoxy’s inner model of humans is based on:
   - **awareness layers** (L2–L5+),
   - **identity / contract formation** (how people bind self-worth to patterns),
   - **arcs** (how those contracts and layers change over time).
   This isn’t just documentation; it should influence what memories are retrieved and what interventions the controller chooses.

4. **Safe, bounded power:**  
   Epoxy will eventually be a deep team member for leadership, but not an omniscient panopticon for members.
   - Access and capabilities are **context-gated** (per channel / DM type).
   - There are explicit **policies / invariants** about what she can and cannot say or do in member-facing contexts.

5. **Self-improving controller (under governance):**  
   Over time, Epoxy’s controller will learn from experience:
   - log episodes,
   - evaluate outcomes,
   - propose updates to its own behavior,
   - all under human review, with tests and rollback.

---

## 3. Core Architectural Ideas

The system is built around two major pillars:

1. **Memory stack**
2. **Controller stack**

Codex should assume that most non-trivial features touch at least one of these.

### 3.1 Memory Stack

The memory stack handles *what Epoxy knows*.

Key concepts:

- **Atomic memories (`MemoryItem`)**  
  Individual facts, events, preferences, relationships, etc., with:
  - provenance (who said it, where, when),
  - scope (global vs project vs channel),
  - lifecycle (candidate, active, archived, deprecated),
  - stability / confidence flags.

- **Summaries (`SummaryItem`)**  
  Compressed representations:
  - event digests,
  - topic gists,
  - decision logs,
  - preference profiles.

- **Meta-layer (`MetaItem`)**  
  Two distinct kinds:
  - **Narratives / arcs** — higher-order stories about people and the organization.
  - **Policies / invariants** — hard rules and constraints (e.g. “don’t reveal other members’ private info in member DMs”).

- **Links (`Link`)**  
  Graph edges tying everything together:
  - supports / elaborates / contradicts / example_of / caused_by / depends_on / supersedes.

Supporting services:

- Ingestion, retrieval, lifecycle & verification, contradiction/merge, evaluation harness.

### 3.2 Controller Stack

The controller stack handles *how Epoxy shows up* in a given context.

Key concepts:

- **ContextProfile**  
  Describes the calling context:
  - caller type (founder, core lead, coach, member, external),
  - surface (DM, coach channel, public channel, system job),
  - allowed capabilities and sensitivity rules.

- **UserProfile**  
  Minimal per-human profile:
  - estimated awareness layer (L2–L5),
  - dev arcs (linked narratives),
  - tone preferences,
  - risk flags.

- **ControllerConfig**  
  Tunable knobs (per global scope / context / user):
  - persona (guide, analyst, coach, ops, system),
  - depth (how far into contracts/identity to go),
  - strictness,
  - intervention level (how proactive to be),
  - memory budgets (hot/warm/cold/summaries/meta),
  - tool budgets.

- **EpisodeLog**  
  Logged interaction traces used for learning:
  - context info,
  - which ControllerConfig was used,
  - what memories were retrieved,
  - assistant / user excerpts,
  - explicit and implicit outcome signals,
  - optional human notes / “gold” rewrites.

Controller service responsibilities:

- Select appropriate `ControllerConfig` for each request.
- Shape retrieval (which scopes/tiers to use).
- Enforce policies / invariants.
- Log every episode for future analysis.
- Eventually (M6+), support **offline learning** to refine `ControllerConfig` under human review.

⚠️ Important: Controller learning (M6+) must NOT be implemented as fully autonomous weight updates without:
- an evaluation harness,
- a review/approval step,
- and a rollback path.
Until explicitly noted otherwise, any “learning” should be:
- offline,
- behind a feature flag,
- and gated by human review.


---

## 4. Governance & Safety Principles

Codex should optimize for **alignment with these principles**, not just raw functionality:

- **Contextual access control**
  - Different channels/DM types map to different capabilities.
  - Example: founder DMs may allow cross-member analysis; member DMs must not reveal other members’ private details.

- **Auditability**
  - Every non-trivial change to memory or controller behavior should be traceable:
    - what job or human action caused it,
    - what objects were touched,
    - how to roll back.

- **Human-in-the-loop**
  - Automated suggestions for new narratives/policies/configs should go through review queues.
  - Certain operations are never fully autonomous (e.g. redefining core policies).

- **Conservative member-facing behavior**
  - In ambiguous situations, prefer:
    - protecting privacy,
    - lowering intervention depth,
    - inviting human follow-up.

---

## 5. Epoxy Memory + Controller Roadmap (M0–M7)

Below is the end-to-end core Epoxy system spec.

---

## 0 - Canonical objects (data model)

### 0.1 `MemoryItem` (atomic memory)

Represents a single fact/event/preference/etc.

**Fields**

- `id`
- `type`: `event | preference | concept | relationship | policy | instruction | skill | artifact_ref | note`
- `title` (short)
- `content` (canonical text)
- `source`:
  - `origin`: `chat | tool | user_edit | imported`
  - `message_ids[] / artifact_ids[]`
- `timestamp_start`, `timestamp_end` (optional)
- `people[] / entities[] / topics[]` (tags)
- `provenance`:
  - `evidence_spans[]` (message id + offset ranges if you can)
  - `author`: `user | assistant | system | mixed`
- `confidence`: `0–1`
- `stability`: `volatile | medium | stable` (how likely it changes)
- `scope`: `global | project:<name> | thread:<id> | channel:<name>` (prevents bleed)
- `tier`: `hot | warm | cold | archive`
- `lifecycle`: `candidate | active | archived | deprecated | deleted`
- `created_at`, `updated_at`, `last_verified_at`
- `expiry_at` (optional)
- `contradicts[]` (other `MemoryItem` ids)
- `supersedes[] / superseded_by` (versioning)

---

### 0.2 `SummaryItem` (M3 artifact)

Compressed representation of multiple MemoryItems.

**Fields**

- `id`
- `summary_type`: `event_digest | topic_gist | decision_log | preference_profile`
- `scope` (same scheme as above)
- `covers_memory_ids[]`
- `content`
- `confidence`, `stability`, `last_verified_at`
- `lifecycle`, `tier`
- `generated_by`: `job_id`, `model_version`, `prompt_hash`

---

### 0.3 `MetaItem` (M4+; two explicitly separate kinds)

#### A - Narrative / Arc

- `id`
- `kind: "narrative"`
- `name`  
  e.g. `"Brian: glue-to-systems integrator arc"`
- `signals[]` (patterns observed; citations to `MemoryItem` / `SummaryItem`)
- `implications[]` (how to respond / what to optimize for)
- `scope`, `confidence`, `stability`, `lifecycle`
- `links`: `supports_memory_ids[]`, `supported_by_memory_ids[]`

#### B - Policy / Invariant (hard constraints)

- `id`
- `kind: "policy"`
- `statement` (machine-checkable if possible)
- `priority`: `critical | high | medium | low`
- `applies_to`: `chat_mode | group_chat | safety | memory_ops | tone | tools | controller`
- `scope`, `evidence`, `confidence`, `lifecycle`
- `conflict_resolution_rule` (explicit, not implied)

---

### 0.4 `Link` (graph edge)

- `from_id`, `to_id`
- `relation`: `supports | elaborates | contradicts | example_of | caused_by | depends_on | supersedes`
- `weight`, `confidence`
- `created_by`: `human | system`
- `lifecycle`

---

### 0.5 Controller objects (new)

#### 0.5.1 `ContextProfile`

Describes *where* a request is coming from.

- `id`
- `caller_type`: `founder | core_lead | coach | member | external`
- `surface`: `dm | coach_channel | public_channel | system_job`
- `channel_id` / `guild_id`
- `sensitivity_policy_id` (link to MetaItem(kind=policy))
- `allowed_capabilities[]`  
  e.g. `["cross_member_analysis", "strategy_access", "anonymized_patterns_only"]`

#### 0.5.2 `UserProfile`

Thin “who is this human” object, backed by memories/meta.

- `id` (user id)
- `layer_estimate`: `L2 | L3 | L4 | L5 | mixed | unknown`
- `risk_flags[]` (manual tags)
- `preferred_tone`: `gentle | direct | strict | playful`
- `dev_arc_meta_ids[]` (linked narratives)
- `last_seen_at`

#### 0.5.3 `ControllerConfig`

The tunable knobs the controller learns over time.

- `id`
- `scope`: `global | caller_type | context_profile_id | user_id`
- `persona`: `guide | analyst | coach | ops | system`
- `depth`: `0–1` (how far into contracts/identity)
- `strictness`: `0–1`
- `intervention_level`: `0–1` (unsolicited guidance vs pure answering)
- `memory_budget`:
  - `hot`, `warm`, `cold`, `summaries`, `meta`
- `tool_budget[]` (which tools are allowed, rate limits)
- `last_trained_at`
- `lifecycle`: `active | candidate | deprecated`

#### 0.5.4 `EpisodeLog`

What the controller learns from.

- `id`
- `timestamp`
- `context_profile_id`
- `user_id`
- `controller_config_id` (what config was used)
- `input_excerpt`
- `assistant_output_excerpt`
- `retrieved_memory_ids[]`
- `tags[]` (topic, risk level, etc.)
- `outcome_signals`:
  - `explicit_rating` (`-2..+2` or null)
  - `implicit_signals` (reply latency, emoji, follow-up, churn markers)
- `human_notes` (optional “gold feedback”, rewrites)

---

# Core services

These exist from M1 onward.

### 1.1 Ingestion service

Turns raw chat/tool outputs into candidate `MemoryItem`s.

- attaches provenance/evidence pointers
- assigns initial `confidence`, `stability`, `scope`

---

### 1.2 Retrieval service

Tier-aware hybrid retrieval (not just vector search).

**Inputs**

- query
- current task context (user, channel, task type)
- scope constraints

**Outputs**

- ranked set of `MemoryItem` + `SummaryItem` + `MetaItem` (later),
- with diversity + tier budgets

Must support:

- hybrid scoring: semantic + keyword + recency + priority + scope match
- diversity sampling: prevent 10 near-duplicates
- budgeting: e.g. `8 hot, 6 warm, 3 cold, 2 summaries, 2 policies`
- explainability hooks: why items were retrieved (scores)

---

### 1.3 Lifecycle & verification service

- promotions/demotions between `candidate | active | archived | deprecated | deleted`
- handles `expiry_at`, `last_verified_at`
- supports “user corrected this” → lower confidence / deprecate / supersede

---

### 1.4 Contradiction & merge service

- detects likely conflicts (same entity, opposing claims)
- proposes merges/dedupes
- creates `supersedes` edges rather than overwriting history

---

### 1.5 Evaluation harness (memory)

- measures retrieval precision/recall on a small fixed suite of prompts
- measures “memory drift” after consolidation
- measures contradiction rate & correction rate
- later gates autonomy (M7)

---

### 1.6 Controller service (new)

The policy head that decides **how Epoxy should show up** for a given request.

**Inputs**

- `ContextProfile` (caller, surface, channel)
- `UserProfile` (if applicable)
- current message + recent chat state
- relevant `MetaItem(kind=policy)` (constraints)
- current `ControllerConfig` (selected by scope / context)

**Outputs**

- finalized `ControllerConfig` for this turn:
  - persona, depth, strictness, intervention level
  - memory & tool budgets
- retrieval query shaping:
  - what scopes to search,
  - which tiers to emphasize,
  - whether to prefer narratives vs raw atoms
- post-processing directives:
  - e.g. “don’t mention other members by name”

**Responsibilities**

- **Selection:** choose an appropriate `ControllerConfig` based on context.
- **Logging:** emit an `EpisodeLog` for every turn.
- **Learning (M5+):** periodically update `ControllerConfig` parameters from batches of `EpisodeLog` + human feedback, under guardrails.

---

### Evaluation harness (controller)

- separate small suite of **scenarios**:
  - “member DM asking about life contracts”
  - “coach channel conflict postmortem”
  - “public announcement copy”
- measures:
  - tone fit,
  - depth appropriate to layer,
  - policy adherence (no-fly zones respected),
  - human rater score
- used to gate new controller configs / learning jobs before they go live.

---

# Stages (memory + controller)

Each M-stage now has a **memory objective** and a **controller state**.

---

### M0 — Baseline

**Memory**

- no persistent storage
- purely current context

**Controller**

- none (raw model + single static system prompt)

**Exit**

- n/a

---

### M1 — Persistent atomic memory

**Goal (memory)**  
Store events/preferences/etc. reliably with evidence + reversibility.

**Build**

- `MemoryItem` schema + DB tables
- Ingestion service creates candidate items
- Human promotion path: `candidate → active`
- Lifecycle state machine + “supersede” edits (never overwrite silently)

**Minimum retrieval**

- simple filtered search by scope + recency (even before full hybrid)

**Controller @ M1**

- Rule-based, prompt-only:
  - different base prompts for `founder | coach | member | public`
- No learning; configs are hand-written.
- No `EpisodeLog` yet, or only for debugging.

**Exit**

- You can answer:  
  “why do we believe this?”, “who said it?”, “can we undo it?”  
- Controller behaves differently per **role**, but is static.

---

### M2 — Temporal tiers + disciplined retrieval substrate

**Goal (memory)**  
Stop cold memory bleed; make retrieval robust and predictable.

**Build**

- Tiering rules (`hot/warm/cold/archive`) driven by:
  - recency + access frequency + stability + priority
- Retrieval service v1:
  - hybrid scoring
  - per-tier budgets
  - scope gating (project/thread/channel)
  - diversity sampling
- Cleanup jobs:
  - auto-demote by inactivity
  - archive/deprecate by expiry or contradiction resolution

**Controller @ M2**

- Uses `ContextProfile`:
  - channel-level policies: e.g. member DMs vs coach channels.
- Can:
  - choose different **memory budgets** per context,
  - decide “summaries allowed?” or “raw atoms only?”
- Still manually tuned, but decisions are explicit code paths, not just prompt text.

**Exit**

- “Cold storage is real” (doesn’t show unless needed).
- Retrieval is reproducible enough to test.
- Controller policies per **surface** (DM vs public vs coach) are explicit and stable.

---

### M3 — Abstraction layer: summaries + consolidation

**Goal (memory)**  
Reduce context load without losing truth.

**Build**

- `SummaryItem` types (at least these 4):
  - `event_digest` (time-bounded)
  - `topic_gist` (conceptual cluster)
  - `decision_log` (what was decided + why)
  - `preference_profile` (stable user prefs with exceptions)
- Consolidation jobs:
  - dedupe cluster → merge proposal
  - contradiction detection → “needs review” + candidate resolution summary
  - summarization that keeps links to source `MemoryItem`s
- Retrieval service v2:
  - can return summaries preferentially when context is tight
  - can “drill down” to underlying atoms on demand

**Controller @ M3**

- Begins **logging `EpisodeLog`s** for selected surfaces (e.g. founder DMs, coach channels).
- Can:
  - choose when to prefer `SummaryItem` vs raw `MemoryItem`,
  - pick different personas / tones per `ContextProfile` using `ControllerConfig`.
- No automated learning yet:
  - configs are changed by hand based on what you see in logs.

**Exit**

- Summaries are auditable (linked to sources).
- Consolidation reduces total active items without losing correctness.
- Controller + Episode logs exist, but you are still the “learning algorithm.”

---

### M4 — Manual meta-layer (narratives + policies) + policy-aware controller

**Goal (memory)**  
Create stable guiding structures that don’t get confused with vibes.

**Build**

- `MetaItem(kind="narrative")`
- `MetaItem(kind="policy")` with priority + scope + conflict rules
- UI/commands for manually:
  - creating meta items
  - linking meta ↔ memory

- Retrieval service v3:
  - always retrieve relevant policies/invariants first
  - narratives are optional, lower priority unless explicitly useful

**Controller @ M4**

- Now **policy-aware**:
  - pulls `MetaItem(kind="policy")` relevant to current `ContextProfile`
  - enforces no-fly zones (e.g. “don’t reveal other members’ DMs in member context”)
- `ControllerConfig` gains:
  - `depth`, `strictness`, `intervention_level` tuned per user/context.
- Still no automatic weight updates, but:
  - you can manually adjust configs for individuals (e.g. Caleb vs Gio).

**Exit**

- Hard constraints are enforced consistently across all responses.
- Narratives help tone/strategy without overriding constraints.
- Controller can show **different personalities** safely in different rooms.

---

### M5 — Assisted linking + controller evaluation / reporting

**Goal (memory)**  
Scale graph maintenance without letting the model hallucinate structure.

**Build**

- Suggestions queue:
  - “these 7 memories likely support narrative X”
  - “this preference looks stable; propose policy?”
  - “these 3 items are duplicates; propose merge”
- Human approval flow writes `Link` objects + lifecycle updates.

**Controller @ M5**

- Episode logging now **systematic** (across key contexts).
- Weekly controller reports:
  - per-context performance:
    - average explicit rating,
    - policy violation count (should be ~0),
    - “too deep / too shallow” tags.
- Manual tuning loop:
  - you adjust `ControllerConfig` parameters from these reports.
- Still **human-driven learning**, but supported by metrics.

**Exit**

- High acceptance rate of memory/meta suggestions.
- Low correction rate afterward.
- Controller has a **clear measurement loop**; you can see where it over/under-shoots.

---

### M6 — Assisted meta-creation + offline controller learning

**Goal (memory)**  
The model starts proposing new narratives/policies safely.

**Build**

- Proposal templates:
  - Narrative proposal: name + observed signals + supporting evidence links
  - Policy proposal: statement + priority + scope + conflicts + evidence
- Review queue + “require evidence minimum” (e.g. ≥3 supporting items, high confidence)

**Controller @ M6**

- Introduce **offline learning jobs**:
  - periodically sample `EpisodeLog`s with strong signals (good/bad + human notes).
  - train a simple model or heuristic optimizer that suggests new `ControllerConfig` parameters:
    - e.g. “for caller_type=member, context=dm, topic=identity, reduce depth from 0.8 → 0.5.”
- Human approval:
  - candidate configs are tested in the **evaluation harness** and, if they pass, promoted to active.
- Effectively: controller starts **learning from experience**, but under human veto.

**Exit**

- Meta-proposals are mostly good; low “wtf did it invent” rate.
- Controller configs produced by offline learning:
  - perform at least as well as hand-tuned ones on eval suite,
  - and don’t increase policy violations.

---

### M7 — Autonomous management + audits + rollback (memory + controller)

**Goal (memory)**  
Autonomy, but with guardrails and measurable drift control.

**Build (memory)**

- Autonomous jobs allowed to:
  - demote/archive by rules,
  - generate summaries,
  - propose + auto-accept low-risk merges.
- Audit cycles:
  - weekly drift report,
  - contradiction report,
  - “top 20 most-used memories; verify freshness”.
- Rollback tooling:
  - revert merges,
  - restore deprecated items,
  - trace which job caused which change.

**Controller @ M7**

- Limited **self-tuning** in low-risk regions:
  - small, bounded adjustments to depth/strictness/intervention per context,
  - gated by eval harness + drift thresholds.
- Automatic “safety clamp”:
  - if evals detect regression in tone fit or policy adherence, revert to last known good config.
- Clear governance:
  - only certain contexts (e.g. founder DM, lab channel) allow aggressive experimentation;
  - member-facing configs change slowly and only after passing evaluation.

**Exit**

- System improves over time without silently corrupting itself:
  - memory stays coherent,
  - controller behaves more “Brian-like” with less manual tuning,
  - guardrails ensure no surprise personality or policy shifts.

---

### Future Work: Community State Dashboards (Meta-Meta Layer)

**Stage:** Post M4 (later-phase enhancement, not part of current M3 → M4 scope)  
**Status:** Intent documented; design direction sketched, not implemented.

---

#### Goal

Introduce a **community state “dashboard” layer** on top of Epoxy’s existing meta-memory that can summarize the *vibe/health of the community* over time, without becoming a new source of ground-truth or directly driving behavior.

Think of these as **aggregated health indicators and trend summaries**, derived from existing episodes + meta (people arcs, org arcs, etc.), primarily for **human operators** and higher-level analysis.

---

#### Key Properties

- **Aggregated, not individual**
  - Dashboards operate on **groups/cohorts**, not on single people.
  - Examples:
    - `community_state:lumeris_overall`
    - `cohort_state:mastery_drivers`
    - `cohort_state:new_joiners_last_60d`

- **Time-bounded and explicitly scoped**
  - Each dashboard item is tied to a **time window**:
    - `window_start`, `window_end`, `computed_at`.
  - No “forever true” vibe statements; they always answer “during this period.”

- **Provenance-aware**
  - Each dashboard explicitly records **how it was computed**:
    - which metrics,
    - which meta types (person cores, arcs, etc.),
    - example episodes or aggregates used.
  - Always includes references like `ref: meta:<id>` and/or aggregate counts instead of opaque magic.

- **Ephemeral influence by default**
  - **Default rule:** dashboards **do not influence Epoxy’s behavior directly**.
  - They are used as **operator-facing instrumentation**, not as hidden priors.
  - Any behavior changes based on dashboards must be **introduced via human-reviewed policy/meta changes**, not automatically.

- **Low-frequency updates**
  - Updated on a **scheduled basis** (e.g. daily/weekly) or at operator-triggered checkpoints.
  - Emphasis on **trend tracking** rather than fast-reactive behavior.

---

#### Example Shape (Conceptual)

A `MetaItem(kind='community_state')` might include:

- Time window and identifiers:
  - `window_start`, `window_end`, `computed_at`,
  - `scope` (e.g. `community:lumeris`, `cohort:mastery`).
- A small set of **health indicators** (normalized 0–1 or low/med/high):
  - trust/safety,
  - tension/conflict level,
  - burnout/fatigue risk,
  - cohesion/alignment.
- **Top themes**:
  - short descriptions of dominant narratives (e.g. “boundary recalibration,” “money stress,” “excitement about Epoxy”).
- **Provenance**:
  - references to metrics, meta, or summary episodes used (counts, IDs, or tags).

These are **summaries with links**, not standalone truth.

---

#### Intended Use

- Give Brian and other operators a **high-level read** on how the community is doing over time.
- Support:
  - deciding what workshops or communications to prioritize,
  - retro analysis (“what did the vibe look like before/after event X?”),
  - designing policy/meta changes for Epoxy’s behavior.

- Epoxy may:
  - **surface dashboards explicitly when asked** (e.g. “show me current community_state”),
  - or use them **only via human-confirmed policies** (e.g. “for the next month, treat community as in a fragile integration phase”).

---

#### Explicit Non-Goals (Guardrails)

- **No automatic behavioral control**
  - Dashboards must **not autonomously change** relational contracts, policies, or tone rules.
  - Any behavior shifts require **human-reviewed updates** to:
    - policy meta,
    - relational contracts,
    - or controller config.

- **No storing per-person judgements here**
  - Individual people’s arcs and states remain in:
    - `person_core`,
    - `narrative`,
    - and related per-person meta.
  - Community dashboards only describe **aggregated patterns**, never “this person is X.”

- **No hardcoding narratives about Lumeris**
  - Dashboards should be treated as **snapshots with uncertainty**, not permanent story tiles.
  - Retrieval/UI should highlight **time window + confidence**, not present them as timeless truths.

---

#### Implementation Approach (Later)

1. **Start with ephemeral evaluators**
   - Implement a `community_health_eval` step that computes **in-memory** health metrics from:
     - existing meta,
     - recent episodes,
     - simple numeric counters.
   - Use it for operator-facing output and manual review.

2. **If useful, introduce persistent dashboards**
   - Add `MetaItem(kind='community_state')` and related types.
   - Store selected, human-reviewed summaries as long-lived objects, with full provenance + time windows.

3. **Wire into operator tools, not controller behavior**
   - Integrate dashboards into:
     - admin/owner commands,
     - monitoring views,
     - and planning docs.
   - Only later, if desired, allow **explicit, human-authored policies** to reference dashboard metrics.

---


## Conflict resolution (define it early; enforce it always)

A simple priority stack that prevents weird behavior across both memory and controller:

1. **User explicit corrections** > everything.
2. **Policies/invariants** (`MetaItem(kind="policy")`, priority critical/high) > narratives.
3. **Manual items** > auto-generated items (same type).
4. **Higher confidence** > lower confidence.
5. **More recent verification** > older verification.
6. **Scope match** > scope mismatch (don’t leak cross-project).
7. **Controller safety limits** > performance tweaks.

This priority stack is used by:

- retrieval,
- consolidation,
- meta-suggestions,
- controller learning (never accept a learned config that would violate higher-priority rules).



---

## 6. How Codex Should Help

When suggesting or generating code:

1. **Respect the architecture.**  
   - Use the canonical objects (`MemoryItem`, `SummaryItem`, `MetaItem`, `Link`, `ContextProfile`, `UserProfile`, `ControllerConfig`, `EpisodeLog`) where appropriate.
   - Don’t introduce ad-hoc JSON blobs when a schema already exists or should exist.

2. **Preserve auditability.**  
   - Make sure writes to memory or controller configs:
     - are logged,
     - contain enough metadata for rollback and debugging.

3. **Keep context boundaries clear.**  
   - When adding features that touch Discord channels/DMs:
     - always consider what `ContextProfile` should be applied,
     - check which capabilities are allowed in that context.

4. **Prefer small, composable services.**  
   - Retrieval, ingestion, lifecycle, controller, and evaluation should stay as separate modules with clean interfaces.
   - New features should be wired through these modules, not bypass them.

5. **Guardrails > cleverness.**  
   - If in doubt between a “smart” but opaque design vs a slightly more verbose one with explicit policies, pick the latter.
   - Make it easy to test, inspect, and override behavior.

---

## 7. Non-Goals (for now)

To keep Epoxy focused and safe, **Codex should NOT**:

- Add features that give Epoxy:
  - direct financial control,
  - unsupervised physical actuation,
  - arbitrary open-internet agents with broad tool access.
- Build generalized AGI frameworks unrelated to:
  - Lumeris,
  - human-development support,
  - the memory + controller system described here.

Epoxy is meant to be a **bounded, deeply integrated teammate** inside a specific human ecosystem, not a free-roaming global agent.

## 8. Current Implementation Status

Epoxy is roughly built up to M3. HOWEVER, the roadmap was just updated and made more robust, so consider that there may be missing pieces from the roadmap as well as chaotic/messy code.

When touching older, ad-hoc code paths, prefer migrating them toward this architecture rather than extending the old pattern.

Epoxy will also have some add-on modules - for example, she currently manages self-assignment of Discord roles, and soon we will automate announcements through her as well. Consider any modules unrelated to the core development path as separate functions, not core Epoxy code.

Epoxy is hosted on the Railway third-party service. She currently runs SQLite for database. We'll want to migrate to Postgres before serious implementation since Railway supports easy db exploration in Postgres.

Epoxy currently runs on one file: bot.py - we'll want to update it toward a code layout that looks roughly like:

### Code Layout (at a Glance)

- `/epoxy-bot/memory/` – MemoryItem, SummaryItem, MetaItem, Link models & services
- `/epoxy-bot/controller/` – ContextProfile, UserProfile, ControllerConfig, EpisodeLog, controller service
- `/epoxy-bot/ingestion/` – chat/tool ingestion pipelines
- `/epoxy-bot/retrieval/` – retrieval service implementations
- `/epoxy-bot/eval/` – evaluation harnesses (memory + controller)
- `/epoxy-bot/jobs/` – offline jobs (consolidation, drift reports, learning)
- `/epoxy-bot/misc/` - bolt-on modules such as Discord role management automation, automated announcement systems, etc that are unrelated (but plug into) core Epoxy architecture.

## 9. Schema & Migration Rules

- Treat `MemoryItem`, `SummaryItem`, `MetaItem`, `Link`, `ContextProfile`, `UserProfile`, `ControllerConfig`, and `EpisodeLog` as **canonical schemas**.
- Changes to these schemas MUST:
> - be backwards compatible when possible,
> - include a migration plan or script,
> - and avoid destructive edits to existing data.

Codex: do NOT silently drop fields or change meanings of existing fields.

## 10. Privacy & Logging

- Epoxy will store **potentially sensitive personal information** (DM content, arcs, contracts).
- Logs must:
> - avoid printing full message contents or raw PII where not necessary,
> - never log secrets or auth tokens,
> - respect context boundaries (don’t “debug log” member DMs into a global log sink).

Codex: If in doubt between logging everything and logging minimal structured IDs/refs, pick the minimal option.

## 11. Testing & Evals

When adding or changing:
- retrieval logic,
- memory lifecycle rules,
- controller behavior,

Codex should also:
- add or update tests under `/epoxy/eval/` or the relevant test directory,
- prefer deterministic or replayable cases (e.g. fixed EpisodeLogs),
- and avoid shipping behavior changes without at least one basic eval.

## 12. Patch Notes / Change Summaries

After any non-trivial refactor or feature change, you must:
1. Create a new file in `docs/changes/` named with the date and a short description.
2. Copy the structure from `docs/epoxy_change_summary_template.md`.
3. Fill in all sections, especially “Risks and sharp edges” and “Open questions for Brian/Seri”.

These summaries are for a higher-level architect review, so prioritize clarity and conceptual reasoning over code snippets.
