"""YouTube entertainment command validation shared by Core API endpoints."""
import json
import random
import re
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator


DEFAULT_DANCE_ACTION_IDS = [2, 3, 5, 11, 18, 22, 23, 44]


class YouTubeCommand(BaseModel):
    url: str = Field(..., min_length=12, max_length=2048)
    action: Optional[str] = "play"
    dance_action_ids: List[int] = Field(default_factory=list)
    loop_dance: bool = True
    duration_seconds: Optional[int] = Field(default=None, ge=1, le=3600)

    @field_validator("url")
    @classmethod
    def validate_youtube_url(cls, value: str) -> str:
        normalized = value.strip()
        parsed = urlparse(normalized)
        if parsed.scheme != "https":
            raise ValueError("YouTube URL must use HTTPS")
        host = (parsed.hostname or "").lower()
        if host not in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"}:
            raise ValueError("Only youtube.com or youtu.be URLs are supported")
        video_id = re.search(r"(?:[?&]v=|/embed/|/shorts/|youtu\.be/)([A-Za-z0-9_-]{6,})", normalized)
        if not video_id:
            raise ValueError("YouTube URL must identify one video (watch, short, embed, or youtu.be link)")
        return normalized

    @field_validator("action")
    @classmethod
    def validate_action(cls, value: Optional[str]) -> Optional[str]:
        if value not in {"play", "pause", "resume", "stop"}:
            raise ValueError("Unsupported YouTube action")
        return value

    @field_validator("dance_action_ids")
    @classmethod
    def validate_dance_actions(cls, values: List[int]) -> List[int]:
        if any(value not in DEFAULT_DANCE_ACTION_IDS for value in values):
            raise ValueError("Unsupported dance action ID")
        return values

    @model_validator(mode="after")
    def require_dance(self) -> "YouTubeCommand":
        if not self.loop_dance:
            raise ValueError("DANCE_REQUIRED")
        if not self.dance_action_ids:
            self.dance_action_ids = random.sample(DEFAULT_DANCE_ACTION_IDS, len(DEFAULT_DANCE_ACTION_IDS))
        return self


class EntertainmentRequest(BaseModel):
    url: str
    dance_action_ids: List[int] = Field(default_factory=list)
    duration_seconds: Optional[int] = None


def dispatch_entertainment(
    robot_slug: str,
    action: str,
    body: EntertainmentRequest,
    mqtt_client: Any,
    record_history: Callable[..., int],
    username: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate, publish, and audit one entertainment command."""
    command = YouTubeCommand(action=action, **body.model_dump())
    payload = command.model_dump()
    mqtt_client.publish(f"zenbo/{robot_slug}/cmd/youtube", json.dumps(payload), qos=1)
    history_id = record_history(
        robot_slug,
        "entertainment_api",
        "MQTT_PUBLISHED",
        payload,
        user_id=username,
        display_name=username,
    )
    return {"status": "dispatched", "robot_slug": robot_slug, "payload": payload, "history_id": history_id}
