# MEMORY

This file is a running memory for big-picture and medium-picture context across sessions.

## How To Use
- Add short, durable notes that affect future design or operations.
- Prefer decisions, constraints, and patterns over implementation minutiae.
- Do not store secrets, tokens, or sensitive personal details.
- Keep entries dated and easy to scan.

## Current Snapshot
- Epoxy includes a bolt-on announcements module under `misc/adhoc_modules/`.
- Announcement templates live at `config/announcement_templates.yml`.
- Weekly cadence and prep settings are maintained in that template file.
- DM Draft Copilot is live as owner-only mention mode: `@Epoxy dm: ...`.
- DM Draft Copilot parse contract includes:
  - `target`
  - `objective`
  - `situation_context`
  - `my_goals[]`
  - `non_negotiables[]`
  - `tone`
  - optional `mode`
- DM draft observability is instrumented in episode logs (target identity, mode audit fields, blocking fields, guideline provenance, draft lineage, recall provenance counts).
- Identity has moved to person-core + masks:
  - canonical internal identity is `person_id` in `people`
  - external handles are in `person_identifiers`
  - `user_profiles` is keyed by `person_id`
  - episode logs include `person_id` and `target_person_id` (legacy `user_id` compatibility retained)

## Stable Decisions / Constraints
- Announcement prep is day-before; publish is day-of.
- `style_guidance` is optional per weekday and supports:
  - `notes`
  - `examples` (up to 1-2 are injected into prompt as style references only)
- Runtime env vars can override template prep settings:
  - `EPOXY_ANNOUNCE_TIMEZONE`
  - `EPOXY_ANNOUNCE_PREP_TIME_LOCAL`
  - `EPOXY_ANNOUNCE_PREP_CHANNEL_ID`
- DM Draft Copilot is collaboration-only:
  - `mode=best_effort` is disabled
  - `mode=auto` resolves to `collab`
  - if parse is `partial` or `insufficient`, drafting is blocked and Epoxy asks concise clarifying questions
- Required context to draft in DM mode:
  - `objective`
  - `situation_context`
  - `my_goals`
  - `non_negotiables`
  - `tone`
- Identity resolution is deterministic only in M3.1:
  - no inference-based linking
  - active identifier means `revoked_at IS NULL`
  - person-first writes are required; legacy `user_id` remains compatibility write-through during transition

## Operational Notes
- Manage `EPOXY_ANNOUNCE_TEMPLATES_PATH` explicitly in deployment.
- Recommended Railway path: `/app/config/announcement_templates.yml`.
- Basename-only paths (for example `announcement_templates.yml`) now have fallback resolution, but explicit env config is preferred.
- DM draft guidelines path is configurable via `EPOXY_DM_GUIDELINES_PATH` (default `config/dm_guidelines.yml`).
- If runtime errors mention missing columns after deploy, run DB migrations through latest (`0015_profile_tag_person_bridge.py`) before retrying DM flows.

## Active Workstreams
- Continue hardening announcement operator ergonomics (`!announce.*` flows).
- Keep announcement docs and command behavior aligned.
- Continue person-first cutover:
  - reduce legacy `user_id` dependencies
  - keep backward compatibility stable during transition
- Continue DM draft quality hardening in collab flow:
  - clarify prompts
  - maintain strict context-before-draft behavior

## Open Questions
- Should template path be strict in production (fail fast) instead of permissive fallback?
- Should manual prep allow safe re-trigger from `prep_pinged`?
- When should legacy `subject:user:*` compatibility tags stop being written on new profile memories?
- When should `person_facts` move from stub to full schema + pipeline?

## Memory Log
- 2026-02-13: Added this memory file for cross-session continuity.
- 2026-02-13: Shipped DM Draft Copilot v1.1 instrumentation and logging schema additions (`0006`-`0011`), including mode/blocking/target/guideline/lineage/recall provenance fields.
- 2026-02-13: Shipped M3.1 person identity refactor (`0012`-`0015`) with canonical `person_id`, `person_identifiers`, person-keyed profiles, episode person columns, and profile tag bridge.
- 2026-02-13: Updated DM draft behavior to collaboration-only (best-effort disabled), with parse-gated clarifications before drafting when required context is missing.
