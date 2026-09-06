import asyncio

import pytest

import main


def test_stop_requires_operator_before_publish(monkeypatch):
    published = []
    monkeypatch.setattr(main.mqtt_client, "publish", lambda *args, **kwargs: published.append(args))

    with pytest.raises(main.HTTPException) as error:
        asyncio.run(main.robot_stop("booky-1", actor=None))

    assert error.value.status_code == 403
    assert error.value.detail["code"] == "TARGET_UNAUTHORIZED"
    assert published == []


def test_authorized_stop_does_not_wait_for_audit_database(monkeypatch):
    published = []
    monkeypatch.setattr(
        main.mqtt_client,
        "publish",
        lambda topic, payload, qos: published.append((topic, payload, qos)),
    )
    monkeypatch.setattr(
        main,
        "record_command_history",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )

    result = asyncio.run(main.robot_stop(
        "booky-1",
        actor={"sub": "operator-1", "display_name": "Operator", "role": "operator"},
    ))

    assert published[0][0] == "zenbo/booky-1/cmd/stop"
    assert published[0][2] == 2
    assert result["status"] == "stopped"
    assert result["history_id"] is None
    assert result["audit_recorded"] is False
