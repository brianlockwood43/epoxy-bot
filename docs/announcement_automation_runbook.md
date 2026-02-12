# Announcement Automation Runbook (v1.1)

This runbook covers first-time setup and safe rollout for the `!announce.*` module.

## 1) Configure Environment

Start from `.env.example` and set:

- `DISCORD_TOKEN`
- `OPENAI_API_KEY`
- `EPOXY_OWNER_USER_IDS`
- `EPOXY_ANNOUNCE_PREP_CHANNEL_ID`
- `EPOXY_ANNOUNCE_PREP_ROLE_NAME` (optional)
- `EPOXY_ANNOUNCE_TIMEZONE`

Recommended initial rollout:

- `EPOXY_ANNOUNCE_ENABLED=0`
- `EPOXY_ANNOUNCE_DRY_RUN=1`

## 2) Configure Daily Templates

Edit `config/announcement_templates.yml`:

- Set `prep_channel_id`
- For each day to use:
  - `enabled: true`
  - `target_channel_id`
  - `publish_time_local`
  - `style_guidance` (optional style references)
  - question list (`id`, `prompt`, `required`)

Notes:

- If `enabled: true` but `target_channel_id: 0`, no cycle is created.
- Required questions become `TODO(question_id)` markers if unanswered.

## 3) Enable Dry Run

Set:

- `EPOXY_ANNOUNCE_ENABLED=1`
- `EPOXY_ANNOUNCE_DRY_RUN=1`

Observe for several days:

- Prep ping appears once at prep time
- `!announce.generate` works in prep thread
- `!announce.approve` transitions status
- Scheduled “post” records state without sending live message (dry run)

## 4) Switch Live

Set:

- `EPOXY_ANNOUNCE_DRY_RUN=0`

Keep using owner approval gate:

- `!announce.approve` is required before scheduled posting.

## 5) Daily Ops Commands

- `!announce.status [YYYY-MM-DD]`
- `!announce.answers [YYYY-MM-DD]`
- `!announce.answer <question_id> | <answer>`
- `!announce.generate [YYYY-MM-DD]`
- `!announce.override | <full_text>`
- `!announce.clear_override`
- `!announce.approve [YYYY-MM-DD]` (owner)
- `!announce.unapprove [YYYY-MM-DD]` (owner)
- `!announce.post_now [YYYY-MM-DD]` (owner)
- `!announce.prep_tomorrow_now` (owner, sends tomorrow prep ping/thread early)

Manual completion paths:

- `!announce.done [self|draft] [message_link] | [note]` (owner)
  - omitted mode defaults to `self`
  - `draft` marks “Epoxy drafted, human posted manually”
- `!announce.undo_done [YYYY-MM-DD]` (owner, pre-cutoff only)

## 6) Safety Checklist

- Confirm destination `target_channel_id` values before going live.
- Keep `EPOXY_ANNOUNCE_DRY_RUN=1` until at least one full cycle has been observed.
- Restrict owner IDs to trusted operators only.
- Use `!announce.done` whenever posting manually to suppress duplicate auto-posts.
