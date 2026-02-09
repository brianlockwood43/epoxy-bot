PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS messages (
    message_id INTEGER PRIMARY KEY,
    guild_id INTEGER,
    guild_name TEXT,
    channel_id INTEGER,
    channel_name TEXT,
    author_id INTEGER,
    author_name TEXT,
    created_at_utc TEXT,
    content TEXT,
    attachments TEXT
);

CREATE TABLE IF NOT EXISTS channel_state (
    channel_id INTEGER PRIMARY KEY,
    backfill_done INTEGER DEFAULT 0,
    last_backfill_at_utc TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_channel_id ON messages(channel_id);
CREATE INDEX IF NOT EXISTS idx_messages_author_id ON messages(author_id);

CREATE TABLE IF NOT EXISTS memory_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at_utc TEXT,
    created_ts INTEGER,
    updated_at_utc TEXT,
    last_verified_at_utc TEXT,
    expiry_at_utc TEXT,
    scope TEXT DEFAULT NULL,
    guild_id INTEGER,
    channel_id INTEGER,
    channel_name TEXT,
    author_id INTEGER,
    author_name TEXT,
    source_message_id INTEGER,
    logged_from_channel_id INTEGER,
    logged_from_channel_name TEXT,
    logged_from_message_id INTEGER,
    source_channel_id INTEGER,
    source_channel_name TEXT,
    type TEXT DEFAULT 'event',
    title TEXT DEFAULT NULL,
    text TEXT NOT NULL,
    tags_json TEXT,
    confidence REAL DEFAULT 0.6,
    stability TEXT DEFAULT 'medium',
    lifecycle TEXT DEFAULT 'active',
    superseded_by INTEGER DEFAULT NULL,
    importance INTEGER DEFAULT 0,
    tier INTEGER DEFAULT 1,
    summarized INTEGER DEFAULT 0,
    topic_id TEXT,
    topic_source TEXT DEFAULT 'manual',
    topic_confidence REAL
);

CREATE TABLE IF NOT EXISTS memory_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    summary_type TEXT DEFAULT 'topic_gist',
    scope TEXT DEFAULT NULL,
    topic_id TEXT,
    created_at_utc TEXT,
    updated_at_utc TEXT,
    start_ts INTEGER,
    end_ts INTEGER,
    tags_json TEXT,
    importance INTEGER DEFAULT 1,
    summary_text TEXT NOT NULL,
    covers_event_ids_json TEXT DEFAULT '[]',
    confidence REAL DEFAULT 0.6,
    stability TEXT DEFAULT 'medium',
    last_verified_at_utc TEXT,
    lifecycle TEXT DEFAULT 'active',
    tier INTEGER DEFAULT 2,
    generated_by_model TEXT,
    prompt_hash TEXT,
    job_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_mem_events_scope ON memory_events(scope);
CREATE INDEX IF NOT EXISTS idx_mem_events_type ON memory_events(type);
CREATE INDEX IF NOT EXISTS idx_mem_events_lifecycle ON memory_events(lifecycle);
CREATE INDEX IF NOT EXISTS idx_mem_events_last_verified ON memory_events(last_verified_at_utc);
CREATE INDEX IF NOT EXISTS idx_mem_events_created_ts ON memory_events(created_ts);
CREATE INDEX IF NOT EXISTS idx_mem_events_tier ON memory_events(tier);
CREATE INDEX IF NOT EXISTS idx_mem_events_importance ON memory_events(importance);

CREATE INDEX IF NOT EXISTS idx_mem_summaries_type ON memory_summaries(summary_type);
CREATE INDEX IF NOT EXISTS idx_mem_summaries_scope ON memory_summaries(scope);
CREATE INDEX IF NOT EXISTS idx_mem_summaries_lifecycle ON memory_summaries(lifecycle);
CREATE INDEX IF NOT EXISTS idx_mem_summaries_topic_id ON memory_summaries(topic_id);
CREATE INDEX IF NOT EXISTS idx_mem_summaries_end_ts ON memory_summaries(end_ts);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_events_fts
USING fts5(text, tags, tokenize='unicode61');

CREATE VIRTUAL TABLE IF NOT EXISTS memory_summaries_fts
USING fts5(topic_id, summary_text, tags, tokenize='unicode61');

