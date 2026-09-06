"""T8 pre-flight checklist for supervised L1–L7 physical calibration.

This does not perform physical motion. It checks only the gateway-reported
preconditions that an operator must confirm before a field permit is issued.
"""
from __future__ import annotations

import time
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class CalibrationStatus:
    robot_slug: str
    ready: bool
    blockers: List[str]
    checked_at_ms: int


HEARTBEAT_TTL_SECONDS = 10


def _value(value: Any, expected: Any) -> bool:
    return type(value) is type(expected) and value == expected


def _positive_number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def check(robot: Dict[str, Any], expected_apk_sha256: Optional[str] = None) -> CalibrationStatus:
    """Return calibration readiness without claiming physical safety."""
    robot_slug = str(robot.get("robot_slug") or "unknown")
    blockers: List[str] = []
    now = time.time()

    last_seen = robot.get("last_seen")
    if (not _positive_number(last_seen) or last_seen > now
            or now - last_seen > HEARTBEAT_TTL_SECONDS):
        blockers.append("STALE_HEARTBEAT")

    if not _value(robot.get("robot_api_ready"), True):
        blockers.append("ROBOT_API_NOT_READY")

    if expected_apk_sha256:
        installed = str(robot.get("apk_sha256") or "")
        if installed != expected_apk_sha256:
            blockers.append("APK_HASH_MISMATCH")

    safety_guard = robot.get("safety_guard") if isinstance(robot.get("safety_guard"), dict) else {}
    if not _value(safety_guard.get("collision_guard_enabled"), True):
        blockers.append("COLLISION_GUARD_DISABLED")
    if not _value(safety_guard.get("fall_guard_enabled"), True):
        blockers.append("FALL_GUARD_DISABLED")
    if safety_guard.get("base_motion_enabled") is not False:
        blockers.append("BASE_MOTION_MUST_BE_LOCKED")

    safety_monitor = robot.get("safety_monitor") if isinstance(robot.get("safety_monitor"), dict) else {}
    if safety_monitor.get("enabled") is not True:
        blockers.append("SAFETY_MONITOR_DISABLED")
    if not _value(safety_monitor.get("active"), True):
        blockers.append("SAFETY_MONITOR_INACTIVE")
    if not _value(safety_monitor.get("required_sensor_coverage"), True):
        blockers.append("REQUIRED_SENSOR_COVERAGE_MISSING")

    motion = (robot.get("motion") or {}).get("body_relative") if isinstance(robot.get("motion"), dict) else None
    if not isinstance(motion, dict) or not _value(motion.get("supported"), True):
        blockers.append("BODY_RELATIVE_UNSUPPORTED")
    else:
        for key in ("max_distance_m", "max_body_speed", "auto_stop_ms"):
            value = motion.get(key)
            if not _positive_number(value):
                blockers.append(f"BODY_LIMIT_{key.upper()}_MISSING")
        speed = motion.get("max_body_speed")
        if type(speed) is not int or not 1 <= speed <= 7:
            blockers.append("BODY_SPEED_INVALID")

    version = str(robot.get("version_name") or "")
    if not version:
        blockers.append("APK_VERSION_UNKNOWN")

    return CalibrationStatus(
        robot_slug=robot_slug,
        ready=not blockers,
        blockers=blockers,
        checked_at_ms=int(now * 1000),
    )
