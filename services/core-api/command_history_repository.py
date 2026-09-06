from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

import db


def append_command(
    robot_slug: Optional[str],
    source: Optional[str],
    status: str,
    payload: Dict[str, Any],
    accepted_latency_ms: Optional[int] = None,
    user_id: Optional[str] = None,
    display_name: Optional[str] = None,
    created_at_ms: Optional[int] = None,
) -> int:
    history_id = db.execute(
        """INSERT INTO command_history
           (created_at_ms, robot_slug, source, status, accepted_latency_ms, payload_json, user_id, display_name)
           VALUES (:created_at_ms, :robot_slug, :source, :status, :accepted_latency_ms, :payload_json, :user_id, :display_name)""",
        {
            "created_at_ms": created_at_ms if created_at_ms is not None else int(time.time() * 1000),
            "robot_slug": robot_slug,
            "source": (source or "liff").strip()[:40],
            "status": status,
            "accepted_latency_ms": accepted_latency_ms,
            "payload_json": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            "user_id": (user_id or "").strip()[:64] or None,
            "display_name": (display_name or "").strip()[:128] or None,
        },
        returning_id=True,
    )
    if history_id is None:
        raise RuntimeError("command history insert did not return an id")
    return history_id


def list_commands(robot_slug: Optional[str], page: int, page_size: int) -> Dict[str, Any]:
    where = " WHERE robot_slug = :robot_slug" if robot_slug else ""
    params: Dict[str, Any] = {"limit": page_size, "offset": (page - 1) * page_size}
    if robot_slug:
        params["robot_slug"] = robot_slug
    count_params = {"robot_slug": robot_slug} if robot_slug else None
    total_row = db.fetchone(f"SELECT COUNT(*) AS total FROM command_history{where}", count_params)
    total = int(total_row["total"] if total_row else 0)
    rows = db.fetchall(
        "SELECT id, created_at_ms, robot_slug, source, status, accepted_latency_ms, "
        f"payload_json, user_id, display_name FROM command_history{where} "
        "ORDER BY id DESC LIMIT :limit OFFSET :offset",
        params,
    )
    items = []
    for row in rows:
        payload = row["payload_json"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        items.append({
            "id": row["id"],
            "created_at_ms": row["created_at_ms"],
            "robot_slug": row["robot_slug"],
            "source": row["source"],
            "status": row["status"],
            "accepted_latency_ms": row["accepted_latency_ms"],
            "payload": payload,
            "user_id": row["user_id"],
            "display_name": row["display_name"],
        })
    total_pages = max(1, (total + page_size - 1) // page_size)
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "has_previous": page > 1,
        "has_next": page < total_pages,
    }
