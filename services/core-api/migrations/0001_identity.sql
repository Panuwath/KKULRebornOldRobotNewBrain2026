CREATE TABLE IF NOT EXISTS web_users (
    sub TEXT PRIMARY KEY,
    email TEXT,
    display_name TEXT,
    role TEXT NOT NULL DEFAULT 'viewer',
    created_at_ms BIGINT,
    last_login_ms BIGINT,
    disabled BOOLEAN DEFAULT false
);

CREATE TABLE IF NOT EXISTS web_auth_sessions (
    token_hash TEXT PRIMARY KEY,
    sub TEXT,
    username TEXT,
    display_name TEXT,
    role TEXT,
    provider TEXT,
    created_at_ms BIGINT,
    expires_at_ms BIGINT
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value_encrypted BYTEA,
    updated_by TEXT,
    updated_at_ms BIGINT
);
