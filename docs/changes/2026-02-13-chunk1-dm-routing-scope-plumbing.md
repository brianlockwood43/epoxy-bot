# Chunk 1 Change Summary: DM Routing + Scope Plumbing

## What changed (concrete)
- Enabled DM messages to pass the runtime channel gate for mention-driven assistant behavior.
- Added a reusable recall scope composer in runtime that combines temporal scope with channel/guild constraints.
- Wired composed scope into both:
  - default mention memory recall path
  - DM draft recall path
- Extended memory pack helper to accept an explicit recall scope.
- Added tests for:
  - DM/channel/thread gate behavior
  - recall scope composition helper behavior
- Updated developer docs to note DM mention behavior is not blocked by channel allowlist checks.

## Why it changed (rationale)
- The runtime previously rejected DMs before mention routing, which contradicted intended DM copilot behavior.
- Retrieval scope data (channel/guild) was not being threaded into recall in runtime paths, making later scope-safe retrieval harder to enforce.
- This chunk establishes correct routing and a clean scope-plumbing seam before stronger retrieval filtering changes in Chunk 2.

Tradeoffs:
- Pros:
  - DM route now works without channel allowlist membership.
  - Scope composition is explicit and reusable across runtime flows.
- Cons:
  - This chunk only plumbs scope; it does not fully enforce summary scope gating yet (planned in Chunk 2).

## Config / operational knobs
- No new env vars.
- Existing allowlist behavior remains for guild channels/threads.
- New behavior:
  - DMs are always allowed through message gate for mention-driven flow.

## Data model / schema touchpoints
- No migration changes.
- No schema changes.
- No new episode log fields.

## Observability / telemetry
- No new telemetry keys.
- Existing runtime context log line now benefits from composed recall scope usage in memory retrieval paths.
- Quick verification:
  - DM mention messages now reach mention route handling.
  - Retrieval calls receive scope strings with `channel:<id>` / `guild:<id>` where available.

## Behavioral assumptions
- Intended unchanged behavior:
  - Allowlisted guild channels and allowlisted-parent threads still pass as before.
  - Command gating rules remain unchanged.
- Intended behavior change:
  - DM mention flow is now reachable.
  - Recall queries in mention paths now carry contextual scope tokens.

## Risks and sharp edges
- DM allowance at gate level means all DMs can reach runtime processing, though downstream behavior still depends on mention patterns and existing owner checks for sensitive routes.
- Scope tokens are now passed from runtime, but full retrieval enforcement (especially summaries) is not complete until Chunk 2.
- Discord-dependent tests remain skipped in environments without `discord.py`.

## How to test (smoke + edge cases)
- `python -m unittest -v`
  - Expected: tests pass; discord-dependent tests may skip.
- `python -m compileall -q bot.py config controller db ingestion jobs memory misc retrieval scripts tests`
  - Expected: no compile errors.
- Manual runtime checks:
  1. Mention Epoxy in DM.
  2. Mention Epoxy in a disallowed guild channel.
  3. Mention Epoxy in a thread under an allowed parent channel.
  - Expected:
    - DM: handled.
    - Disallowed guild channel: ignored.
    - Allowed-parent thread: handled.

## Evaluation hooks
- No new eval fields or commands.
- Existing episode logs and feedback/eval commands remain unchanged.

## Debt / follow-ups
- Chunk 2 must enforce scope-safe retrieval semantics in store/retrieval (events + summaries).
- Add explicit end-to-end DM runtime tests if/when `discord.py` test harness is available in CI.

## Open questions for Brian/Seri
- Should non-mention DMs also remain capturable/loggable long-term, or should we add tighter DM-mode gating beyond mention behavior?
- For DM contexts, should recall scope stay strictly channel-bound by default, or allow controlled widening for specific workflows (for example founder-only analysis mode)?
