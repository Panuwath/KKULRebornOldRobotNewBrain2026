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


def test_nested_relative_ack_trace_includes_gateway_and_terminal_events(database):
    append = command_history_repository.append_command
    append("booky-1", "relative_motion", "MQTT_PUBLISHED", {
        "envelope": {"command_id": "relative-1"},
        "acknowledgement": {"command_id": "relative-1", "state": "ACCEPTED"},
    })
    for state in ("APK_RECEIVED", "SDK_SUBMITTED", "SDK_STOP_REQUESTED"):
        append("booky-1", "apk_motion_ack", state, {
            "acknowledgement": {"command_id": "relative-1", "state": state},
            "apk_sha256": "a" * 64,
        })
    append("other-robot", "apk_motion_ack", "REJECTED", {
        "acknowledgement": {"command_id": "relative-1"}})
    result = command_trace.trace_command("relative-1", "booky-1")
    assert result is not None
    assert result["status"] == "SDK_STOP_REQUESTED"
    assert [event["status"] for event in result["events"]] == [
        "MQTT_PUBLISHED", "APK_RECEIVED", "SDK_SUBMITTED", "SDK_STOP_REQUESTED"]
    assert result["payload"]["apk_sha256"] == "a" * 64
    assert result["physical_motion_verified"] is False
    assert result["events_truncated"] is False


def test_trace_accepts_envelope_only_and_keeps_latest_100_events(database):
    for sequence in range(102):
        command_history_repository.append_command("booky", "relative_motion", "APK_RECEIVED", {
            "envelope": {"command_id": "bounded-trace"}, "sequence": sequence})
    result = command_trace.trace_command("bounded-trace", "booky")
    assert result is not None
    assert len(result["events"]) == 100
    assert result["events"][0]["payload"]["sequence"] == 2
    assert result["events"][-1]["payload"]["sequence"] == 101
    assert result["events_truncated"] is True


def test_conflicting_nested_ids_do_not_cross_link_commands(database):
    command_history_repository.append_command("booky", "relative_motion", "REJECTED", {
        "command_id": "owner-id", "acknowledgement": {"command_id": "other-id"}})
    assert command_trace.trace_command("other-id", "booky") is None
    assert command_trace.trace_command("owner-id", "booky") is not None
