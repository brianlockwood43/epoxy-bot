CREATE TABLE IF NOT EXISTS context_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    caller_type TEXT NOT NULL,
    surface TEXT NOT NULL,
    channel_id INTEGER,
    guild_id INTEGER,
    sensitivity_policy_id TEXT,
    allowed_capabilities_json TEXT DEFAULT '[]',
    created_at_utc TEXT,
    updated_at_utc TEXT
);

CREATE TABLE IF NOT EXISTS user_profiles (
    id INTEGER PRIMARY KEY,
    layer_estimate TEXT DEFAULT 'unknown',
    risk_flags_json TEXT DEFAULT '[]',
    preferred_tone TEXT,
    dev_arc_meta_ids_json TEXT DEFAULT '[]',
    last_seen_at_utc TEXT
);

CREATE TABLE IF NOT EXISTS controller_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL,
    persona TEXT DEFAULT 'guide',
    depth REAL DEFAULT 0.35,
    strictness REAL DEFAULT 0.65,
    intervention_level REAL DEFAULT 0.35,
    memory_budget_json TEXT DEFAULT '{}',
    tool_budget_json TEXT DEFAULT '[]',
    last_trained_at_utc TEXT,
    lifecycle TEXT DEFAULT 'active',
    created_at_utc TEXT,
    updated_at_utc TEXT
);

CREATE TABLE IF NOT EXISTS episode_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_utc TEXT NOT NULL,
    context_profile_id INTEGER,
    user_id INTEGER,
    controller_config_id INTEGER,
    input_excerpt TEXT,
    assistant_output_excerpt TEXT,
    retrieved_memory_ids_json TEXT DEFAULT '[]',
    tags_json TEXT DEFAULT '[]',
    explicit_rating INTEGER,
    implicit_signals_json TEXT DEFAULT '{}',
    human_notes TEXT,
    guild_id INTEGER,
    channel_id INTEGER,
    message_id INTEGER,
    created_at_utc TEXT
);

CREATE INDEX IF NOT EXISTS idx_context_profiles_surface ON context_profiles(surface);
CREATE INDEX IF NOT EXISTS idx_context_profiles_channel_id ON context_profiles(channel_id);
CREATE INDEX IF NOT EXISTS idx_controller_configs_scope ON controller_configs(scope);
CREATE INDEX IF NOT EXISTS idx_controller_configs_lifecycle ON controller_configs(lifecycle);
CREATE INDEX IF NOT EXISTS idx_episode_logs_timestamp ON episode_logs(timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_episode_logs_user_id ON episode_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_episode_logs_context ON episode_logs(context_profile_id);

