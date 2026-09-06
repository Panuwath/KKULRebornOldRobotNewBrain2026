"""
Zenbo Scenario Builder API Router
Provides schema, draft management, and validation for user-created scenarios (L0-L5).
"""

import json
import re
import db
import time
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response


def _resolve_db_path(db_ref: Any) -> str:
    if callable(db_ref):
        return db_ref()
    return str(db_ref)


def init_builder_db(db_path_ref: Any, lock: Any) -> None:
    """Ensure created_by and source columns exist in scenario_definitions."""
    if db._backend == "pgsql":
        return
    try:
        db_path = _resolve_db_path(db_path_ref)
        with lock, db.connection(db_path) as conn:
            cols = [row[1] for row in conn.execute("PRAGMA table_info(scenario_definitions)").fetchall()]
            if cols:
                if "created_by" not in cols:
                    conn.execute("ALTER TABLE scenario_definitions ADD COLUMN created_by TEXT")
                if "source" not in cols:
                    conn.execute("ALTER TABLE scenario_definitions ADD COLUMN source TEXT DEFAULT 'system'")
    except Exception:
        pass


def build_router(
    ScenarioDefinitionRequest: Any,
    scenario_public_metadata: Callable[[str, Dict[str, Any]], Dict[str, Any]],
    get_scenario_definition: Callable[[str], Dict[str, Any]],
    import_scenario_definition: Callable[[Any], Dict[str, Any]],
    COMMAND_HISTORY_DB: Any,
    command_history_lock: Any,
    VOICE_PROFILES: Dict[str, Any],
    PRESENTATION_SPEECH_CUES: Dict[str, Any],
    TRUSTED_NAVIGATION_DISPLAY_URLS: tuple,
    SCENARIO_REGISTRY: Dict[str, Any],
) -> APIRouter:
    router = APIRouter(tags=["scenario-builder"])

    def require_web_session_role(*allowed_roles: str):
        async def dependency(request: Request) -> Dict[str, Any]:
            user = getattr(request.state, "user", None)
            import os
            if not user and os.getenv("TEST_ROLE_HEADER_ENABLED") == "1":
                role = request.headers.get("x-test-role")
                if role:
                    user = {"sub": "test_user_1", "role": role}
            if not user or not isinstance(user, dict):
                raise HTTPException(
                    status_code=401,
                    detail={"code": "LOGIN_REQUIRED", "message": "Sign in required to manage scenario drafts"},
                )
            role = user.get("role", "viewer")
            if role not in allowed_roles:
                raise HTTPException(
                    status_code=403,
                    detail={"code": "INSUFFICIENT_ROLE", "message": f"Role '{role}' is not authorized for this operation"},
                )
            return user

        return dependency

    @router.get("/api/v1/scenario-builder/schema")
    async def get_builder_schema() -> Dict[str, Any]:
        voices = [{"id": k, "label": v.get("name", k)} for k, v in VOICE_PROFILES.items()]
        faces = [
            {
                "id": k,
                "face_description": v.get("face_description", ""),
                "gesture_description": v.get("gesture_description", ""),
            }
            for k, v in PRESENTATION_SPEECH_CUES.items()
        ]
        return {
            "voice_profiles": voices,
            "faces": faces,
            "wheel_light_modes": ["breathing", "blinking", "marquee", "static", "off", "rainbow"],
            "vision_actions": ["detect_face", "detect_person", "gesture_point"],
            "trusted_display_urls": list(TRUSTED_NAVIGATION_DISPLAY_URLS),
            "limits": {
                "text_max": 1000,
                "steps_min": 1,
                "steps_max": 8,
                "outcome_min": 1,
                "outcome_max": 4,
                "head": {"yaw": [-45, 45], "pitch": [-15, 55], "speed": [1, 5], "delay_ms_max": 10000},
                "gate": {"interval_ms": [250, 5000], "timeout_ms": [3000, 30000]},
                "risk_levels_allowed": ["L0", "L1", "L2", "L3", "L4", "L5"],
                "scenario_id_pattern": "^user-[a-z0-9][a-z0-9_-]*$",
            },
        }

    @router.post("/api/v1/scenario-drafts", status_code=201)
    async def save_scenario_draft(
        req: ScenarioDefinitionRequest,
        user: Dict[str, Any] = Depends(require_web_session_role("operator", "admin")),
    ) -> Dict[str, Any]:
        # Validate ID pattern
        if not re.fullmatch(r"^user-[a-z0-9][a-z0-9_-]*$", req.scenario_id):
            raise HTTPException(
                status_code=409,
                detail={"code": "DRAFT_ID_RESERVED", "message": "Scenario ID must start with 'user-' and contain lowercase alphanumeric, dash, or underscore"},
            )

        # Enforce Risk Level boundary (L0 - L5 only)
        if req.risk_level not in ["L0", "L1", "L2", "L3", "L4", "L5"]:
            raise HTTPException(
                status_code=422,
                detail={"code": "DRAFT_RISK_LEVEL_NOT_ALLOWED", "message": f"Risk level '{req.risk_level}' is not allowed in Builder drafts (max L5)"},
            )

        # Import via standard definition workflow
        metadata = import_scenario_definition(req)
        init_builder_db(COMMAND_HISTORY_DB, command_history_lock)

        # Update metadata attribution in sqlite
        user_id = user.get("sub") or user.get("user_id") or user.get("username") or "operator"
        now = int(time.time() * 1000)
        db_path = _resolve_db_path(COMMAND_HISTORY_DB)
        with command_history_lock, db.connection(db_path) as conn:
            conn.execute(
                "UPDATE scenario_definitions SET created_by = ?, source = 'builder', updated_at_ms = ? WHERE scenario_id = ?",
                (user_id, now, req.scenario_id),
            )

        metadata["created_by"] = user_id
        metadata["source"] = "builder"
        metadata["updated_at_ms"] = now
        return metadata

    @router.get("/api/v1/scenario-drafts")
    async def list_scenario_drafts(
        user: Dict[str, Any] = Depends(require_web_session_role("operator", "admin")),
    ) -> Dict[str, Any]:
        init_builder_db(COMMAND_HISTORY_DB, command_history_lock)
        db_path = _resolve_db_path(COMMAND_HISTORY_DB)
        with command_history_lock, db.connection(db_path) as conn:
            rows = conn.execute(
                """SELECT scenario_id, version, title, description, risk_level, confirmation,
                          required_capabilities_json, updated_at_ms, created_by, source
                   FROM scenario_definitions
                   WHERE source = 'builder' OR scenario_id LIKE 'user-%'
                   ORDER BY updated_at_ms DESC"""
            ).fetchall()

        drafts = []
        for r in rows:
            drafts.append({
                "id": r[0],
                "version": r[1],
                "title": r[2],
                "description": r[3],
                "risk_level": r[4],
                "confirmation": r[5],
                "required_capabilities": json.loads(r[6]) if r[6] else [],
                "updated_at_ms": r[7],
                "created_by": r[8],
                "source": r[9] or "builder",
            })
        return {"drafts": drafts}

    @router.delete("/api/v1/scenario-drafts/{scenario_id}", status_code=204)
    async def delete_scenario_draft(
        scenario_id: str,
        user: Dict[str, Any] = Depends(require_web_session_role("admin")),
    ) -> Response:
        if scenario_id in SCENARIO_REGISTRY:
            raise HTTPException(
                status_code=409,
                detail={"code": "BUILTIN_SCENARIO_IMMUTABLE", "message": "Cannot delete built-in scenarios"},
            )

        db_path = _resolve_db_path(COMMAND_HISTORY_DB)
        with command_history_lock, db.connection(db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM scenario_definitions WHERE scenario_id = ? AND (source = 'builder' OR scenario_id LIKE 'user-%')",
                (scenario_id,),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Draft scenario not found")

        return Response(status_code=204)

    return router
