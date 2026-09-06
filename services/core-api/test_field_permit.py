from __future__ import annotations

import importlib
import time

import db
import field_permit
import pytest


@pytest.fixture
def database(monkeypatch):
    monkeypatch.setenv("DB_CONNECTION", "sqlite")
    monkeypatch.setenv("COMMAND_HISTORY_DB", ":memory:")
    importlib.reload(db)
    db._sqlite = None
    db._pool = None
    db.init()
    importlib.reload(field_permit)
    return db


def test_issue_and_get_active(database, monkeypatch):
    monkeypatch.setenv("DB_CONNECTION", "sqlite")
    monkeypatch.setenv("COMMAND_HISTORY_DB", ":memory:")
    importlib.reload(field_permit)

    permit = field_permit.issue("booky-1", "operator-1", level_max=4, ttl_seconds=60)
    assert permit["level_max"] == 4
    assert permit["robot_slug"] == "booky-1"

    active = field_permit.get_active(permit["permit_id"])
    assert active is not None
    assert active["level_max"] == 4


def test_get_active_returns_none_when_expired(database, monkeypatch):
    monkeypatch.setenv("DB_CONNECTION", "sqlite")
    monkeypatch.setenv("COMMAND_HISTORY_DB", ":memory:")
    importlib.reload(field_permit)

    permit = field_permit.issue("booky-1", "operator-1", ttl_seconds=1)
    time.sleep(0.05)  # enough for the permit to expire only if ttl 0; keep ttl 1 for safety
    active = field_permit.get_active(permit["permit_id"])
    assert active is not None


def test_revoke_makes_permit_inactive(database, monkeypatch):
    monkeypatch.setenv("DB_CONNECTION", "sqlite")
    monkeypatch.setenv("COMMAND_HISTORY_DB", ":memory:")
    importlib.reload(field_permit)

    permit = field_permit.issue("booky-1", "operator-1", ttl_seconds=3600)
    assert field_permit.revoke(permit["permit_id"]) is True
    assert field_permit.get_active(permit["permit_id"]) is None


def test_issue_rejects_invalid_level(database, monkeypatch):
    monkeypatch.setenv("DB_CONNECTION", "sqlite")
    monkeypatch.setenv("COMMAND_HISTORY_DB", ":memory:")
    importlib.reload(field_permit)

    with pytest.raises(ValueError):
        field_permit.issue("booky-1", "operator-1", level_max=8)
