from __future__ import annotations

import json
from typing import Any, Dict, Optional

import db


def trace_command(command_id: str, robot_slug: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Return the latest history record matching a command_id in the payload.

    Works on both SQLite and PostgreSQL.  This is a gateway audit trail, not a
    guarantee of physical completion.
    """
    if db._backend == "pgsql":
        condition = "payload_json ->> 'command_id' = :command_id"
    else:
        condition = "json_extract(payload_json, '$.command_id') = :command_id"

    params: Dict[str, Any] = {"command_id": command_id}
    where = ""
    if robot_slug:
        where = " AND robot_slug = :robot_slug"
        params["robot_slug"] = robot_slug

    row = db.fetchone(
        f"SELECT id, created_at_ms, robot_slug, source, status, accepted_latency_ms, "
        f"payload_json, user_id, display_name FROM command_history "
        f"WHERE {condition}{where} ORDER BY id DESC LIMIT 1",
        params,
    )
    if row is None:
        return None

    payload = row["payload_json"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return {
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
    }
