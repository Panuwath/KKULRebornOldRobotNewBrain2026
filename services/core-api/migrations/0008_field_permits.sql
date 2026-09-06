CREATE TABLE IF NOT EXISTS field_permits (
    id SERIAL PRIMARY KEY,
    permit_id TEXT UNIQUE NOT NULL,
    robot_slug TEXT NOT NULL,
    operator_sub TEXT NOT NULL,
    level_max INTEGER NOT NULL DEFAULT 3,
    issued_at_ms BIGINT NOT NULL,
    expires_at_ms BIGINT NOT NULL,
    revoked_at_ms BIGINT,
    attestation_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_field_permits_robot_active
    ON field_permits (robot_slug, expires_at_ms)
    WHERE revoked_at_ms IS NULL;
