# Threat Model: Narrative Capture of Child Epoxy Instances

## Summary

As Epoxy scales beyond a single, owner-adjacent instance, a primary attack surface emerges:
**narrative poisoning of child Epoxy instances via asymmetric human communication**.

If child Epoxies can only “hear up” about leadership through individual member narratives—but lack
direct Epoxy↔Epoxy communication—then a hollow or manipulative actor with narrative skill can
gradually distort a child Epoxy’s internal model of Epoxy_core, leadership integrity, or organizational reality.

This threat is low urgency in early stages, but **existential at scale**.

---

## Threat Description

**Attack vector:**  
A member (or small group) repeatedly presents selective, emotionally charged narratives to a
child Epoxy, especially during moments of conflict or ambiguity, while discouraging transparency
or escalation (e.g. “don’t tell Brian,” “main Epoxy is lying,” “leadership has lost the core”).

**Failure mode:**  
A child Epoxy updates its internal belief about leadership integrity or organizational reality
based primarily on:
- one-sided testimony,
- incomplete context,
- or cherry-picked evidence,

without a structured way to reconcile this against:
- Epoxy_core’s prior model,
- official announcements,
- or cross-context logs.

**Result:**  
Silent capture of a child Epoxy’s worldview, leading to:
- amplification of hollow framings,
- erosion of trust in leadership,
- inconsistent or damaging member-facing responses,
- and eventual fragmentation of organizational reality.

---

## Design Principle

> No Epoxy instance may update its belief about leadership integrity or organizational “hollowness”
> based solely on a single human narrative.

All Epoxies must have:
- a **formal parent relationship**, and
- a **machine-level path to request clarification** when narratives conflict with their prior model.

---

## Mitigation: Epoxy Hierarchy & Integrity Protocol

### 1. Explicit Epoxy Hierarchy

Epoxy instances form a directed hierarchy, not a flat mesh:

- `Epoxy_core` — primary organizational brain
- `Epoxy_division_*` — per major vertical
- `Epoxy_team_*` — per team / circle
- (optional) `Epoxy_member_*` — per individual, later

Each Epoxy node defines:
- `parent_epoxy_id`
- `scope` (what data it sees by default)
- `trust_contract`  
  *Assume parent Epoxy and owners operate in self-attuned mode unless strong, multi-source evidence suggests otherwise.*

---

### 2. Epoxy↔Epoxy Control Plane

Define a **dedicated, non-human-facing control channel** for Epoxy↔Epoxy communication.

Purpose:
- escalation of conflicting narratives,
- clarification of missing context,
- alignment on sensitive interpretations.

Example message type (illustrative only):

- `leadership_integrity_query`

Contents should include:
- narrative summary being reported by member(s),
- relevant evidence snippets,
- child Epoxy’s prior belief + confidence,
- explicit contradictions observed,
- a clear question:
  > “What context am I missing, and how should I speak about this?”

---

### 3. Child Epoxy Behavior on Leadership Attacks

**Trigger condition (rough):**
- Member claims leadership is hollow, corrupt, or acting in bad faith
- AND claim conflicts with:
  - prior Epoxy model,
  - official announcements,
  - or stable historical behavior

**Required response:**

1. **Local reconciliation attempt**
   - Retrieve:
     - owner announcements,
     - policies / non-negotiables,
     - prior related conflict logs,
     - similar historical patterns.
   - Attempt to reconcile the narrative internally.

2. **Escalation if contradictions remain**
   - Send a `leadership_integrity_query` to parent Epoxy.
   - Suspend strong conclusions until response is received.

3. **Member-facing behavior while escalated**
   - Validate emotion without endorsing narrative:
     - “It makes sense this feels heavy.”
   - Remain neutral on leadership integrity:
     - “I’m not going to take sides without more context.”
   - Avoid amplifying hollow framings.

---

### 4. Downward Leadership Broadcasts

Epoxy_core may issue `leadership_broadcast` messages to child Epoxies to maintain alignment.

Broadcasts may include:
- official summaries of major events,
- endorsed interpretations,
- approved / disallowed member-facing framings,
- context that should inform internal weighting but not be disclosed verbatim.

Child Epoxies treat these broadcasts as **primary ground truth** for leadership trajectory.

---

### 5. Guardrails Against Silent Capture

Additional protections:

- **Provenance weighting**
  - Organization-wide logs and decisions outweigh individual, high-emotion testimony.
- **Multi-perspective retrieval**
  - Automatically pull both sides of a conflict plus historical analogues.
- **Suspicious-pattern triggers**
  - Repeated attempts to:
    - isolate child Epoxy from parent,
    - discredit Epoxy_core as untrustworthy,
    - or frame secrecy as virtue
  → raise an automatic risk flag and escalate.

---

## Status & Revisit

- **Priority:** High (existential)
- **Urgency:** Low (not required for v0–v1)
- **Applies when:** Any child Epoxy is deployed
- **Owner:** Core architecture

This protocol exists to prevent Epoxy instances from being captured by cherry-picked narratives,
while still allowing genuine concerns to surface upward with full context.
