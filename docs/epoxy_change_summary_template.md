# Epoxy Change Summary Template

> This file is a template. When you (Codex) finish a significant change or refactor,
> create a new summary file by copying this structure and filling it out.
> This file should be made in /docs/changes and named something like 2026-02-09-epoxy-refactor.md or if there's a same day follow up update, something like 2026-02-09-epoxy-refactor-update2.md
> Do NOT change this template file unless it's explicitly requested.

## What changed (concrete)
- [ ] High-level bullet list of key changes.
- [ ] Public-facing behavior changes: commands/routes, parse contract fields, output schema.
- [ ] Name important new modules/types/functions.
- [ ] Note any removed or deprecated pieces.

## Why it changed (rationale)
- What design problems were we solving?
- What tradeoffs did we accept (pros/cons)?

## Config / operational knobs
- [ ] New env vars, defaults, and safe values.
- [ ] Feature gates / allowlists / owner-only behavior.
- [ ] Fallback behavior when config is missing.

## Data model / schema touchpoints
- [ ] Any new fields written to episode logs / artifacts (include stable key paths).
- [ ] New enums / identifiers (e.g., mode, target_type).
- [ ] Migrations: none / list them.

## Observability / telemetry
- [ ] What gets logged now (episode.kind, artifact keys).
- [ ] Any new derived metadata (recall coverage, provenance counts).
- [ ] Where to look to verify quickly.

## Behavioral assumptions
- What behaviors are intended to remain identical?
- What behaviors might change subtly (edge cases)?

## Risks and sharp edges
- Where is this most likely to break?
- Any circular dependencies, hidden coupling, or weirdness?
- Any “unsafe” failure modes (e.g., drafting when it should block, mis-targeting, overconfident recall).

## How to test (smoke + edge cases)
- [ ] 3–5 copy/paste test prompts or commands.
- [ ] Expected outputs (one line each).
- [ ] Any special local/dev setup notes.

## Evaluation hooks
- [ ] Feedback commands / rating mapping.
- [ ] Rubric or failure-tag capture (if applicable).
- [ ] Where eval data is stored.

## Debt / follow-ups
- Things that feel “good enough for now but not ideal”.
- Any TODOs Codex sees but did not implement.

## Open questions for Brian/Seri
- Conceptual questions about architecture, naming, boundaries.
- Unclear ownership decisions or future “shape of the system” questions.
