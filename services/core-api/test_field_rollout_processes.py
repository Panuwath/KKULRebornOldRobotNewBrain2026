"""Real separate-process contention and restart tests using a temporary DB."""
import os
from pathlib import Path
import select
import subprocess
import sys
import json

import pytest
import db
import field_permit
import field_rollout


WORKER = '''
import json, sys
import db, field_rollout
db.init()
actor = {'sub': 'owner', 'role': 'operator'}
print('READY', flush=True)
sys.stdin.readline()
try:
    if sys.argv[1] == 'start':
        result = field_rollout.start('robot', sys.argv[2], actor)
    elif sys.argv[1] == 'get':
        result = field_rollout.get(sys.argv[2], 'robot', actor)
    else:
        result = field_rollout.transition(sys.argv[2], 'robot', actor, 0,
                                         rollback=sys.argv[1] == 'rollback')
    print(json.dumps(result))
except field_rollout.RolloutError as error:
    print(json.dumps({'error': str(error)}))
'''


@pytest.fixture
def database(tmp_path, monkeypatch):
    import sqlite3
    path = tmp_path / 'rollout.sqlite'
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    monkeypatch.setattr(db, '_sqlite', connection)
    monkeypatch.setattr(db, '_backend', 'sqlite')
    db.ensure_sqlite_tables()
    permit = field_permit.issue('robot', 'owner', level_max=3)
    yield path, permit
    connection.close()


def run_workers(path, action, target, count=2):
    env = {**os.environ, 'DB_CONNECTION': 'sqlite', 'COMMAND_HISTORY_DB': str(path)}
    workers = []
    try:
        for _ in range(count):
            workers.append(subprocess.Popen(
                [sys.executable, '-c', WORKER, action, target],
                cwd=Path(__file__).parent, env=env, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        for worker in workers:
            assert select.select([worker.stdout], [], [], 10)[0], 'worker startup timed out'
            assert worker.stdout.readline().strip() == 'READY'
        for worker in workers:
            worker.stdin.write('GO\n')
            worker.stdin.flush()
        results = []
        for worker in workers:
            stdout, stderr = worker.communicate(timeout=10)
            assert worker.returncode == 0, stderr
            results.append(json.loads(stdout))
        return results
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
            worker.wait(timeout=5)


def test_duplicate_start_across_processes(database):
    path, permit = database
    results = run_workers(path, 'start', permit['permit_id'])
    assert sum(row.get('state') == 'LOCKED' for row in results) == 1
    assert sum(row.get('error') == 'ACTIVE_SESSION_EXISTS' for row in results) == 1


@pytest.mark.parametrize('action', ['advance', 'rollback'])
def test_concurrent_transition_and_restart(database, action):
    path, permit = database
    session = field_rollout.start('robot', permit['permit_id'], {'sub': 'owner', 'role': 'operator'})
    results = run_workers(path, action, session['session_id'])
    if action == 'advance':
        assert sum(row.get('state') == 'SIMULATED_L1' for row in results) == 1
        assert sum(row.get('error') == 'REVISION_CONFLICT' for row in results) == 1
    else:
        assert results[0] == results[1]
        assert results[0]['state'] == 'ROLLED_BACK'
    persisted = run_workers(path, 'get', session['session_id'], count=1)[0]
    assert persisted['revision'] == 1
    assert len(persisted['events']) == 2
