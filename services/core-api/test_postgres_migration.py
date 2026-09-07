"""Opt-in integration tests; create and remove ONLY their own random database."""
import os
from pathlib import Path
import sqlite3
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv('ZENBO_TEST_POSTGRES') != '1',
    reason='Set ZENBO_TEST_POSTGRES=1 and explicit local PG test credentials',
)


@pytest.fixture
def postgres(monkeypatch):
    import psycopg
    from psycopg import sql
    import db
    assert os.environ['DB_HOST'] in ('127.0.0.1', 'localhost'), 'Local test server required'
    name = 'zenbo_test_' + uuid.uuid4().hex
    with psycopg.connect(host=os.environ['DB_HOST'], port=os.environ['DB_PORT'],
                         user=os.environ['DB_USERNAME'], password=os.getenv('DB_PASSWORD', ''),
                         dbname='postgres', autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        try:
            db.close()
            monkeypatch.setenv('DB_CONNECTION', 'pgsql')
            monkeypatch.setenv('DB_DATABASE', name)
            db.init()
            yield db
        finally:
            db.close()
            admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))


def test_legacy_and_adapter_share_commit_and_rollback(postgres):
    db = postgres
    with pytest.raises(ValueError):
        with db.transaction():
            db.execute('INSERT INTO app_settings (key) VALUES (?)', ('modern',))
            with db.connection('must-not-create.sqlite3') as conn:
                conn.execute('INSERT INTO app_settings (key) VALUES (?)', ('legacy',))
                assert conn.execute('SELECT COUNT(*) FROM app_settings').fetchone() == (2,)
            raise ValueError('rollback both writers')
    assert db.fetchall('SELECT key FROM app_settings') == []
    with db.transaction():
        with db.connection('must-not-create.sqlite3') as conn:
            conn.execute('INSERT INTO app_settings (key) VALUES (?)', ('committed',))
    assert db.fetchone('SELECT key FROM app_settings') == {'key': 'committed'}


def test_parameters_and_repeated_migrations(postgres):
    db = postgres
    with db.connection('unused') as conn:
        assert conn.execute("SELECT ?::text, 'user-%', '?'", ('Thai text',)).fetchone() == ('Thai text', 'user-%', '?')
    assert db.fetchone("SELECT :value::text AS value, '100%' AS percent", {'value': 'hello'}) == {'value': 'hello', 'percent': '100%'}
    before = db.fetchall('SELECT filename FROM schema_migrations ORDER BY filename')
    db.init()
    assert db.fetchall('SELECT filename FROM schema_migrations ORDER BY filename') == before
    assert db.health_check()['ok'] is True


def make_source(path):
    with sqlite3.connect(path) as source:
        source.executescript('''
            CREATE TABLE app_settings (key TEXT PRIMARY KEY, value_encrypted BLOB, updated_by TEXT, updated_at_ms INTEGER);
            CREATE TABLE compiler_runs (id INTEGER PRIMARY KEY, input_text TEXT, intents_json TEXT, confidence REAL, fallback_used INTEGER, dispatched INTEGER, created_at_ms INTEGER);
            CREATE TABLE web_users (sub TEXT PRIMARY KEY, disabled INTEGER);
        ''')
        source.execute('INSERT INTO app_settings VALUES (?, ?, ?, ?)', ('setting', b'ciphertext', 'operator', 1800000000000))
        source.execute('INSERT INTO compiler_runs VALUES (?, ?, ?, ?, ?, ?, ?)', (101, 'unicode \u0e44\u0e17\u0e22', '{"a": [1, true]}', .91, 1, 0, 1800000000000))
        source.execute('INSERT INTO web_users VALUES (?, ?)', ('operator', 0))


def test_copy_dry_run_retry_and_sequences(postgres, tmp_path):
    from migrate_sqlite_postgres import copy_database
    source = tmp_path / 'source.sqlite3'
    make_source(source)
    report = copy_database(source)
    assert report['mode'] == 'dry-run'
    assert postgres.fetchall('SELECT * FROM compiler_runs') == []
    report = copy_database(source, apply=True)
    assert all(t['status'] == 'copied-and-verified' for t in report['tables'].values())
    assert postgres.fetchone('SELECT intents_json, fallback_used, dispatched FROM compiler_runs') == {
        'intents_json': {'a': [1, True]}, 'fallback_used': True, 'dispatched': False,
    }
    assert all(t['status'] == 'already-identical' for t in copy_database(source, apply=True)['tables'].values())
    assert postgres.execute('INSERT INTO compiler_runs (input_text) VALUES (?)', ('next',), returning_id=True) > 101
    with sqlite3.connect(source) as original:
        assert original.execute('SELECT COUNT(*) FROM compiler_runs').fetchone() == (1,)


def test_conflict_rolls_back_all_copied_tables(postgres, tmp_path):
    from migrate_sqlite_postgres import copy_database
    source = tmp_path / 'source.sqlite3'
    make_source(source)
    postgres.execute('INSERT INTO compiler_runs (id, input_text) VALUES (?, ?)', (101, 'destination-owned'))
    with pytest.raises(RuntimeError, match='different data'):
        copy_database(source, apply=True)
    assert postgres.fetchall('SELECT * FROM app_settings') == []
    assert postgres.fetchone('SELECT input_text FROM compiler_runs')['input_text'] == 'destination-owned'


def test_unknown_source_table_fails_closed(postgres, tmp_path):
    from migrate_sqlite_postgres import copy_database
    source = tmp_path / 'source.sqlite3'
    with sqlite3.connect(source) as conn:
        conn.execute('CREATE TABLE unknown_data (id INTEGER)')
    with pytest.raises(RuntimeError, match='Missing PostgreSQL'):
        copy_database(source, apply=True)


def test_relative_trace_jsonb_links_gateway_and_apk_receipts(postgres):
    from command_history_repository import append_command
    from command_trace import trace_command
    append_command("booky", "relative_motion", "MQTT_PUBLISHED", {
        "envelope": {"command_id": "pg-trace"}})
    append_command("booky", "apk_motion_ack", "SDK_STOP_REQUESTED", {
        "acknowledgement": {"command_id": "pg-trace"}, "apk_sha256": "a" * 64})
    append_command("other", "apk_motion_ack", "REJECTED", {"command_id": "pg-trace"})
    trace = trace_command("pg-trace", "booky")
    assert [event["status"] for event in trace["events"]] == ["MQTT_PUBLISHED", "SDK_STOP_REQUESTED"]
    assert trace["payload"]["apk_sha256"] == "a" * 64
    assert trace["physical_motion_verified"] is False
    # Existing PG schema stores TEXT; also support deployments using native JSONB.
    postgres.execute("ALTER TABLE command_history ALTER COLUMN payload_json TYPE jsonb USING payload_json::jsonb")
    assert trace_command("pg-trace", "booky")["events"] == trace["events"]


def test_field_rollout_jsonb_roundtrip_and_rollback_gate(postgres):
    import field_permit
    import field_rollout
    actor = {"sub": "pg-operator", "role": "operator"}
    permit = field_permit.issue("booky", actor["sub"], level_max=3)
    session = field_rollout.start("booky", permit["permit_id"], actor)
    session = field_rollout.transition(session["session_id"], "booky", actor, session["revision"])
    assert session["state"] == "SIMULATED_L1"
    assert field_rollout.authorize_preview(session["session_id"], "booky", permit["permit_id"], actor, 1)
    session = field_rollout.transition(session["session_id"], "booky", actor, session["revision"], rollback=True)
    with pytest.raises(field_rollout.RolloutError, match="SESSION_TERMINAL"):
        field_rollout.authorize_preview(session["session_id"], "booky", permit["permit_id"], actor, 1)
    assert session["physical_authorized"] is False


def test_active_rollout_recovery_owner_scope_and_revocation(postgres):
    import field_rollout as rollout
    import field_permit
    actor = {'sub': 'recovery-owner', 'role': 'operator'}
    permit = field_permit.issue('recovery-robot', actor['sub'], level_max=3)
    row = rollout.start('recovery-robot', permit['permit_id'], actor)
    field_permit.revoke(permit['permit_id'])
    assert rollout.active('recovery-robot', actor)['session'] == row
    assert rollout.active('recovery-robot', {'sub': 'other', 'role': 'operator'})['session'] is None
    assert rollout.active('recovery-robot', {'sub': 'admin', 'role': 'admin'})['session'] == row
    rollout.transition(row['session_id'], 'recovery-robot', actor, 0, rollback=True)
    assert rollout.active('recovery-robot', actor)['session'] is None
