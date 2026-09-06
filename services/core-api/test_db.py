"""Contract tests for the new database adapter."""
import hashlib
import importlib

import pytest


@pytest.fixture
def database(monkeypatch):
    monkeypatch.setenv("DB_CONNECTION", "sqlite")
    monkeypatch.setenv("COMMAND_HISTORY_DB", ":memory:")
    import db

    adapter = importlib.reload(db)
    adapter.init()
    return adapter


def test_execute_fetch_and_returning_id(database):
    phrase_id = database.execute(
        "INSERT INTO speech_phrases (text, text_norm) VALUES (:text, :norm)",
        {"text": "Hello", "norm": "hello"},
        returning_id=True,
    )

    assert phrase_id == 1
    assert database.fetchone(
        "SELECT text, text_norm FROM speech_phrases WHERE id = :id", {"id": phrase_id}
    ) == {"text": "Hello", "text_norm": "hello"}
    assert database.fetchall("SELECT id FROM speech_phrases") == [{"id": 1}]


def test_transaction_rolls_back(database):
    with pytest.raises(RuntimeError):
        with database.transaction():
            database.execute(
                "INSERT INTO speech_phrases (text) VALUES (:text)", {"text": "discarded"}
            )
            raise RuntimeError("force rollback")

    assert database.fetchone(
        "SELECT id FROM speech_phrases WHERE text = :text", {"text": "discarded"}
    ) is None


def test_new_tables_exist(database):
    expected = {
        "web_users", "web_auth_sessions", "app_settings", "speech_phrases",
        "camera_sessions", "apk_releases", "robot_update_events", "compiler_runs",
        "command_history",
    }
    rows = database.fetchall(
        "SELECT name FROM sqlite_master WHERE type = :type", {"type": "table"}
    )

    assert expected <= {row["name"] for row in rows}
    assert database.health_check()["ok"] is True


def test_web_user_schema_has_provider(database):
    columns = database.fetchall("PRAGMA table_info(web_users)")

    assert "provider" in {column["name"] for column in columns}


def test_session_repository_login_lookup_logout(database, monkeypatch):
    import oidc

    monkeypatch.setattr(oidc, "db", database)
    token = oidc.create_web_auth_session(
        sub="admin",
        display_name="Admin",
        role="admin",
        provider="password",
        ttl_seconds=300,
    )
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

    session = oidc.get_web_auth_session(token_hash)
    assert session["sub"] == "admin"
    assert session["provider"] == "password"

    oidc.delete_web_auth_session(token_hash)
    assert oidc.get_web_auth_session(token_hash) is None
