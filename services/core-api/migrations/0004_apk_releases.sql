CREATE TABLE IF NOT EXISTS apk_releases (
    version_code BIGINT PRIMARY KEY,
    version_name TEXT,
    sha256 TEXT,
    url TEXT,
    channel TEXT,
    notes TEXT,
    created_at_ms BIGINT
);

CREATE TABLE IF NOT EXISTS robot_update_events (
    id BIGSERIAL PRIMARY KEY,
    robot_slug TEXT,
    version_code BIGINT,
    state TEXT,
    detail_json JSONB,
    created_at_ms BIGINT
);
