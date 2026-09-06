CREATE TABLE IF NOT EXISTS compiler_runs (
    id BIGSERIAL PRIMARY KEY,
    user_sub TEXT,
    robot_slug TEXT,
    input_text TEXT,
    provider TEXT,
    model TEXT,
    intents_json JSONB,
    confidence REAL,
    latency_ms INT,
    prompt_tokens INT,
    completion_tokens INT,
    fallback_used BOOLEAN,
    dispatched BOOLEAN,
    created_at_ms BIGINT
);
