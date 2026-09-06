from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict

from motion_contract import RelativeMotionRequest, ServerMotionPolicy, evaluate_relative_motion


@dataclass(frozen=True)
class MotionGateError(Exception):
    status_code: int
    code: str
    message: str


def dispatch_relative_motion(
    robot_slug: str,
    request: RelativeMotionRequest,
    actor: Dict[str, Any] | None,
    robot: Dict[str, Any] | None,
    permit: Dict[str, Any] | None,
    policy: ServerMotionPolicy,
    publisher: Callable[[str, str, int], Any],
    now_ms: int,
    feature_enabled: bool,
    heartbeat_ttl_ms: int = 10_000,
) -> Dict[str, Any]:
    if not feature_enabled:
        raise MotionGateError(409, "RELATIVE_MOTION_DISABLED", "Relative motion is disabled")
    if not actor or str(actor.get("role", "")).lower() not in {"admin", "operator"}:
        raise MotionGateError(403, "TARGET_UNAUTHORIZED", "Operator authorization is required")
    if not robot or robot.get("robot_slug") != robot_slug:
        raise MotionGateError(409, "ROBOT_OFFLINE", "Target robot is offline")
    last_seen_ms = int(float(robot.get("last_seen", 0)) * 1000)
    if last_seen_ms <= 0 or now_ms - last_seen_ms > heartbeat_ttl_ms:
        raise MotionGateError(409, "STALE_HEARTBEAT", "Target heartbeat is stale")
    capability = (robot.get("motion") or {}).get("body_relative")
    if not isinstance(capability, dict) or capability.get("supported") is not True:
        raise MotionGateError(409, "CAPABILITY_MISSING", "Relative body capability is unavailable")
    if robot.get("robot_api_ready") is not True:
        raise MotionGateError(409, "ROBOT_API_NOT_READY", "Robot API is not ready")
    if not permit or permit.get("state") != "READY" or permit.get("robot_slug") != robot_slug:
        raise MotionGateError(409, "OPERATION_PERMIT_REQUIRED", "A matching operation permit is required")

    capability_cap = capability.get("policy_max_speed_level")
    if not isinstance(capability_cap, int) or capability_cap < 1:
        raise MotionGateError(409, "CAPABILITY_POLICY_MISSING", "Capability policy cap is unavailable")
    heartbeat_max_speed = capability.get("max_body_speed")
    heartbeat_max_distance = capability.get("max_distance_m")
    heartbeat_auto_stop = capability.get("auto_stop_ms")
    if not isinstance(heartbeat_max_speed, (int, float)) or heartbeat_max_speed < 1:
        raise MotionGateError(409, "CAPABILITY_LIMITS_MISSING", "Heartbeat max body speed is unavailable")
    if not isinstance(heartbeat_max_distance, (int, float)) or heartbeat_max_distance <= 0:
        raise MotionGateError(409, "CAPABILITY_LIMITS_MISSING", "Heartbeat max distance is unavailable")
    if not isinstance(heartbeat_auto_stop, (int, float)) or heartbeat_auto_stop <= 0:
        raise MotionGateError(409, "CAPABILITY_LIMITS_MISSING", "Heartbeat auto-stop is unavailable")
    effective_policy = policy.model_copy(
        update={
            "max_body_speed_level": min(policy.max_body_speed_level, capability_cap, int(heartbeat_max_speed)),
            "max_distance_m": round(min(policy.max_distance_m, float(heartbeat_max_distance)), 6),
            "hard_stop_after_ms": min(policy.hard_stop_after_ms, int(heartbeat_auto_stop)),
        }
    )
    deadline_ms = min(request.expires_at_ms, int(permit["expires_at_ms"]), now_ms + effective_policy.hard_stop_after_ms)
    authoritative_request = request.model_copy(
        update={"issued_at_ms": now_ms, "expires_at_ms": deadline_ms}
    )
    if deadline_ms <= now_ms:
        _, acknowledgement = evaluate_relative_motion(authoritative_request, effective_policy, now_ms)
        return {"published": False, "acknowledgement": acknowledgement.model_dump(mode="json")}

    envelope, acknowledgement = evaluate_relative_motion(authoritative_request, effective_policy, now_ms)
    if envelope is None:
        return {"published": False, "acknowledgement": acknowledgement.model_dump(mode="json")}
    payload = envelope.model_dump_json()
    publisher(f"zenbo/{robot_slug}/cmd/interact", payload, 1)
    return {
        "published": True,
        "topic": f"zenbo/{robot_slug}/cmd/interact",
        "envelope": envelope.model_dump(mode="json"),
        "acknowledgement": acknowledgement.model_dump(mode="json"),
    }
