# Epoxy Change Summary

## What changed (concrete)
- Added deterministic Discord timestamp helper module at `misc/discord_timestamps.py` as the single formatting source for `<t:...>` tags.
- Added helper APIs and types:
  - `format_discord_timestamp(...)`
  - `next_weekday_time(...)`
  - `next_weekday_timestamp_tag(...)`
  - `fixed_date_time_timestamp_tag(...)`
  - `RecurringTimestampSpec`
  - `TimestampRenderResult`
  - named placeholder + raw-tag patterns and renderer.
- Added announcement placeholder rendering integration in `misc/adhoc_modules/announcements_service.py`:
  - parses/normalizes `timestamp_placeholders` config.
  - renders placeholders for draft preview output.
  - stores raw draft text (with placeholders) in DB.
  - renders placeholders before posting.
  - enforces configurable unresolved/raw-tag policy at publish time.
  - writes render metrics into audit payloads.
- Updated announcement draft prompt rules to require placeholders:
  - never output `<t:...>` directly.
  - never compute Unix timestamps.
  - use `{{DISCORD_TS:event_name}}`.
  - include allowed event names from config in prompt context.
- Extended `config/announcement_templates.yml` with `timestamp_placeholders` config and weekly schedule event mappings.
- Updated weekday guidance so Epoxy is explicitly told which placeholder(s) to use for each day.
- Reworked Monday announcement template to a structured format:
  - Hook
  - What we're doing
  - Who it's for
  - When & where
  - What to prep
- Replaced Monday question set with structured inputs:
  - `pillar`, `car`, `track`, `focuses`, `focus_rationale`, `prep`, optional `all_levels_reassurance`.
- Removed `time_and_place` from Monday questions so times come from placeholder config/guidance.
- Added weekly training pillar reference text to Monday style guidance.
- Added tests:
  - new unit suite `tests/test_discord_timestamps.py`.
  - announcement integration coverage additions in `tests/test_announcements.py`.

## Why it changed (rationale)
- Timestamp generation through the model is fragile and non-deterministic.
- Placeholder rendering in backend code gives deterministic, testable timestamp output.
- Named placeholders reduce prompt complexity and are easier for operators to manage.
- Weekday-specific guidance improves consistency and reduces ambiguity in announcement drafts.
- Monday now has a stricter, reusable drafting structure aligned with operator preferences.

## Config / operational knobs
- New template config block:
  - `timestamp_placeholders.default_style` (default `f`)
  - `timestamp_placeholders.unresolved_policy` (`passthrough` or `block`, default `passthrough`)
  - `timestamp_placeholders.raw_tag_policy` (`allow` or `block`, default `allow`)
  - `timestamp_placeholders.events.<event_name>`
- Current mapped schedule placeholders include:
  - Monday: `monday_workshop_early`, `monday_workshop_evening`
  - Tuesday: `tuesday_study_hall_early`, `tuesday_study_hall_evening`
  - Wednesday: `wednesday_adaptability_early`, `wednesday_adaptability_evening`
  - Thursday: `thursday_mastery_training`
  - Friday: `friday_funday_start`
  - Saturday: `saturday_racecraft_training`
  - Sunday: `sunday_race_together`

## Data model / schema touchpoints
- No DB schema changes.
- No migration required.
- Existing announcement cycle fields are reused:
  - `draft_text` remains source text.
  - `final_text` stores rendered post content after successful publish.

## Observability / telemetry
- Added timestamp render metadata to announcement audit payloads, including:
  - resolved count
  - unresolved placeholder names
  - raw tag count
  - active unresolved/raw policies
  - render/block reason (when applicable)
- Added explicit audit path for render-policy block/failure before publish.

## Behavioral assumptions
- Scope is announcement module only (not global Discord send interception).
- Placeholder syntax is named-only:
  - `{{DISCORD_TS:event_name}}`
- Preview (`!announce.generate`) returns rendered placeholder output.
- Publish always re-renders at send time and applies policy enforcement.
- Default rollout remains permissive:
  - unresolved placeholders pass through
  - raw `<t:...>` tags allowed

## Risks and sharp edges
- If operators leave unresolved placeholders while policy is `passthrough`, unresolved tokens can appear in posted output.
- Invalid placeholder event definitions are ignored during template normalization.
- Existing style examples may still contain legacy phrasing and should be kept aligned manually.

## How to test (smoke + edge cases)
- `python -m unittest -v tests.test_discord_timestamps tests.test_announcements`
- Key expected coverage:
  - same-day future and past-week rollover logic for recurring times
  - DST wall-clock stability
  - fixed-date helper correctness
  - placeholder replacement + unresolved/raw policy behavior
  - announcement preview rendering and post-time rendering/persistence

## Evaluation hooks
- No eval schema changes.
- No controller/memory eval harness changes.
- Announcement quality and policy behavior remain operator-reviewed through existing `!announce.*` workflow and audit logs.

## Debt / follow-ups
- Consider flipping defaults to stricter publish policy after operational soak:
  - `unresolved_policy=block`
  - optionally `raw_tag_policy=block`
- Consider de-duplicating or tightening long style examples in template for cleaner prompt signal.
- Consider adding command support for validating placeholder coverage before approval.

## Open questions for Brian/Seri
- Should unresolved placeholders be blocked by default in production now that schedule mappings are in place?
- Do we want a lint/check command that validates required placeholder presence per weekday before `approve`?
