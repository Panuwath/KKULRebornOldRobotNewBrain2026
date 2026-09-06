"""T4 offline vertical integration: Core relative motion with golden JSON.

Simulates the no-motion path:
  mock browser (golden JSON) -> Core contract/dispatch -> fake MQTT publisher

No real HTTP, MQTT broker, ADB, APK install, or RobotAPI call occurs.
The fake publisher is the only sink; rejected/invalid commands result in
exactly zero published envelopes.
"""

import json
from pathlib import Path

import pytest

from motion_contract import (
    RejectReason,
    RelativeMotionRequest,
    ServerMotionPolicy,
    StopRequest,
    authorize_stop,
    evaluate_relative_motion,
)
from relative_motion_service import MotionGateError, dispatch_relative_motion

GOLDEN = json.loads(
    (Path(__file__).parents[2] / "contracts" / "relative_motion_golden.json").read_text(encoding="utf-8")
)


def request(speed=None, x=None, y=None):
    payload = GOLDEN["valid"]["request"].copy()
    if speed is not None:
        payload["motion_request"] = {**payload["motion_request"], "requested_speed_level": speed}
    if x is not None or y is not None:
        m = payload["motion_request"].copy()
        if x is not None:
            m["x_m"] = x
        if y is not None:
            m["y_m"] = y
        payload["motion_request"] = m
    return RelativeMotionRequest.model_validate(payload)


def policy(max_speed=None, max_distance=None):
    payload = GOLDEN["valid"]["policy"].copy()
    if max_speed is not None:
        payload["max_body_speed_level"] = max_speed
    if max_distance is not None:
        payload["max_distance_m"] = max_distance
    return ServerMotionPolicy.model_validate(payload)


def robot(**overrides):
    base = {
        "robot_slug": "booky-1",
        "last_seen": 1.1,
        "robot_api_ready": True,
        "motion": {
            "body_relative": {
                "supported": True,
                "policy_max_speed_level": 4,
                "max_body_speed": 7,
                "max_distance_m": 0.15,
                "auto_stop_ms": 1_500,
            }
        },
    }
    base.update(overrides)
    return base


def dispatch(**overrides):
    published = []
    args = {
        "robot_slug": "booky-1",
        "request": request(),
        "actor": {"sub": "operator-1", "role": "operator"},
        "robot": robot(),
        "permit": {"state": "READY", "robot_slug": "booky-1", "expires_at_ms": 3_000},
        "policy": policy(),
        "publisher": lambda topic, payload, qos: published.append((topic, json.loads(payload), qos)),
        "now_ms": GOLDEN["valid"]["now_ms"],
        "feature_enabled": True,
    }
    args.update(overrides)
    return dispatch_relative_motion(**args), published


def test_golden_valid_contract_matches_core_evaluation():
    fixture = GOLDEN["valid"]
    req = RelativeMotionRequest.model_validate(fixture["request"])
    pol = ServerMotionPolicy.model_validate(fixture["policy"])
    envelope, acknowledgement = evaluate_relative_motion(req, pol, now_ms=fixture["now_ms"])

    assert envelope is not None
    assert envelope.model_dump(mode="json") == fixture["expected_envelope"]
    assert acknowledgement.state == fixture["expected_state"]


def test_golden_over_cap_rejected():
    fixture = GOLDEN["over_cap"]
    envelope, acknowledgement = evaluate_relative_motion(
        request(speed=fixture["requested_speed_level"]),
        policy(max_speed=fixture["policy_max_speed_level"]),
        now_ms=fixture["now_ms"],
    )

    assert envelope is None
    assert acknowledgement.state == fixture["expected_state"]
    assert acknowledgement.reject_reason == fixture["reject_reason"]
    assert acknowledgement.effective_speed_level is None


def test_golden_over_distance_rejected():
    fixture = GOLDEN["over_distance"]
    envelope, acknowledgement = evaluate_relative_motion(
        request(x=fixture["x_m"], y=fixture["y_m"]),
        policy(max_distance=fixture["max_distance_m"]),
        now_ms=GOLDEN["valid"]["now_ms"],
    )

    assert envelope is None
    assert acknowledgement.state == fixture["expected_state"]
    assert acknowledgement.reject_reason == fixture["reject_reason"]


def test_golden_expired_rejected():
    fixture = GOLDEN["expired"]
    envelope, acknowledgement = evaluate_relative_motion(
        request(),
        policy(),
        now_ms=fixture["now_ms"],
    )

    assert envelope is None
    assert acknowledgement.state == fixture["expected_state"]
    assert acknowledgement.reject_reason == fixture["reject_reason"]


def test_golden_unauthorized_stop_rejected():
    fixture = GOLDEN["unauthorized_stop"]
    stop = StopRequest.model_validate(fixture["request"])
    reason = authorize_stop(stop, target_authorized=fixture["target_authorized"])
    assert reason == RejectReason.TARGET_UNAUTHORIZED


def test_offline_dispatch_publishes_exactly_one_fake_envelope():
    result, published = dispatch()

    assert result["published"] is True
    assert len(published) == 1
    topic, envelope, qos = published[0]
    assert topic == "zenbo/booky-1/cmd/interact"
    assert qos == 1
    assert envelope["command_id"] == GOLDEN["valid"]["request"]["command_id"]
    assert envelope["motion"]["requested_speed_level"] == 3
    assert result["acknowledgement"]["state"] == "ACCEPTED"
    assert result["acknowledgement"]["effective_speed_level"] == 3


@pytest.mark.parametrize("overrides, code", [
    ({"feature_enabled": False}, "RELATIVE_MOTION_DISABLED"),
    ({"robot": None}, "ROBOT_OFFLINE"),
    ({"robot": robot(last_seen=0)}, "STALE_HEARTBEAT"),
    ({"robot": robot(robot_api_ready=False)}, "ROBOT_API_NOT_READY"),
    ({"robot": robot(motion={})}, "CAPABILITY_MISSING"),
    ({"permit": None}, "OPERATION_PERMIT_REQUIRED"),
    ({"permit": {"state": "READY", "robot_slug": "other", "expires_at_ms": 3_000}}, "OPERATION_PERMIT_REQUIRED"),
])
def test_offline_gate_rejections_never_publish(overrides, code):
    with pytest.raises(MotionGateError) as error:
        dispatch(**overrides)

    assert error.value.code == code


@pytest.mark.parametrize("overrides, code", [
    ({"request": request(speed=5)}, "SPEED_EXCEEDS_POLICY"),
    ({"request": request(x=0.16)}, "DISTANCE_EXCEEDS_POLICY"),
    ({"request": request(), "now_ms": 2_000}, "COMMAND_EXPIRED"),
])
def test_offline_policy_rejections_never_publish(overrides, code):
    result, published = dispatch(**overrides)

    assert result["published"] is False
    assert result["acknowledgement"]["reject_reason"] == code
    assert published == []
