from __future__ import annotations

import importlib
import json

import command_history_repository
import command_trace
import db
import pytest


@pytest.fixture
def database(monkeypatch):
    monkeypatch.setenv("DB_CONNECTION", "sqlite")
    monkeypatch.setenv("COMMAND_HISTORY_DB", ":memory:")
    importlib.reload(db)
    db._sqlite = None
    db._pool = None
    db.init()
    importlib.reload(command_history_repository)
    importlib.reload(command_trace)
    return db


def _sample_payload(command_id: str):
    return {"command_id": command_id, "x": 0.05, "y": 0.0, "thai": "สวัสดี"}


def test_trace_finds_recent_command_by_id(database, monkeypatch):
    monkeypatch.setenv("DB_CONNECTION", "sqlite")
    monkeypatch.setenv("COMMAND_HISTORY_DB", ":memory:")
    importlib.reload(command_history_repository)
    importlib.reload(command_trace)

    command_history_repository.append_command(
        "booky-1", "liff", "MQTT_PUBLISHED", _sample_payload("cmd-123"),
    )
    result = command_trace.trace_command("cmd-123")
    assert result is not None
    assert result["command_id"] == "cmd-123"
    assert result["robot_slug"] == "booky-1"
    assert result["payload"]["thai"] == "สวัสดี"


def test_trace_returns_none_for_missing_command(database, monkeypatch):
    monkeypatch.setenv("DB_CONNECTION", "sqlite")
    monkeypatch.setenv("COMMAND_HISTORY_DB", ":memory:")
    importlib.reload(command_trace)
    assert command_trace.trace_command("missing") is None


def test_trace_filters_by_robot_slug(database, monkeypatch):
    monkeypatch.setenv("DB_CONNECTION", "sqlite")
    monkeypatch.setenv("COMMAND_HISTORY_DB", ":memory:")
    importlib.reload(command_history_repository)
    importlib.reload(command_trace)

    command_history_repository.append_command(
        "booky-a", "liff", "MQTT_PUBLISHED", _sample_payload("cmd-shared"),
    )
    command_history_repository.append_command(
        "booky-b", "liff", "MQTT_PUBLISHED", _sample_payload("cmd-shared"),
    )
    result = command_trace.trace_command("cmd-shared", robot_slug="booky-b")
    assert result is not None
    assert result["robot_slug"] == "booky-b"
