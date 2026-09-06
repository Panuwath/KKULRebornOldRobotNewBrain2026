from __future__ import annotations

import json
from typing import Any, Dict, Optional

import db


def trace_command(command_id: str, robot_slug: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Return latest receipt and up to 100 events, ordered by gateway history id.

    Accept the existing top-level, relative gateway envelope, and APK ACK shapes.
    These are recorded observations, never a physical completion guarantee.
    """
    if db._backend == "pgsql":
        command_expression = "COALESCE(payload_json::jsonb ->> 'command_id', " \
            "payload_json::jsonb -> 'acknowledgement' ->> 'command_id', " \
            "payload_json::jsonb -> 'envelope' ->> 'command_id')"
    else:
        command_expression = "COALESCE(json_extract(payload_json, '$.command_id'), " \
            "json_extract(payload_json, '$.acknowledgement.command_id'), " \
            "json_extract(payload_json, '$.envelope.command_id'))"
    condition = f"{command_expression} = :command_id"

    params: Dict[str, Any] = {"command_id": command_id}
    where = ""
    if robot_slug:
        where = " AND robot_slug = :robot_slug"
        params["robot_slug"] = robot_slug

    rows = db.fetchall(
        f"SELECT id, created_at_ms, robot_slug, source, status, accepted_latency_ms, "
        f"payload_json, user_id, display_name FROM command_history "
        f"WHERE {condition}{where} ORDER BY id DESC LIMIT 101",
        params,
    )
    if not rows:
        return None

    events = []
    for row in reversed(rows[:100]):
        payload = row["payload_json"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        events.append({
            "command_id": command_id,
            "history_id": row["id"],
            "robot_slug": row["robot_slug"],
            "source": row["source"],
            "status": row["status"],
            "created_at_ms": row["created_at_ms"],
            "accepted_latency_ms": row["accepted_latency_ms"],
            "payload": payload,
            "user_id": row["user_id"],
            "display_name": row["display_name"],
        })
    return {
        **events[-1],
        "events": events,
        "events_truncated": len(rows) > 100,
        "event_order": "GATEWAY_RECEIPT",
        "physical_motion_verified": False,
    }
