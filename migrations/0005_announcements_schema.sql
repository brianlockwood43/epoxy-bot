CREATE TABLE IF NOT EXISTS announcement_cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_date_local TEXT NOT NULL,
    timezone TEXT NOT NULL,
    weekday_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned',
    completion_path TEXT DEFAULT NULL,
    prep_channel_id INTEGER,
    prep_message_id INTEGER,
    prep_thread_id INTEGER,
    target_channel_id INTEGER,
    publish_at_utc TEXT,
    draft_text TEXT,
    override_text TEXT,
    final_text TEXT,
    approved_by_user_id INTEGER,
    approved_at_utc TEXT,
    posted_message_id INTEGER,
    posted_at_utc TEXT,
    manual_done_by_user_id INTEGER,
    manual_done_at_utc TEXT,
    manual_done_link TEXT,
    manual_done_note TEXT,
    manual_prev_status TEXT,
    created_at_utc TEXT,
    updated_at_utc TEXT,
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS announcement_answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id INTEGER NOT NULL,
    question_id TEXT NOT NULL,
    answer_text TEXT NOT NULL,
    answered_by_user_id INTEGER,
    answered_at_utc TEXT,
    source_message_id INTEGER
);

CREATE TABLE IF NOT EXISTS announcement_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id INTEGER,
    action TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    actor_user_id INTEGER,
    payload_json TEXT DEFAULT '{}',
    created_at_utc TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_announce_cycles_date_tz
ON announcement_cycles(target_date_local, timezone);

CREATE INDEX IF NOT EXISTS idx_announce_cycles_status_publish
ON announcement_cycles(status, publish_at_utc);

CREATE UNIQUE INDEX IF NOT EXISTS idx_announce_answers_cycle_question
ON announcement_answers(cycle_id, question_id);

CREATE INDEX IF NOT EXISTS idx_announce_answers_cycle
ON announcement_answers(cycle_id);

CREATE INDEX IF NOT EXISTS idx_announce_audit_cycle_created
ON announcement_audit_log(cycle_id, created_at_utc);
