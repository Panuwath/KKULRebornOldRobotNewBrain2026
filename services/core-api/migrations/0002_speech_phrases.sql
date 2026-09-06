CREATE TABLE IF NOT EXISTS speech_phrases (
    id BIGSERIAL PRIMARY KEY,
    user_sub TEXT,
    robot_slug TEXT,
    text TEXT NOT NULL,
    text_norm TEXT,
    voice_profile TEXT,
    face TEXT,
    use_count INT DEFAULT 1,
    pinned BOOLEAN DEFAULT false,
    scope TEXT DEFAULT 'personal',
    created_at_ms BIGINT,
    last_used_at_ms BIGINT,
    deleted_at_ms BIGINT
);

CREATE INDEX IF NOT EXISTS idx_speech_phrases_user_text
    ON speech_phrases (user_sub, text_norm);
CREATE INDEX IF NOT EXISTS idx_speech_phrases_last_used
    ON speech_phrases (last_used_at_ms);
