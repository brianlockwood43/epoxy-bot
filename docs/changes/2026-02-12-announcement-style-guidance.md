# Epoxy Change Summary

## What changed (concrete)
- Added optional `style_guidance` parsing for announcement day templates in `misc/adhoc_modules/announcements_service.py`.
- Extended `AnnouncementTemplateDay` with `style_notes` and `style_examples` so style references are available at draft-generation time.
- Updated draft prompt construction to include style guidance only when configured:
- Includes `style_guidance.notes`.
- Includes up to the first 2 `style_guidance.examples[].text` entries.
- Added explicit anti-copy instruction in the system prompt so examples are treated as references only.
- Added tests in `tests/test_announcements.py` for:
- Style guidance present: prompt includes notes + first 2 examples and omits the 3rd.
- Style guidance absent: no style guidance block in prompt.
- Added commented example block to `config/announcement_templates.yml` showing the new optional schema.

## Why it changed (rationale)
- Announcement quality can vary by surface/context, and weekday tone/structure alone is sometimes not enough.
- `style_guidance` provides controlled style steering without changing core workflow or making it mandatory.
- Tradeoff: prompt context gets longer when style guidance is used; cap at 2 examples keeps token growth bounded.

## Config / operational knobs
- New optional template key under `days.<weekday>`:
- `style_guidance.notes: str`
- `style_guidance.examples: [{id, summary, text}]`
- No new env vars.
- Fallback behavior: if `style_guidance` is missing or empty, generation behavior remains unchanged.

## Data model / schema touchpoints
- No DB schema changes.
- No migration required.
- In-memory template/day object now carries:
- `AnnouncementTemplateDay.style_notes`
- `AnnouncementTemplateDay.style_examples`

## Observability / telemetry
- No new logging sinks.
- Existing `draft_generated` audit payload remains unchanged (`missing_required`, `answers`).
- Quick verification path: inspect captured LLM prompt in `tests/test_announcements.py`.

## Behavioral assumptions
- Existing announcement lifecycle (prep, answers, generation, approval, posting) remains identical.
- Style references only affect LLM draft prompt content.
- Missing required question handling (`TODO(question_id)`) remains unchanged.

## Risks and sharp edges
- Large example texts can still expand prompt size; current cap is only by count (2), not strict text length.
- If users place policy-sensitive phrasing in style examples, the model may mirror style direction (without direct copying), so operator review still matters.
- Duplicate or low-quality examples can reduce style signal quality.

## How to test (smoke + edge cases)
- `python -m unittest tests.test_announcements.AnnouncementServiceTests.test_generate_includes_style_guidance_in_prompt_when_present`
- Expected: prompt contains style notes and first two example texts, excludes third.
- `python -m unittest tests.test_announcements.AnnouncementServiceTests.test_generate_omits_style_guidance_when_not_configured`
- Expected: prompt has no `Style guidance:` section.
- `python -m unittest tests.test_announcements`
- Expected: full announcements test file passes (with existing discord auth test skipped if discord.py is unavailable).

## Evaluation hooks
- No eval-schema changes.
- No new feedback command mappings.
- Announcement quality still reviewed through existing draft/approve workflow and manual checks.

## Debt / follow-ups
- Consider adding character caps/truncation per style example before prompt injection.
- Consider optional randomization/selection strategy among >2 examples to avoid always using first entries.
- Consider storing selected style example IDs in audit payload for traceability.

## Open questions for Brian/Seri
- Should style examples be scoped per channel/surface in addition to weekday?
- Do we want a hard policy gate that strips references to specific names/PII from `style_guidance.examples.text` before prompt use?
- Should we log which style example IDs were used for each generated draft for easier retrospective tuning?
