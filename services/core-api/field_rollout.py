"""Durable software-only rollout rehearsal. Never authorizes physical motion."""
import json
import time
import uuid

import db
import field_permit


SCHEMA = """
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
"""


class RolloutError(ValueError):
    pass


def _actor(actor):
    if (not isinstance(actor, dict) or actor.get('role') not in {'admin', 'operator'}
            or not isinstance(actor.get('sub'), str) or not actor['sub'].strip()):
        raise RolloutError('OPERATOR_REQUIRED')


def _permit(permit_id, robot_slug, actor, level=1):
    # Called inside the session transaction. Acquire the same row lock as
    # revocation before reading, including across PostgreSQL workers.
    db.execute('UPDATE field_permits SET permit_id = permit_id WHERE permit_id = :id',
               {'id': permit_id})
    permit = field_permit.get_active(permit_id)
    if (not permit or permit['robot_slug'] != robot_slug
            or permit['operator_sub'] != actor['sub']
            or permit['expires_at_ms'] <= int(time.time() * 1000)
            or permit['level_max'] < level):
        raise RolloutError('ACTIVE_MATCHING_FIELD_PERMIT_REQUIRED')


def get(session_id, robot_slug, actor):
    _actor(actor)
    row = db.fetchone('SELECT * FROM field_rollout_sessions WHERE session_id = :id AND robot_slug = :robot',
                      {'id': session_id, 'robot': robot_slug})
    if not row:
        raise RolloutError('SESSION_NOT_FOUND')
    if row['operator_sub'] != actor['sub'] and actor['role'] != 'admin':
        raise RolloutError('SESSION_OWNER_REQUIRED')
    return _snapshot(row)


def _snapshot(row):
    row = dict(row)
    row['events'] = json.loads(row.pop('events_json'))
    return {**row, 'dry_run': True, 'physical_authorized': False, 'mqtt_publish_attempted': False}


def active(robot_slug, actor):
    """Recover an open session after a lost response, without renewing its permit."""
    _actor(actor)
    owner = '' if actor['role'] == 'admin' else ' AND operator_sub = :owner'
    params = {'robot': robot_slug}
    if owner:
        params['owner'] = actor['sub']
    row = db.fetchone("SELECT * FROM field_rollout_sessions WHERE robot_slug = :robot AND state <> 'ROLLED_BACK'" + owner, params)
    return {'session': _snapshot(row) if row else None, 'dry_run': True,
            'physical_authorized': False, 'mqtt_publish_attempted': False}


def start(robot_slug, permit_id, actor):
    _actor(actor)
    session_id = str(uuid.uuid4())
    events = json.dumps([{'state': 'LOCKED', 'actor': actor['sub'], 'at_ms': int(time.time() * 1000)}])
    with db.transaction():
        _permit(permit_id, robot_slug, actor)
        db.execute('''INSERT INTO field_rollout_sessions
            (session_id, robot_slug, operator_sub, permit_id, state, events_json)
            VALUES (:id, :robot, :actor, :permit, 'LOCKED', :events)
            ON CONFLICT DO NOTHING''',
            {'id': session_id, 'robot': robot_slug, 'actor': actor['sub'], 'permit': permit_id, 'events': events})
        if not db.fetchone('SELECT session_id FROM field_rollout_sessions WHERE session_id = :id', {'id': session_id}):
            raise RolloutError('ACTIVE_SESSION_EXISTS')
    return get(session_id, robot_slug, actor)


def transition(session_id, robot_slug, actor, revision, rollback=False):
    _actor(actor)
    if type(revision) is not int or revision < 0:
        raise RolloutError('INVALID_REVISION')
    with db.transaction():
        # Serialize before reading to avoid SQLite read-to-write upgrades and
        # to make simultaneous rollback retries return the same terminal state.
        db.execute('UPDATE field_rollout_sessions SET revision = revision WHERE session_id = :id',
                   {'id': session_id})
        row = get(session_id, robot_slug, actor)
        if row['state'] == 'ROLLED_BACK':
            if rollback:
                return row
            raise RolloutError('SESSION_TERMINAL')
        if row['revision'] != revision:
            raise RolloutError('REVISION_CONFLICT')
        if rollback:
            state = 'ROLLED_BACK'
        else:
            if row['operator_sub'] != actor['sub']:
                raise RolloutError('SESSION_OWNER_REQUIRED')
            stages = ['LOCKED', 'SIMULATED_L1', 'SIMULATED_L2', 'SIMULATED_L3']
            level = stages.index(row['state']) + 1
            if level > 3:
                raise RolloutError('L1_L3_DRILL_COMPLETE')
            _permit(row['permit_id'], robot_slug, actor, level)
            state = stages[level]
        token = str(uuid.uuid4())
        events = row['events'] + [{'state': state, 'actor': actor['sub'],
                                  'at_ms': int(time.time() * 1000), 'transition_id': token}]
        db.execute('''UPDATE field_rollout_sessions SET state = :state,
            revision = revision + 1, events_json = :events
            WHERE session_id = :id AND revision = :revision''',
            {'state': state, 'events': json.dumps(events), 'id': session_id, 'revision': revision})
        result = get(session_id, robot_slug, actor)
        if result['events'][-1].get('transition_id') != token:
            raise RolloutError('REVISION_CONFLICT')
        return result


def authorize_preview(session_id, robot_slug, permit_id, actor, level):
    """Snapshot authorization for a software preview, never for live dispatch."""
    _actor(actor)
    if type(level) is not int or not 1 <= level <= 3:
        raise RolloutError('LEVEL_OUTSIDE_DRILL')
    with db.transaction():
        db.execute('UPDATE field_rollout_sessions SET revision = revision WHERE session_id = :id',
                   {'id': session_id})
        row = get(session_id, robot_slug, actor)
        if row['operator_sub'] != actor['sub']:
            raise RolloutError('SESSION_OWNER_REQUIRED')
        if row['permit_id'] != permit_id:
            raise RolloutError('SESSION_PERMIT_MISMATCH')
        if row['state'] == 'ROLLED_BACK':
            raise RolloutError('SESSION_TERMINAL')
        enabled = {'LOCKED': 0, 'SIMULATED_L1': 1, 'SIMULATED_L2': 2, 'SIMULATED_L3': 3}[row['state']]
        if level > enabled:
            raise RolloutError('SESSION_LEVEL_NOT_REACHED')
        _permit(permit_id, robot_slug, actor, level)
        return {'session_id': session_id, 'revision': row['revision'],
                'state': row['state'], 'dry_run': True, 'physical_authorized': False}
