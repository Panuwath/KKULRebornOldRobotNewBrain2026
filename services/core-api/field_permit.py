from __future__ import annotations

import json
import secrets
import time
from typing import Any, Dict, Optional

import db


def issue(
    robot_slug: str,
    operator_sub: str,
    level_max: int = 3,
    ttl_seconds: int = 3600,
    attestation: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Issue a time-boxed field permit for supervised physical calibration."""
    if type(level_max) is not int or not 1 <= level_max <= 7:
        raise ValueError("level_max must be between 1 and 7")
    if not isinstance(robot_slug, str) or not robot_slug.strip():
        raise ValueError("robot_slug is required")
    if not isinstance(operator_sub, str) or not operator_sub.strip():
        raise ValueError("operator_sub is required")
    if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 86400:
        raise ValueError("ttl_seconds must be between 1 and 86400")
    permit_id = secrets.token_urlsafe(32)
    now_ms = int(time.time() * 1000)
    expires_at_ms = now_ms + (ttl_seconds * 1000)
    db.execute(
        """INSERT INTO field_permits
           (permit_id, robot_slug, operator_sub, level_max, issued_at_ms, expires_at_ms, attestation_json)
           VALUES (:permit_id, :robot_slug, :operator_sub, :level_max, :issued_at_ms, :expires_at_ms, :attestation_json)""",
        {
            "permit_id": permit_id,
            "robot_slug": robot_slug,
            "operator_sub": operator_sub,
            "level_max": level_max,
            "issued_at_ms": now_ms,
            "expires_at_ms": expires_at_ms,
            "attestation_json": json.dumps(attestation or {}, ensure_ascii=False, separators=(",", ":")),
        },
        returning_id=True,
    )
    return {
        "permit_id": permit_id,
        "robot_slug": robot_slug,
        "operator_sub": operator_sub,
        "level_max": level_max,
        "issued_at_ms": now_ms,
        "expires_at_ms": expires_at_ms,
    }


def get_active(permit_id: str) -> Optional[Dict[str, Any]]:
    """Return the permit if it is active and not expired; otherwise None."""
    now_ms = int(time.time() * 1000)
    row = db.fetchone(
        """SELECT id, permit_id, robot_slug, operator_sub, level_max, issued_at_ms, expires_at_ms, attestation_json
           FROM field_permits
           WHERE permit_id = :permit_id AND revoked_at_ms IS NULL""",
        {"permit_id": permit_id},
    )
    if row is None or int(row["expires_at_ms"]) <= now_ms:
        return None
    attestation = row["attestation_json"]
    if isinstance(attestation, str):
        attestation = json.loads(attestation)
    return {
        "permit_id": row["permit_id"],
        "robot_slug": row["robot_slug"],
        "operator_sub": row["operator_sub"],
        "level_max": row["level_max"],
        "issued_at_ms": row["issued_at_ms"],
        "expires_at_ms": row["expires_at_ms"],
        "attestation": attestation,
    }


def revoke(permit_id: str) -> bool:
    """Mark a permit as revoked. Returns True if a matching row was found."""
    now_ms = int(time.time() * 1000)
    cursor = db.execute(
        "UPDATE field_permits SET revoked_at_ms = :now_ms WHERE permit_id = :permit_id AND revoked_at_ms IS NULL",
        {"now_ms": now_ms, "permit_id": permit_id},
    )
    # db.execute returns lastrowid for SQLite; for PostgreSQL the raw cursor
    # is not exposed. The adapter does not expose rowcount directly, so we
    # verify with a fetch instead.
    return db.fetchone(
        "SELECT 1 AS found FROM field_permits WHERE permit_id = :permit_id AND revoked_at_ms = :now_ms",
        {"permit_id": permit_id, "now_ms": now_ms},
    ) is not None
