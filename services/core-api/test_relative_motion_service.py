import json

import pytest

from motion_contract import RelativeMotionRequest, ServerMotionPolicy
from relative_motion_service import MotionGateError, dispatch_relative_motion

NOW = 10_000


def request(speed=3, expires_at_ms=20_000):
    return RelativeMotionRequest.model_validate({
        "command_id": "018f47d2-f228-7de0-b025-4ef6a7e416f8",
        "source_session_id": "018f47d2-f228-7de0-b025-4ef6a7e416f9",
        "source_seq": 1,
        "issued_at_ms": 9_000,
        "expires_at_ms": expires_at_ms,
        "motion_request": {
            "control_mode": "RELATIVE_BODY",
            "x_m": 0.1,
            "y_m": 0,
            "theta_deg": 0,
            "requested_speed_level": speed,
        },
    })


def policy():
    return ServerMotionPolicy(
        policy_version="server-v1",
        max_body_speed_level=5,
        max_distance_m=0.15,
        hard_stop_after_ms=1_500,
    )


def robot(last_seen_ms=NOW, cap=4):
    return {
        "robot_slug": "booky-1",
        "last_seen": last_seen_ms / 1000,
        "robot_api_ready": True,
        "motion": {"body_relative": {
            "supported": True,
            "policy_max_speed_level": cap,
            "max_body_speed": 7,
            "max_distance_m": 0.15,
            "auto_stop_ms": 1_500,
        }},
    }


def permit(expires_at_ms=30_000):
    return {"state": "READY", "robot_slug": "booky-1", "expires_at_ms": expires_at_ms}


def dispatch(**overrides):
    published = []
    arguments = {
        "robot_slug": "booky-1",
        "request": request(),
        "actor": {"sub": "operator-1", "role": "operator"},
        "robot": robot(),
        "permit": permit(),
        "policy": policy(),
        "publisher": lambda topic, payload, qos: published.append((topic, json.loads(payload), qos)),
        "now_ms": NOW,
        "feature_enabled": True,
    }
    arguments.update(overrides)
    return dispatch_relative_motion(**arguments), published


def test_valid_dispatch_uses_server_cap_and_hard_deadline():
    result, published = dispatch()

    assert result["published"] is True
    assert result["envelope"]["issued_at_ms"] == NOW
    assert result["envelope"]["expires_at_ms"] == NOW + 1_500
    assert result["envelope"]["policy"]["max_body_speed_level"] == 4
    assert published[0][0] == "zenbo/booky-1/cmd/interact"
    assert published[0][1] == result["envelope"]
    assert published[0][2] == 1


@pytest.mark.parametrize("overrides,code", [
    ({"feature_enabled": False}, "RELATIVE_MOTION_DISABLED"),
    ({"actor": None}, "TARGET_UNAUTHORIZED"),
    ({"robot": None}, "ROBOT_OFFLINE"),
    ({"robot": robot(last_seen_ms=0)}, "STALE_HEARTBEAT"),
    ({"robot": {**robot(), "motion": {}}}, "CAPABILITY_MISSING"),
    ({"robot": {**robot(), "robot_api_ready": False}}, "ROBOT_API_NOT_READY"),
    ({"permit": None}, "OPERATION_PERMIT_REQUIRED"),
    ({"permit": {**permit(), "robot_slug": "other"}}, "OPERATION_PERMIT_REQUIRED"),
])
def test_gate_rejections_never_publish(overrides, code):
    with pytest.raises(MotionGateError) as error:
        dispatch(**overrides)

    assert error.value.code == code


def test_over_cap_rejection_never_publishes():
    result, published = dispatch(request=request(speed=5))

    assert result["published"] is False
    assert result["acknowledgement"]["reject_reason"] == "SPEED_EXCEEDS_POLICY"
    assert published == []


def test_expired_permit_never_publishes():
    result, published = dispatch(permit=permit(expires_at_ms=NOW))

    assert result["published"] is False
    assert result["acknowledgement"]["reject_reason"] == "COMMAND_EXPIRED"
    assert published == []


@pytest.mark.parametrize("last_seen", [True, "10", float("nan"), float("inf"), 11])
def test_invalid_or_future_heartbeat_fails_closed(last_seen):
    with pytest.raises(MotionGateError) as error:
        dispatch(robot={**robot(), "last_seen": last_seen})
    assert error.value.code == "STALE_HEARTBEAT"


@pytest.mark.parametrize("key,value", [
    ("max_body_speed", True), ("max_body_speed", 7.5),
    ("max_distance_m", float("nan")), ("max_distance_m", True),
    ("auto_stop_ms", True), ("auto_stop_ms", float("inf")),
])
def test_invalid_heartbeat_limits_never_publish(key, value):
    target = robot()
    target["motion"]["body_relative"][key] = value
    with pytest.raises(MotionGateError) as error:
        dispatch(robot=target)
    assert error.value.code == "CAPABILITY_LIMITS_MISSING"
