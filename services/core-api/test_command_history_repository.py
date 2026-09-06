import importlib

import pytest


@pytest.fixture
def repository(monkeypatch):
    monkeypatch.setenv("DB_CONNECTION", "sqlite")
    monkeypatch.setenv("COMMAND_HISTORY_DB", ":memory:")
    import db
    import command_history_repository

    database = importlib.reload(db)
    database.init()
    repo = importlib.reload(command_history_repository)
    return database, repo


def test_append_and_paginate_preserves_contract(repository):
    _, repo = repository
    first_id = repo.append_command(
        "booky-1",
        "liff",
        "MQTT_PUBLISHED",
        {"text": "สวัสดี", "metadata": None},
        accepted_latency_ms=None,
        user_id=None,
        display_name="ผู้ดูแล",
        created_at_ms=1_000,
    )
    second_id = repo.append_command(
        "booky-1",
        "liff",
        "REJECTED",
        {"reason": "SPEED_EXCEEDS_POLICY"},
        accepted_latency_ms=12,
        user_id="user-1",
        created_at_ms=1_001,
    )
    repo.append_command("booky-2", None, "MQTT_PUBLISHED", {"ok": True}, created_at_ms=1_002)

    first_page = repo.list_commands("booky-1", page=1, page_size=1)
    second_page = repo.list_commands("booky-1", page=2, page_size=1)

    assert second_id == first_id + 1
    assert first_page == {
        "items": [{
            "id": second_id,
            "created_at_ms": 1_001,
            "robot_slug": "booky-1",
            "source": "liff",
            "status": "REJECTED",
            "accepted_latency_ms": 12,
            "payload": {"reason": "SPEED_EXCEEDS_POLICY"},
            "user_id": "user-1",
            "display_name": None,
        }],
        "page": 1,
        "page_size": 1,
        "total": 2,
        "total_pages": 2,
        "has_previous": False,
        "has_next": True,
    }
    assert second_page["items"][0]["id"] == first_id
    assert second_page["items"][0]["payload"] == {"text": "สวัสดี", "metadata": None}
    assert second_page["items"][0]["display_name"] == "ผู้ดูแล"
    assert second_page["has_previous"] is True
    assert second_page["has_next"] is False


def test_invalid_stored_json_is_reported(repository):
    database, repo = repository
    database.execute(
        """INSERT INTO command_history
           (created_at_ms, source, status, payload_json)
           VALUES (:created_at_ms, :source, :status, :payload_json)""",
        {"created_at_ms": 1, "source": "test", "status": "BROKEN", "payload_json": "{"},
    )

    with pytest.raises(ValueError):
        repo.list_commands(None, page=1, page_size=50)
