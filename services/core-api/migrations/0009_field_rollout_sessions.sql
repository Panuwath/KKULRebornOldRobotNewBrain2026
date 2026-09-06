CREATE TABLE IF NOT EXISTS field_rollout_sessions (
    session_id TEXT PRIMARY KEY,
    robot_slug TEXT NOT NULL,
    operator_sub TEXT NOT NULL,
    permit_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('LOCKED', 'SIMULATED_L1', 'SIMULATED_L2', 'SIMULATED_L3', 'ROLLED_BACK')),
    revision INTEGER NOT NULL DEFAULT 0,
    events_json TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS field_rollout_one_active_robot
ON field_rollout_sessions(robot_slug) WHERE state <> 'ROLLED_BACK';
