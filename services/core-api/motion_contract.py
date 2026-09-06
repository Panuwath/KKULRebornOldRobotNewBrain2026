from __future__ import annotations

import math
from enum import Enum
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RejectReason(str, Enum):
    COMMAND_EXPIRED = "COMMAND_EXPIRED"
    SPEED_EXCEEDS_POLICY = "SPEED_EXCEEDS_POLICY"
    DISTANCE_EXCEEDS_POLICY = "DISTANCE_EXCEEDS_POLICY"
    TARGET_UNAUTHORIZED = "TARGET_UNAUTHORIZED"


class MotionRequestData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    control_mode: Literal["RELATIVE_BODY"]
    x_m: float
    y_m: float
    theta_deg: float
    requested_speed_level: int = Field(strict=True, ge=1, le=7)

    @field_validator("x_m", "y_m", "theta_deg")
    @classmethod
    def finite_coordinates(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("motion coordinates must be finite")
        return value


class RelativeMotionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    source_session_id: UUID
    source_seq: int = Field(strict=True, ge=0)
    issued_at_ms: int = Field(strict=True, ge=0)
    expires_at_ms: int = Field(strict=True, ge=0)
    motion_request: MotionRequestData

    @model_validator(mode="after")
    def expiry_follows_issue(self) -> "RelativeMotionRequest":
        if self.expires_at_ms <= self.issued_at_ms:
            raise ValueError("expires_at_ms must be after issued_at_ms")
        return self


class ServerMotionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_version: str = Field(min_length=1, max_length=100)
    max_body_speed_level: int = Field(strict=True, ge=1, le=7)
    max_distance_m: float = Field(gt=0)
    hard_stop_after_ms: int = Field(strict=True, gt=0)

    @field_validator("max_distance_m")
    @classmethod
    def finite_distance(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("max_distance_m must be finite")
        return value


class MotionEnvelopeData(MotionRequestData):
    pass


class RelativeMotionEnvelope(BaseModel):
    command_id: UUID
    source_session_id: UUID
    source_seq: int
    issued_at_ms: int
    expires_at_ms: int
    motion: MotionEnvelopeData
    policy: ServerMotionPolicy


class MotionAcknowledgement(BaseModel):
    command_id: UUID
    control_mode: Literal["RELATIVE_BODY"] = "RELATIVE_BODY"
    state: Literal["ACCEPTED", "REJECTED"]
    requested_speed_level: int
    policy_max_speed_level: int
    effective_speed_level: Optional[int]
    received_at_ms: int
    sdk_applied_at_ms: Optional[int] = None
    reject_reason: Optional[RejectReason] = None


class StopRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    target_robot_slug: str = Field(min_length=1, max_length=120)


def authorize_stop(request: StopRequest, target_authorized: bool) -> Optional[RejectReason]:
    return None if target_authorized else RejectReason.TARGET_UNAUTHORIZED


def evaluate_relative_motion(
    request: RelativeMotionRequest,
    policy: ServerMotionPolicy,
    now_ms: int,
) -> tuple[Optional[RelativeMotionEnvelope], MotionAcknowledgement]:
    requested = request.motion_request.requested_speed_level
    reason = None
    if now_ms >= request.expires_at_ms:
        reason = RejectReason.COMMAND_EXPIRED
    elif requested > policy.max_body_speed_level:
        reason = RejectReason.SPEED_EXCEEDS_POLICY
    elif math.hypot(request.motion_request.x_m, request.motion_request.y_m) > policy.max_distance_m:
        reason = RejectReason.DISTANCE_EXCEEDS_POLICY

    acknowledgement = MotionAcknowledgement(
        command_id=request.command_id,
        state="REJECTED" if reason else "ACCEPTED",
        requested_speed_level=requested,
        policy_max_speed_level=policy.max_body_speed_level,
        effective_speed_level=None if reason else requested,
        received_at_ms=now_ms,
        reject_reason=reason,
    )
    if reason:
        return None, acknowledgement

    envelope = RelativeMotionEnvelope(
        command_id=request.command_id,
        source_session_id=request.source_session_id,
        source_seq=request.source_seq,
        issued_at_ms=request.issued_at_ms,
        expires_at_ms=request.expires_at_ms,
        motion=MotionEnvelopeData(**request.motion_request.model_dump()),
        policy=policy,
    )
    return envelope, acknowledgement
