import json
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from motion_contract import (
    RejectReason,
    RelativeMotionRequest,
    ServerMotionPolicy,
    StopRequest,
    authorize_stop,
    evaluate_relative_motion,
)

COMMAND_ID = "018f47d2-f228-7de0-b025-4ef6a7e416f8"
SESSION_ID = "018f47d2-f228-7de0-b025-4ef6a7e416f9"
GOLDEN = json.loads(
    (Path(__file__).parents[2] / "contracts" / "relative_motion_golden.json").read_text(encoding="utf-8")
)


def request_payload(speed_level=3):
    return {
        "command_id": COMMAND_ID,
        "source_session_id": SESSION_ID,
        "source_seq": 12,
        "issued_at_ms": 1_000,
        "expires_at_ms": 2_000,
        "motion_request": {
            "control_mode": "RELATIVE_BODY",
            "x_m": 0.1,
            "y_m": 0.0,
            "theta_deg": 0.0,
            "requested_speed_level": speed_level,
        },
    }


def policy_payload(max_speed=4):
    return {
        "policy_version": "test-policy-v1",
        "max_body_speed_level": max_speed,
        "max_distance_m": 0.15,
        "hard_stop_after_ms": 1_500,
    }


def test_valid_relative_motion_golden_json():
    fixture = GOLDEN["valid"]
    request = RelativeMotionRequest.model_validate(fixture["request"])
    envelope, acknowledgement = evaluate_relative_motion(
        request, ServerMotionPolicy.model_validate(fixture["policy"]), now_ms=fixture["now_ms"]
    )

    assert envelope is not None
    assert envelope.model_dump(mode="json") == fixture["expected_envelope"]
    assert acknowledgement.model_dump(mode="json") == {
        "command_id": COMMAND_ID,
        "control_mode": "RELATIVE_BODY",
        "state": "ACCEPTED",
        "requested_speed_level": 3,
        "policy_max_speed_level": 4,
        "effective_speed_level": 3,
        "received_at_ms": 1_100,
        "sdk_applied_at_ms": None,
        "reject_reason": None,
    }


def test_expired_command_is_rejected():
    request = RelativeMotionRequest.model_validate(request_payload())
    envelope, acknowledgement = evaluate_relative_motion(
        request, ServerMotionPolicy.model_validate(policy_payload()), now_ms=2_000
    )

    assert envelope is None
    assert acknowledgement.state == "REJECTED"
    assert acknowledgement.effective_speed_level is None
    assert acknowledgement.reject_reason == RejectReason.COMMAND_EXPIRED
    assert acknowledgement.sdk_applied_at_ms is None


def test_over_cap_command_is_rejected_without_effective_speed():
    request = RelativeMotionRequest.model_validate(request_payload(speed_level=5))
    envelope, acknowledgement = evaluate_relative_motion(
        request, ServerMotionPolicy.model_validate(policy_payload(max_speed=4)), now_ms=1_100
    )

    assert envelope is None
    assert acknowledgement.model_dump(mode="json") == {
        "command_id": COMMAND_ID,
        "control_mode": "RELATIVE_BODY",
        "state": "REJECTED",
        "requested_speed_level": 5,
        "policy_max_speed_level": 4,
        "effective_speed_level": None,
        "received_at_ms": 1_100,
        "sdk_applied_at_ms": None,
        "reject_reason": "SPEED_EXCEEDS_POLICY",
    }


def test_over_distance_command_is_rejected():
    fixture = GOLDEN["over_distance"]
    payload = request_payload()
    payload["motion_request"]["x_m"] = fixture["x_m"]
    payload["motion_request"]["y_m"] = fixture["y_m"]
    policy = policy_payload()
    policy["max_distance_m"] = fixture["max_distance_m"]

    envelope, acknowledgement = evaluate_relative_motion(
        RelativeMotionRequest.model_validate(payload),
        ServerMotionPolicy.model_validate(policy),
        now_ms=1_100,
    )

    assert envelope is None
    assert acknowledgement.reject_reason == RejectReason.DISTANCE_EXCEEDS_POLICY
    assert acknowledgement.effective_speed_level is None


def test_stop_keeps_target_authorization():
    request = StopRequest(command_id=UUID(COMMAND_ID), target_robot_slug="booky-1")

    assert authorize_stop(request, target_authorized=False) == RejectReason.TARGET_UNAUTHORIZED
    assert authorize_stop(request, target_authorized=True) is None


@pytest.mark.parametrize("speed_level", [0, 8, 1.5, "3"])
def test_body_speed_requires_strict_integer_level_1_to_7(speed_level):
    with pytest.raises(ValidationError):
        RelativeMotionRequest.model_validate(request_payload(speed_level=speed_level))


def test_client_cannot_supply_policy_fields():
    payload = request_payload()
    payload["policy"] = policy_payload()

    with pytest.raises(ValidationError):
        RelativeMotionRequest.model_validate(payload)
