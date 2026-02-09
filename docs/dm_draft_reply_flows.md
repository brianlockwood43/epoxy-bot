# DM Draft Reply Flows (Operator Guide)

This document defines current DM draft behavior for `@Epoxy dm: ...`.

## 1) Mode Policy (Current)
- DM drafting is collaboration-only.
- Effective mode is always `collab`.
- `mode=best_effort` is disabled.
- `mode=auto` and omitted `mode` both resolve to `collab`.

## 2) Supported Mode Inputs
- Supported:
  - `mode=collab`
  - `mode: collab`
  - `mode=auto`
  - `mode: auto`
- Not supported:
  - `mode=best_effort`
  - `mode: best_effort`

If `best_effort` is requested, Epoxy stays in collab and asks for missing context.

## 3) Parse Quality -> Reply Flow
- `full`:
  - Draft is generated.
  - Follow-up questions may still be included if useful.
- `partial`:
  - No draft.
  - Epoxy asks concise targeted clarification questions.
- `insufficient`:
  - No draft.
  - Epoxy asks concise targeted clarification questions.

## 4) Blocking Contract
Epoxy blocks draft generation whenever required context fields are missing.

Required context fields:
- `objective`
- `situation_context`
- `my_goals`
- `non_negotiables`
- `tone`

Additional critical-risk blocking still applies in collab mode:
- missing `target`
- missing `objective`
- missing `non_negotiables` in boundary/safety contexts

## 5) Trigger Phrases (Operational)
These phrases can still shape tone and question style, but do not switch mode.

- reflective/collaborative cues:
  - `help me think`
  - `ask me`
  - `let's refine`
  - `work with me`
- urgency cues:
  - `urgent`
  - `asap`
  - `I'm cooked`
  - `no time`

Urgency does not bypass context requirements.

## 6) Assumptions Used
- Automatic best-guess assumptions are disabled with best-effort removal.
- `Assumptions Used` is expected to be empty unless assumptions are explicitly introduced by future policy changes.

## 7) Suggested Operator Patterns
- Minimal complete request:
  - `@Epoxy dm: objective=...; situation_context=...; my_goals=...; non_negotiables=...; tone=...`
- Add target when person-specific context matters:
  - `target=<@...>` or `target=member:name`
- For high-risk boundary conversations:
  - include explicit `non_negotiables` and concrete `situation_context`.
