import sqlite3
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import db
import field_permit
import field_rollout as rollout
from field_rollout_api import router, operator

ACTOR = {'sub': 'operator-a', 'role': 'operator'}


@pytest.fixture
def fixture(monkeypatch):
    connection = sqlite3.connect(':memory:', check_same_thread=False)
    connection.row_factory = sqlite3.Row
    monkeypatch.setattr(db, '_sqlite', connection)
    monkeypatch.setattr(db, '_backend', 'sqlite')
    db.ensure_sqlite_tables()
    permit = field_permit.issue('robot-a', ACTOR['sub'], level_max=3)
    yield permit
    connection.close()


def test_stages_rollback_and_single_session(fixture):
    row = rollout.start('robot-a', fixture['permit_id'], ACTOR)
    with pytest.raises(rollout.RolloutError, match='ACTIVE_SESSION_EXISTS'):
        rollout.start('robot-a', fixture['permit_id'], ACTOR)
    for level in range(1, 4):
        row = rollout.transition(row['session_id'], 'robot-a', ACTOR, row['revision'])
        assert row['state'] == f'SIMULATED_L{level}'
        assert row['physical_authorized'] is False
    with pytest.raises(rollout.RolloutError, match='L1_L3_DRILL_COMPLETE'):
        rollout.transition(row['session_id'], 'robot-a', ACTOR, 3)
    end = rollout.transition(row['session_id'], 'robot-a', ACTOR, 3, rollback=True)
    assert rollout.transition(row['session_id'], 'robot-a', ACTOR, 3, rollback=True) == end
    with pytest.raises(rollout.RolloutError, match='SESSION_TERMINAL'):
        rollout.transition(row['session_id'], 'robot-a', ACTOR, 4)
    assert rollout.start('robot-a', fixture['permit_id'], ACTOR)['session_id'] != row['session_id']


def test_revoke_blocks_advance_but_allows_rollback(fixture):
    row = rollout.start('robot-a', fixture['permit_id'], ACTOR)
    field_permit.revoke(fixture['permit_id'])
    with pytest.raises(rollout.RolloutError, match='ACTIVE_MATCHING'):
        rollout.transition(row['session_id'], 'robot-a', ACTOR, 0)
    assert rollout.transition(row['session_id'], 'robot-a', ACTOR, 0, rollback=True)['state'] == 'ROLLED_BACK'


def test_owner_robot_revision_and_level(fixture):
    row = rollout.start('robot-a', fixture['permit_id'], ACTOR)
    with pytest.raises(rollout.RolloutError, match='REVISION_CONFLICT'):
        rollout.transition(row['session_id'], 'robot-a', ACTOR, 9)
    with pytest.raises(rollout.RolloutError, match='SESSION_OWNER_REQUIRED'):
        rollout.get(row['session_id'], 'robot-a', {'sub': 'other', 'role': 'operator'})
    with pytest.raises(rollout.RolloutError, match='SESSION_NOT_FOUND'):
        rollout.get(row['session_id'], 'robot-b', ACTOR)
    db.execute('UPDATE field_permits SET level_max = 1')
    rollout.transition(row['session_id'], 'robot-a', ACTOR, 0)
    with pytest.raises(rollout.RolloutError, match='ACTIVE_MATCHING'):
        rollout.transition(row['session_id'], 'robot-a', ACTOR, 1)


def test_api_auth_and_expiry(fixture):
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    root = '/api/v1/robots/robot-a/rollout-drills'
    assert client.post(root, json={'permit_id': fixture['permit_id']}).status_code == 403
    app.dependency_overrides[operator] = lambda: ACTOR
    response = client.post(root, json={'permit_id': fixture['permit_id']})
    assert response.status_code == 200
    row = response.json()
    assert row['mqtt_publish_attempted'] is False
    db.execute('UPDATE field_permits SET expires_at_ms = 0')
    assert client.post(root + '/' + row['session_id'] + '/advance', json={'revision': 0}).status_code == 409
    assert client.post(root + '/' + row['session_id'] + '/rollback', json={'revision': 0}).status_code == 200


def test_preview_requires_reached_level_matching_permit_and_open_session(fixture):
    row = rollout.start('robot-a', fixture['permit_id'], ACTOR)
    args = (row['session_id'], 'robot-a', fixture['permit_id'], ACTOR)
    with pytest.raises(rollout.RolloutError, match='SESSION_LEVEL_NOT_REACHED'):
        rollout.authorize_preview(*args, 1)
    rollout.transition(row['session_id'], 'robot-a', ACTOR, 0)
    assert rollout.authorize_preview(*args, 1)['physical_authorized'] is False
    with pytest.raises(rollout.RolloutError, match='SESSION_PERMIT_MISMATCH'):
        rollout.authorize_preview(row['session_id'], 'robot-a', 'another', ACTOR, 1)
    with pytest.raises(rollout.RolloutError, match='LEVEL_OUTSIDE_DRILL'):
        rollout.authorize_preview(*args, 4)
    rollout.transition(row['session_id'], 'robot-a', ACTOR, 1, rollback=True)
    with pytest.raises(rollout.RolloutError, match='SESSION_TERMINAL'):
        rollout.authorize_preview(*args, 1)


def test_simultaneous_advances_cannot_skip_a_level(fixture):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    row = rollout.start('robot-a', fixture['permit_id'], ACTOR)
    barrier = Barrier(2)

    def advance():
        barrier.wait(timeout=5)
        try:
            return rollout.transition(row['session_id'], 'robot-a', ACTOR, 0)['state']
        except rollout.RolloutError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: advance(), range(2)))
    assert sorted(results) == ['REVISION_CONFLICT', 'SIMULATED_L1']
    assert len(rollout.get(row['session_id'], 'robot-a', ACTOR)['events']) == 2


def test_admin_can_abort_revoked_session_but_not_preview_as_owner(fixture):
    admin = {'sub': 'admin', 'role': 'admin'}
    row = rollout.start('robot-a', fixture['permit_id'], ACTOR)
    rollout.transition(row['session_id'], 'robot-a', ACTOR, 0)
    with pytest.raises(rollout.RolloutError, match='SESSION_OWNER_REQUIRED'):
        rollout.authorize_preview(row['session_id'], 'robot-a', fixture['permit_id'], admin, 1)
    field_permit.revoke(fixture['permit_id'])
    result = rollout.transition(row['session_id'], 'robot-a', admin, 1, rollback=True)
    assert result['events'][-1]['actor'] == 'admin'


def test_expiry_boundary_and_repository_input(fixture, monkeypatch):
    monkeypatch.setattr(field_permit.time, 'time', lambda: fixture['expires_at_ms'] / 1000)
    assert field_permit.get_active(fixture['permit_id']) is None
    for kwargs in ({'level_max': True}, {'ttl_seconds': 0}, {'ttl_seconds': True}):
        with pytest.raises(ValueError):
            field_permit.issue('robot-a', ACTOR['sub'], **kwargs)
    with pytest.raises(ValueError):
        field_permit.issue('robot-a', ' ')


def test_main_dry_route_honors_session_before_dispatch(fixture):
    # Load the actual decorated route without main.py's application startup,
    # broker setup and unrelated services. The dispatch dependency is a spy.
    import ast
    import time
    from pathlib import Path
    from typing import Optional
    from fastapi import Header, Depends, HTTPException
    from motion_contract import RelativeMotionRequest
    source = ast.parse(Path(__file__).with_name('main.py').read_text())
    names = {'robot_relative_motion_dry_run', '_require_field_permit_actor', '_field_rollout_rollback_plan'}
    selected = ast.Module(body=[node for node in source.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                               and node.name in names], type_ignores=[])
    app = FastAPI()
    dispatched = []

    def dispatch(*args, **kwargs):
        dispatched.append(kwargs)
        assert kwargs['dry_run'] is True
        return {'would_publish': True, 'published': False}, fixture, {'ready': True}

    namespace = {'app': app, 'Optional': Optional, 'Dict': dict, 'Any': object,
                 'Header': Header, 'Depends': Depends, 'HTTPException': HTTPException,
                 'RelativeMotionRequest': RelativeMotionRequest,
                 'require_role': lambda *roles: lambda: ACTOR,
                 '_dispatch_field_relative_motion': dispatch, 'FIELD_ROLLOUT_MAX_LEVEL': 3}
    exec(compile(selected, '<isolated-main-route>', 'exec'), namespace)
    row = rollout.start('robot-a', fixture['permit_id'], ACTOR)
    rollout.transition(row['session_id'], 'robot-a', ACTOR, 0)
    now = int(time.time() * 1000)
    body = {'command_id': '018f47d2-f228-7de0-b025-4ef6a7e416f8',
            'source_session_id': '018f47d2-f228-7de0-b025-4ef6a7e416f9',
            'source_seq': 1, 'issued_at_ms': now, 'expires_at_ms': now + 1000,
            'motion_request': {'control_mode': 'RELATIVE_BODY', 'x_m': 0.1,
                               'y_m': 0, 'theta_deg': 0, 'requested_speed_level': 1}}
    client = TestClient(app)
    url = '/api/v1/robots/robot-a/relative-motion/dry-run'
    headers = {'X-Field-Permit-Id': fixture['permit_id'], 'X-Rollout-Session-Id': row['session_id']}
    assert client.post(url, json=body).json()['decision'] == 'BLOCKED'
    assert dispatched == []
    assert client.post(url, json=body, headers=headers).json()['decision'] == 'ALLOWED'
    rollout.transition(row['session_id'], 'robot-a', ACTOR, 1, rollback=True)
    result = client.post(url, json=body, headers=headers).json()
    assert result['decision'] == 'BLOCKED'
    assert result['gate']['code'] == 'SESSION_TERMINAL'
    assert len(dispatched) == 1


def test_active_recovery_is_owner_scoped_and_survives_permit_revocation(fixture):
    assert rollout.active('robot-a', ACTOR)['session'] is None
    row = rollout.start('robot-a', fixture['permit_id'], ACTOR)
    field_permit.revoke(fixture['permit_id'])
    assert rollout.active('robot-a', ACTOR)['session'] == row
    assert rollout.active('robot-b', ACTOR)['session'] is None
    assert rollout.active('robot-a', {'sub': 'other', 'role': 'operator'})['session'] is None
    assert rollout.active('robot-a', {'sub': 'admin', 'role': 'admin'})['session'] == row
    rollout.transition(row['session_id'], 'robot-a', ACTOR, 0, rollback=True)
    assert rollout.active('robot-a', ACTOR)['session'] is None
    assert rollout.get(row['session_id'], 'robot-a', ACTOR)['state'] == 'ROLLED_BACK'


def test_active_api_is_authenticated_and_precedes_session_route(fixture):
    app = FastAPI(); app.include_router(router); client = TestClient(app)
    path = '/api/v1/robots/robot-a/rollout-drills/active'
    assert client.get(path).status_code == 403
    app.dependency_overrides[operator] = lambda: ACTOR
    row = rollout.start('robot-a', fixture['permit_id'], ACTOR)
    response = client.get(path)
    assert response.status_code == 200
    assert response.json()['session']['session_id'] == row['session_id']
    assert response.json()['mqtt_publish_attempted'] is False
    assert response.json()['physical_authorized'] is False
    assert rollout.get(row['session_id'], 'robot-a', ACTOR)['revision'] == 0
