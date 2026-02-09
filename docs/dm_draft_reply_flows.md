# DM Draft Reply Flows (Operator Guide)

This doc gives explicit trigger phrases and expected Epoxy flow behavior for `@Epoxy dm: ...`.

## 1) Mode Selection Rules (Current Trial)
- Default behavior is collaboration-first.
- `mode=best_effort` is never auto-selected now.
- If `mode` is omitted (or `mode=auto`), Epoxy uses `collab`.
- If urgency cues are detected with partial/insufficient parse, Epoxy adds a confirmation line:
  - `If speed matters more than precision, reply mode=best_effort ...`

## 2) Explicit Mode Triggers You Can Use
- Force collab:
  - `mode=collab`
  - `mode: collab`
- Force best effort:
  - `mode=best_effort`
  - `mode: best_effort`
- Auto (still maps to collab in this trial):
  - `mode=auto`
  - `mode: auto`

## 3) Heuristic Cue Phrases (Still Logged, Not Auto-Applied)
Epoxy still computes `mode_inferred` for auditability.

- Cues that infer `best_effort`:
  - `just draft`
  - `do your best`
  - `no time`
  - `urgent`
  - `asap`
  - `I'm cooked` / `im cooked`
  - `brain fried`
  - high intensity punctuation (`!!!`) and high caps ratio

- Cues that infer `collab`:
  - `help me think`
  - `ask me`
  - `let's refine`
  - `work with me`
  - `co-create`
  - `iterate with me`

## 4) Parse Quality -> Flow
- `full`:
  - Draft generated.
  - Collab may include concise follow-ups depending on context.
- `partial`:
  - Collab flow with targeted follow-ups.
  - If inferred urgency is high and mode is not explicit, Epoxy includes a `mode=best_effort` confirmation option.
- `insufficient`:
  - Collab asks targeted questions and/or blocks when critical fields are missing.

## 5) Blocking Collab (Critical Missing)
Blocking is only in collab mode and only for critical-risk missing data:
- missing target
- missing objective
- missing non-negotiables when boundary/safety context is detected

When blocked:
- no draft is generated in that response
- response asks up to 2 focused clarifications
- block reason is logged

## 6) “Assumptions Used” Output
When assumptions are applied, output now includes an explicit section:
- `Assumptions Used:`
- bullet list of assumptions (for example `tone=steady`)

If you do not see this section:
- likely no assumptions were needed (full parse), or
- mode remained collab and no best-effort assumptions were applied.

## 7) Suggested Operator Patterns
- Low context, reflective:
  - `@Epoxy dm: objective=...; situation_context=...; mode=collab`
- Low context, speed required:
  - wait for Epoxy confirmation prompt, then reply:
  - `mode=best_effort`
- High-stakes boundary case:
  - always include `non_negotiables` explicitly.
