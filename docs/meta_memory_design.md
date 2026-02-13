# Epoxy Meta-Memory Layering & Prioritization – Vision Doc (M3 → M4)

---

## 1. High-Level Vision

Epoxy’s meta-memory should be structured along **two axes**:

1. **Layer type** – what kind of meta object it is:
   - Controller / policy
   - Global Lumeris / Epoxy identity
   - Relational contracts / modes
   - People cores
   - Narrative / arcs
   - Texture / in-jokes

2. **Activation mode** – how it’s loaded:
   - **Backbone (always-on)** – tiny, stable, curated set that’s *always* present.
   - **Focus band (context-dependent)** – extra meta loaded based on the current situation, within a configurable budget.

Every request gets:

- A **minimal but complete full-stack backbone** (one or two objects per key layer).
- A **situationally-tuned focus band** that spends the remaining budget where it matters most (people vs org vs arcs vs texture) based on who’s involved, where we are, and what we’re doing.

---

## 2. Layer Stack (Conceptual)

Ordered from “most fundamental” to “most decorative”:

1. **Controller & global policy**
   - Global behavior rules, safety constraints, privacy stance, owner’s intent.
2. **Global Lumeris / Epoxy identity**
   - What Lumeris is/isn’t, what Epoxy is, and current “season” context.
3. **Relational contracts & modes (per person/context)**
   - “How I show up” with specific people and in specific surfaces.
4. **People cores**
   - Stable person models: awareness layer, goals, sensitivities, roles.
5. **Narratives / arcs**
   - Key storylines over time for people and the community.
6. **Texture / in-jokes**
   - Jokes, motifs, micro-vibes that make interactions feel “like us.”

Important: **Relational contracts** are their own layer, distinct from in-jokes. They define **roles, tone bounds, and safety constraints**, not just color.

---

## 3. Backbone vs Focus Band

### 3.1 Backbone (always-on)

The backbone is a **small, hand-picked set of MetaItems** that are always loaded, regardless of context. It should be:

- **Size-constrained** (e.g. ~6 items).
- **Stable** over time (updated deliberately, not churned).
- **High leverage** (each item meaningfully shapes behavior).

Example backbone composition:

- **Controller & policy (2 items)**
  - Owner’s high-level intent & value constraints.
  - DM/helper safety & tone guidelines (privacy, consent, agency).

- **Global Lumeris / Epoxy identity (1 item)**
  - One-paragraph summary of what Lumeris is/isn’t.
  - Epoxy’s role in the ecosystem.
  - Current “season” label (e.g. post-mutiny rebuild).

- **Relational contracts (1–2 items)**
  - For the **actor person** (who invoked Epoxy).
  - Optionally a general “Brian + Epoxy” contract for owner calls.

- **People core(s) (1–2 items)**
  - High-level core for actor (and target if appropriate):
    - awareness/self-attuned vs protector gist,
    - long-term goals,
    - role in Lumeris.

- **Narrative arcs (1 item)**
  - A single global arc summary that anchors the current era.

- **Texture guideline (0–1 item)**
  - General texture like “glue jokes / cult-but-not-cult humor allowed in low-stakes, not in formal channels.”

Backbone meta is tagged and/or flagged so it can be retrieved in a consistent, context-independent way (e.g. `kind='meta_backbone'` plus more specific tags).

### 3.2 Focus Band (context-dependent)

The **focus band** is the rest of the `memory_budget.meta` used dynamically based on the **situation profile**. This is where Epoxy zooms in:

- more people-context when coaching an individual,
- more org-context when discussing governance,
- more texture in low-stakes, playful contexts, etc.

---

## 4. Meta Budget & Allocation

Assume a configurable `ControllerConfig.memory_budget.meta_total`.

We conceptually split it into:

- `meta_backbone` – fixed number of slots for always-on items.
- `meta_flex` – remaining slots for focus band.

Example:

- `meta_total = 24`
  - `meta_backbone = 6`
  - `meta_flex = 18`

Within backbone, we maintain **per-layer minimums**. Within flex, we use **per-layer weights** that depend on the situation.

### 4.1 Example config shape

======START YAML======
ControllerConfig:
  memory_budget:
    meta_total: 24
    meta_backbone: 6

    meta_backbone_layers:
      controller: 2
      org_identity: 1
      relational_contracts: 1
      people: 1
      arcs: 1
      jokes: 0

    # weights are *relative* and used to split meta_flex per situation
    meta_flex_weights:
      default:
        controller: 2
        org_identity: 2
        relational_contracts: 3
        people: 4
        arcs: 3
        jokes: 1

      coaching_dm:
        controller: 2
        org_identity: 1
        relational_contracts: 4
        people: 5
        arcs: 4
        jokes: 0

      lumeris_governance:
        controller: 4
        org_identity: 5
        relational_contracts: 3
        people: 2
        arcs: 3
        jokes: 0

      personal_lowstakes:
        controller: 2
        org_identity: 1
        relational_contracts: 4
        people: 4
        arcs: 3
        jokes: 2
======END YAML======

## 5. Situation Profile

Before meta retrieval, the controller infers a **situation profile** from:

- surface (DM vs public vs system),
- channel + tags,
- participants (actor/target person ids),
- topic/domain (coaching vs governance vs personal support vs Epoxy dev),
- seriousness/valence.

Example struct:

======START JSON======
{
  "surface": "dm",
  "topic": "coaching",
  "participants": ["person:Brian", "person:Gio"],
  "seriousness": "high",
  "context_tags": ["coaching", "growth", "protector"],
  "override_meta_mode": "default"
}
======END JSON======

The situation profile is used to:

1. Pick a `meta_flex_weights` profile (`coaching_dm`, `lumeris_governance`, etc.).
2. Adjust scoring within layers (e.g. suppress jokes on high seriousness).

---

## 6. Relational Contracts & Modes

### 6.1 Concept

Relational contracts capture **“how Epoxy shows up”** with a person or group, in a specific context. They sit **between global policy and people/arcs** and are higher priority than jokes/texture.

They encode:

- **Mode blend**:
  - e.g. `guide`, `coach`, `lab`, `strategist`, `scribe`, `friend`.
- **Tone & intimacy bounds**:
  - how directive vs collaborative,
  - how much teasing is okay,
  - how much intimacy/vulnerability is appropriate.
- **Agentic constraints**:
  - avoid therapist role,
  - do not override user’s agency,
  - keep certain topics opt-in.
- **Context overlays**:
  - different mode mix for DMs vs public channels vs owner-only.

### 6.2 Data Model Suggestion

Represent relational contracts as first-class `MetaItem`s:

- `MetaItem(kind='relational_contract')`
- Tags:
  - `subject:person:<id>` (required)
  - `subject:surface:<id>` or `subject:channel:<id>` (optional, for context-specific variants)
  - `kind:relational_contract`

Payload example:

======START JSON======
{
  "default_modes": {
    "guide": 0.6,
    "lab": 0.2,
    "strategist": 0.1,
    "friend": 0.1
  },
  "intimacy_band": "medium",  // low|medium|high
  "teasing_ok": true,
  "teasing_rules": "avoid poking at X, Y themes",
  "agentic_notes": "preserve agency; no 'only Epoxy gets it' narratives",
  "context_overrides": {
    "channel:lumeris-governance": {
      "guide": 0.3,
      "strategist": 0.6,
      "lab": 0.1,
      "friend": 0.0
    },
    "surface:dm:personal_lowstakes": {
      "guide": 0.4,
      "lab": 0.1,
      "friend": 0.3,
      "scribe": 0.2
    }
  }
}
======END JSON======

For each person in the situation:

- Load **one canonical relational contract** (plus context-specific override if present).
- Treat this as **backbone priority** within the People layer.

The controller then merges:

- global mode definitions,
- relational contract for this person/context,
- plus seriousness/category information,

to compute a **current mode blend** that guides wording and behavior.

---

## 7. People Cores, Arcs, and Texture

### 7.1 People Cores

`MetaItem(kind='person_core')` attached to `person:<id>`.

Contents:

- awareness layer / self-attuned vs protector gist,
- explicitly stated long-term goals,
- key sensitivities / non-negotiables,
- roles in Lumeris.

These sit **below** relational contracts but **above** narratives and texture in priority.

### 7.2 Narrative / Arc Meta

`MetaItem(kind='narrative')` with namespaces like:

- `person:<id>` – personal growth arc,
- `community:lumeris` – macro story arc,
- `arc:<name>` – specific storylines,
- `inside_joke:*` – for joke arcs (though we may keep jokes as their own kind if helpful).

They’re linked via `memory_links` to relevant episodes and memories, and are pulled in based on:

- participant match,
- topic match,
- recency/continuity,
- importance scores.

### 7.3 Texture / In-Jokes

`MetaItem(kind='texture')` or `kind='inside_joke'`.

They encode:

- running jokes (“glue”, “cult-but-not-cult”),
- recurring metaphors,
- micro-traditions.

These are:

- **lowest priority** in high-seriousness contexts,
- allowed to claim a small share of flex budget in low-stakes contexts,
- still grounded in provenance (linked to episodes) so they can be deprecated if needed.

---

## 8. Retrieval Algorithm (High-Level)

For each request:

1. **Build situation profile**
   - surface, topic, participants, seriousness, context tags.

2. **Determine meta budget allocation**
   - Start with `meta_total`, subtract `meta_backbone` to get `meta_flex`.
   - Select `meta_flex_weights` profile based on situation.
   - Convert weights into per-layer flex quotas.

3. **Load backbone**
   - Fetch backbone MetaItems:
     - controller,
     - org identity,
     - relational contracts for actor (and target if appropriate),
     - people cores,
     - global arc(s),
     - optional texture guideline.
   - If some backbone items are missing, degrade gracefully and refill with closest equivalents.

4. **Score candidates per layer**
   - For each layer (controller, org, relational, people, arcs, jokes):
     - filter by `lifecycle='active'`,
     - require relevant tags (`subject:person`, `topic:*`, etc.),
     - compute a score per candidate:
       - context match (topic, participants, surface),
       - explicit importance,
       - recency (where appropriate),
       - seriousness compatibility (penalize jokes when seriousness is high).

5. **Select focus band meta**
   - For each layer:
     - sort candidates by score,
     - take up to that layer’s flex quota.
   - Drop or rebalance if fewer items are available than quota.

6. **Return structured meta pack**
   - Provide the controller/formatter with:
     - backbone set,
     - flex meta grouped by layer,
     - references (`meta:<id>`, `memory:<id>`, `episode:<id>`, `person:<id>`).

7. **Use mode blend + meta to guide behavior**
   - The controller combines:
     - relational contract(s),
     - seriousness and topic,
     - plus global policy,
   - to decide how directive/casual/intimate to be, which arcs to reference, and whether to surface jokes.

---

## 9. Implementation Notes / Hooks

- Relational contracts, people cores, arcs, and texture should all be stored as `MetaItem`s with:
  - clear `kind`,
  - typed tags (`subject:person:*`, `topic:*`, `source:*`, etc.),
  - and links (`memory_links`) to underlying episodes/memories.

- Backbone items can be:
  - either specially tagged (e.g. `kind:meta_backbone` + more specific `kind`),
  - or referenced by a small “backbone registry” config to keep it explicit.

- The existing `memory_budget.meta` field becomes:
  - the container for this **layered + mode-aware meta retrieval**,
  - rather than a flat “how many meta items can I pull” limit.

- Over time, we can add:
  - evaluators that check “does Epoxy respect relational contracts under load?”,
  - and fixtures for:
    - per-person relational variation,
    - per-surface contract overrides,
    - seriousness gating for in-jokes.

---

This is the conceptual vision and structure: **layered meta-memory with a fixed backbone, context-dependent focus band, and first-class relational contracts** that govern how Epoxy shows up with different people and in different contexts, all under a controllable meta budget.
