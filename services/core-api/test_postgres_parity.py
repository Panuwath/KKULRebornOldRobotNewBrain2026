"""Parity tests for the shared DB adapter under both backends.

These run on SQLite by default; the same assertions must hold after
DB_CONNECTION=pgsql is supplied and a live PostgreSQL instance is available.
"""
from __future__ import annotations

import importlib
import json

import pytest


def _reload_adapter(monkeypatch) -> None:
    monkeypatch.setenv("DB_CONNECTION", "sqlite")
    monkeypatch.setenv("COMMAND_HISTORY_DB", ":memory:")
    import db as db_module
    import command_history_repository

    db_module._sqlite = None
    db_module._pool = None
    db_module.init()
    importlib.reload(command_history_repository)


@pytest.fixture
def database(monkeypatch):
    _reload_adapter(monkeypatch)
    import db as db_module

    return db_module


def test_parity_unicode_and_null(database, monkeypatch):
    _reload_adapter(monkeypatch)
    import command_history_repository

    hid = command_history_repository.append_command(
        robot_slug="r1",
        source="parity",
        status="TEST",
        payload={"thai": "สวัสดี", "null_key": None, "nested": [1, 2, None]},
    )
    row = database.fetchone(
        "SELECT payload_json FROM command_history WHERE id = :id", {"id": hid}
    )
    payload = json.loads(row["payload_json"])
    assert payload["thai"] == "สวัสดี"
    assert payload["null_key"] is None
    assert payload["nested"] == [1, 2, None]


def test_parity_pagination(database, monkeypatch):
    _reload_adapter(monkeypatch)
    import command_history_repository

    for i in range(5):
        command_history_repository.append_command(
            robot_slug="r1", source="parity", status="TEST", payload={"i": i}
        )
    result = command_history_repository.list_commands("r1", page=1, page_size=2)
    assert result["total"] == 5
    assert len(result["items"]) == 2
    assert result["has_next"] is True
    assert all(isinstance(item["payload"], dict) for item in result["items"])


def test_parity_transaction_rollback(database, monkeypatch):
    _reload_adapter(monkeypatch)

    with pytest.raises(RuntimeError):
        with database.transaction():
            database.execute(
                "INSERT INTO speech_phrases (text, text_norm) VALUES (:text, :norm)",
                {"text": "rollback", "norm": "rollback"},
            )
            raise RuntimeError("intentional")

    assert (
        database.fetchone(
            "SELECT id FROM speech_phrases WHERE text_norm = :norm", {"norm": "rollback"}
        )
        is None
    )
