import time

import pytest

from field_calibration_check import CalibrationStatus, check


def _robot(**overrides):
    base = {
        "robot_slug": "booky-cal",
        "version_name": "1.9.48",
        "last_seen": time.time(),
        "robot_api_ready": True,
        "apk_sha256": "a1b2c3",
        "safety_guard": {
            "collision_guard_enabled": True,
            "fall_guard_enabled": True,
            "base_motion_enabled": False,
        },
        "safety_monitor": {
            "enabled": True,
            "active": True,
            "required_sensor_coverage": True,
        },
        "motion": {
            "body_relative": {
                "supported": True,
                "speed_levels": [1, 2, 3, 4, 5, 6, 7],
                "max_distance_m": 0.15,
                "max_body_speed": 7,
                "auto_stop_ms": 1500,
            }
        },
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and key in base and isinstance(base[key], dict):
            base[key].update(value)
        else:
            base[key] = value
    return base


def test_ready_robot_passes():
    status = check(_robot())
    assert status.ready is True
    assert status.blockers == []


def test_missing_body_limits_blocks():
    status = check(_robot(motion={"body_relative": {"supported": True}}))
    assert status.ready is False
    assert any("BODY_LIMIT" in b for b in status.blockers)


def test_base_motion_unlocked_blocks():
    status = check(_robot(safety_guard={"base_motion_enabled": True}))
    assert status.ready is False
    assert any("BASE_MOTION" in b for b in status.blockers)


def test_safety_monitor_missing_sensor_blocks():
    status = check(_robot(safety_monitor={"required_sensor_coverage": False}))
    assert status.ready is False
    assert "REQUIRED_SENSOR_COVERAGE_MISSING" in status.blockers


def test_apk_hash_mismatch_blocks():
    status = check(_robot(), expected_apk_sha256="different")
    assert status.ready is False
    assert "APK_HASH_MISMATCH" in status.blockers
