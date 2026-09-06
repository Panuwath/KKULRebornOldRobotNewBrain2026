CREATE TABLE IF NOT EXISTS camera_sessions (
    session_id TEXT PRIMARY KEY,
    robot_slug TEXT,
    username TEXT,
    started_at_ms BIGINT,
    ended_at_ms BIGINT,
    state TEXT
);

CREATE INDEX IF NOT EXISTS idx_camera_sessions_robot_started
    ON camera_sessions (robot_slug, started_at_ms);
