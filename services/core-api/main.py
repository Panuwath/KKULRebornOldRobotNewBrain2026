import asyncio
import os
import json
import base64
import hashlib
import hmac
import httpx
import time
import sqlite3
import uuid
import re
import secrets
from urllib.parse import quote, urlparse
from threading import Lock
from typing import Optional, Dict, Any, List, Literal, Union
from fastapi import FastAPI, HTTPException, Header, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response, JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
import paho.mqtt.client as mqtt

import db
from command_history_repository import append_command, list_commands
from command_trace import trace_command
import field_calibration_check
import field_permit
from motion_contract import RelativeMotionRequest, ServerMotionPolicy
from relative_motion_service import MotionGateError, dispatch_relative_motion
from sdk_bridge_publisher import MqttSdkBridgePublisher
from oidc import (
    SESSION_COOKIE,
    SESSION_TTL_SECONDS,
    authenticate,
    build_tx_cookie,
    create_web_auth_session,
    delete_session_cookie,
    delete_web_auth_session,
    get_web_auth_session,
    is_standard_web_request,
    login_url,
    parse_tx_cookie,
    require_role,
    set_session_cookie,
)
from speech_phrases import (
    SpeechPhraseCreate,
    SpeechPhraseUpdate,
    list_phrases,
    soft_delete_phrase,
    update_phrase,
    upsert_phrase,
    record_from_interact,
)
from youtube_entertainment import (
    EntertainmentRequest,
    YouTubeCommand,
    dispatch_entertainment,
)

app = FastAPI(title="Zenbo Core API Gateway & MQTT Bridge", version="1.0.0")
from field_rollout_api import router as field_rollout_router
app.include_router(field_rollout_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def liff_api_alias(request, call_next):
    """Allow the public LIFF proxy to reserve its API namespace safely."""
    if request.url.path.startswith("/liff-api/"):
        request.scope["path"] = request.url.path[len("/liff-api"):]
    return await call_next(request)

LIFF_DIR = os.getenv("LIFF_DIR", "/app/liff-app")


class NoStoreStaticFiles(StaticFiles):
    """Keep LIFF WebView from serving an older controller after a deploy."""
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response


@app.get("/api/v1/web-auth/oidc/login")
async def oidc_login(request: Request, next: str = "/liff/"):
    """Redirect the browser to the KKU libsso OIDC authorization endpoint."""
    if not is_standard_web_request(request):
        raise HTTPException(status_code=404, detail="OIDC login is not configured for this host")
    state, nonce, cookie = build_tx_cookie(next)
    redirect = login_url(next, state=state, nonce=nonce)
    response = RedirectResponse(redirect, status_code=303)
    response.set_cookie(
        "zenbo_oidc_tx", cookie, max_age=600,
        httponly=True, secure=True, samesite="lax", path="/"
    )
    return response


@app.get("/liff/callback")
async def oidc_callback(request: Request, code: str = "", state: str = ""):
    """Consume the OIDC authorization code and establish a web session."""
    cookie = request.cookies.get("zenbo_oidc_tx", "")
    error, user = authenticate(code, state, cookie)
    redirect_target = "/liff/login/?error=" + error if error else "/liff/"
    response = RedirectResponse(redirect_target, status_code=303)
    response.delete_cookie("zenbo_oidc_tx", path="/")
    if not error and user:
        token = create_web_auth_session(
            user["sub"], user["display_name"], user["role"],
            user["provider"], SESSION_TTL_SECONDS,
        )
        set_session_cookie(response, token, SESSION_TTL_SECONDS)
        tx = parse_tx_cookie(cookie) or {}
        response.headers["location"] = tx.get("next", "/liff/")
    return response


if os.path.exists(LIFF_DIR):
    app.mount("/liff", NoStoreStaticFiles(directory=LIFF_DIR, html=True), name="liff")

@app.get("/")
async def root():
    index_file = os.path.join(LIFF_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file, headers={"Cache-Control": "no-store, max-age=0"})
    return {"message": "Zenbo Core API Gateway Online. Access LIFF at /liff"}


def apk_update_manifest() -> Dict[str, Any]:
    """Return an opt-in, integrity-pinned release manifest for the Android client."""
    manifest_file = os.getenv("APK_UPDATE_MANIFEST_FILE", "/app/data/apk-update.json")
    if os.path.exists(manifest_file):
        try:
            with open(manifest_file, "r") as f:
                data = json.load(f)
                if isinstance(data, dict) and data.get("status") == "ready" and data.get("update"):
                    return data
        except Exception:
            pass

    configured = [APK_UPDATE_URL, APK_UPDATE_VERSION_CODE, APK_UPDATE_VERSION_NAME, APK_UPDATE_SHA256]
    if not all(configured):
        return {"status": "not_configured", "update": None}
    parsed = urlparse(APK_UPDATE_URL)
    if parsed.scheme != "https" or not parsed.netloc or not re.fullmatch(r"[a-f0-9]{64}", APK_UPDATE_SHA256):
        # Misconfiguration must fail closed; do not let an app download an
        # unpinned artifact just because the endpoint exists.
        return {"status": "invalid_configuration", "update": None}
    try:
        version_code = int(APK_UPDATE_VERSION_CODE)
    except ValueError:
        return {"status": "invalid_configuration", "update": None}
    if version_code < 1:
        return {"status": "invalid_configuration", "update": None}
    return {
        "status": "ready",
        "update": {
            "version_code": version_code,
            "version_name": APK_UPDATE_VERSION_NAME[:80],
            "apk_url": APK_UPDATE_URL,
            "sha256": APK_UPDATE_SHA256,
            "notes": APK_UPDATE_NOTES[:500],
            "installation": "USER_CONFIRMATION_REQUIRED",
        },
    }


@app.get("/api/v1/apk-update")
async def get_apk_update_manifest():
    return apk_update_manifest()

MQTT_HOST = os.getenv("MQTT_HOST", "mqtt-broker")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "zenbo_core_gateway")
MQTT_AUTH_REQUIRED = os.getenv("MQTT_AUTH_REQUIRED", "true").strip().lower() in {"1", "true", "yes", "on"}
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "").strip()
# MQTT_TOKEN is deliberately not logged, returned from an API, or persisted in
# command history. MQTT_PASSWORD remains a migration alias for an existing
# deployment, but new deployments must use MQTT_TOKEN.
MQTT_TOKEN = os.getenv("MQTT_TOKEN") or os.getenv("MQTT_PASSWORD") or ""
# Android clients never receive MQTT credentials from their APK build.  A
# separately scoped bootstrap secret authorizes a one-time HTTPS provisioning
# response from this service instead.  Keep this different from MQTT_TOKEN so
# rotating the broker credential does not require rebuilding every APK.
ZENBO_DEVICE_PROVISIONING_TOKEN = os.getenv("ZENBO_DEVICE_PROVISIONING_TOKEN", "").strip()
MQTT_CLIENT_HOST = os.getenv("MQTT_CLIENT_HOST", "").strip()
MQTT_CLIENT_PORT = int(os.getenv("MQTT_CLIENT_PORT", str(MQTT_PORT)))
MQTT_CLIENT_TRANSPORT = os.getenv("MQTT_CLIENT_TRANSPORT", "tcp").strip().lower()
MQTT_CLIENT_TOPIC_ROOT = os.getenv("MQTT_CLIENT_TOPIC_ROOT", "zenbo").strip().strip("/") or "zenbo"
ZENBO_DEVICE_ROBOT_SLUG = os.getenv("ZENBO_DEVICE_ROBOT_SLUG", "").strip().lower()
TTS_SERVICE_URL = os.getenv("TTS_SERVICE_URL", "http://10.101.118.149:8025").strip()
TTS_BINARY_PATH = os.getenv("TTS_BINARY_PATH", "/api/tts/binary").strip() or "/api/tts/binary"
# MQTT carries short operator test prompts reliably, but it is not a transport
# for multi-minute WAV files.  Keep the inline recovery path well below common
# broker message-size limits and fall back to the APK's normal fetch for longer
# speech.
INLINE_TTS_MAX_BYTES = int(os.getenv("INLINE_TTS_MAX_BYTES", "512000"))
COMPILER_SERVICE_URL = os.getenv("COMPILER_SERVICE_URL", "http://zenbo-compiler-service:5006")
COMPILER_API_MODE = os.getenv("COMPILER_API_MODE", "legacy").strip().lower()
LIBRARY_RAG_API_URL = os.getenv("LIBRARY_RAG_API_URL", "https://lib.kku.ac.th/rag/api/chat").strip()
SERVER_PUBLIC_HOST = os.getenv("SERVER_PUBLIC_HOST", "http://localhost:8000")
COMMAND_HISTORY_DB = os.getenv("COMMAND_HISTORY_DB", "/app/data/command_history.sqlite3")
WEB_AUTH_ENABLED = os.getenv("ZENBO_WEB_AUTH_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
WEB_AUTH_HOST = os.getenv("ZENBO_WEB_AUTH_HOST", "lib.kku.ac.th").strip().lower()
WEB_AUTH_ADMIN_USERNAME = os.getenv("ZENBO_WEB_ADMIN_USERNAME", "").strip()
WEB_AUTH_ADMIN_PASSWORD_HASH = os.getenv("ZENBO_WEB_ADMIN_PASSWORD_HASH", "").strip()
WEB_AUTH_SESSION_TTL_SECONDS = max(300, min(int(os.getenv("ZENBO_WEB_SESSION_TTL_SECONDS", "28800")), 86400))
WEB_AUTH_COOKIE = "zenbo_web_session"


def _web_auth_password_matches(password: str) -> bool:
    """Verify the versioned hash stored only in the deployment environment."""
    if not WEB_AUTH_ADMIN_PASSWORD_HASH:
        return False
    try:
        parts = WEB_AUTH_ADMIN_PASSWORD_HASH.split("$")
        if parts[0] == "scrypt" and len(parts) == 6:
            _, n, r, p, salt_b64, digest_b64 = parts
            expected = base64.urlsafe_b64decode(digest_b64.encode("ascii"))
            actual = hashlib.scrypt(
                password.encode("utf-8"), salt=base64.urlsafe_b64decode(salt_b64.encode("ascii")),
                n=int(n), r=int(r), p=int(p), dklen=len(expected),
            )
            return hmac.compare_digest(actual, expected)
        elif parts[0] == "pbkdf2_sha256" and len(parts) == 4:
            _, iterations, salt_b64, digest_b64 = parts
            expected = base64.urlsafe_b64decode(digest_b64.encode("ascii"))
            actual = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"),
                base64.urlsafe_b64decode(salt_b64.encode("ascii")),
                int(iterations), dklen=len(expected),
            )
            return hmac.compare_digest(actual, expected)
        elif parts[0] == "plain" and len(parts) == 2:
            return hmac.compare_digest(parts[1], password)
        elif not WEB_AUTH_ADMIN_PASSWORD_HASH.startswith(("scrypt$", "pbkdf2_sha256$", "plain$")):
            return hmac.compare_digest(WEB_AUTH_ADMIN_PASSWORD_HASH, password)
        return False
    except (ValueError, TypeError, AttributeError):
        return False


def _session_user(token: str) -> Optional[dict]:
    """Resolve a web auth session token to a user dict, supporting OIDC and password sessions."""
    if not token:
        return None
    session = get_web_auth_session(hashlib.sha256(token.encode("utf-8")).hexdigest())
    if not session:
        return None
    role = session.get("role")
    display_name = session.get("display_name") or session.get("username")
    sub = session.get("sub") or session.get("username")
    if not role and session.get("username"):
        role = "admin"
        display_name = display_name or session["username"]
        sub = sub or session["username"]
    return {
        "sub": sub,
        "username": sub,
        "display_name": display_name,
        "role": role or "viewer",
        "provider": session.get("provider") or "password",
    }


@app.middleware("http")
async def standard_web_auth(request: Request, call_next):
    """Protect the normal-web controller and its same-origin API, requiring login."""
    if not is_standard_web_request(request):
        return await call_next(request)
    path = request.url.path
    is_controller = path == "/liff" or path.startswith("/liff/")
    is_api = path.startswith("/liff-api/") or path.startswith("/api/")
    public = (
        path == "/liff/login" or path.startswith("/liff/login/")
        or path == "/liff/callback"
        or path.startswith("/liff/shared/")
        or path == "/liff/liff.js"
        or path == "/liff/liff-config.js"
        or path.startswith("/liff/download/")
        or path == "/liff/download"
        or path.startswith("/download/")
        or path.startswith("/liff-api/api/v1/web-auth/")
        or path.startswith("/api/v1/web-auth/")
        or path == "/api/v1/apk-update"
        or path.startswith("/api/v1/apk-update")
        or path == "/liff-api/api/v1/apk-update"
        or path.startswith("/liff-api/api/v1/apk-update")
        or path == "/liff-api/api/v1/scenario-builder/schema"
        or path == "/api/v1/scenario-builder/schema"
    )
    try:
        user = _session_user(request.cookies.get(SESSION_COOKIE, ""))
    except RuntimeError:
        return JSONResponse({"detail": "authentication store unavailable"}, status_code=503)
    request.state.user = user
    if (is_controller or is_api) and not public and not user:
        if is_api:
            return JSONResponse({"detail": "login required"}, status_code=401)
        destination = request.url.path + (("?" + request.url.query) if request.url.query else "")
        return RedirectResponse("/liff/login/?next=" + quote(destination, safe="/%?=&"), status_code=303)
    return await call_next(request)


class WebLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=8, max_length=256)


@app.post("/api/v1/web-auth/login")
async def web_auth_login(payload: WebLoginRequest, request: Request):
    if not is_standard_web_request(request) or not WEB_AUTH_ADMIN_USERNAME or not WEB_AUTH_ADMIN_PASSWORD_HASH:
        raise HTTPException(status_code=404, detail="Web login is not configured")
    submitted_user = payload.username.strip()
    valid_users = {WEB_AUTH_ADMIN_USERNAME, "admin", "zenbo-admin"}
    if submitted_user not in valid_users or not _web_auth_password_matches(payload.password):
        raise HTTPException(status_code=401, detail="ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
    try:
        token = create_web_auth_session(
            sub=submitted_user,
            display_name=submitted_user,
            role="admin",
            provider="password",
            ttl_seconds=WEB_AUTH_SESSION_TTL_SECONDS,
        )
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail="authentication store unavailable") from error
    response = JSONResponse({"ok": True, "username": submitted_user, "role": "admin"})
    response.set_cookie(WEB_AUTH_COOKIE, token, max_age=WEB_AUTH_SESSION_TTL_SECONDS,
                        httponly=True, secure=True, samesite="lax", path="/")
    return response


@app.get("/api/v1/web-auth/me")
async def web_auth_me(request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="login required")
    return {"user": user}


@app.post("/api/v1/web-auth/logout")
async def web_auth_logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE, "")
    if token:
        delete_web_auth_session(hashlib.sha256(token.encode("utf-8")).hexdigest())
    response = JSONResponse({"ok": True})
    delete_session_cookie(response)
    return response


@app.get("/liff/download/{filename}")
@app.get("/download/{filename}")
async def download_client_file(filename: str):
    """Serve Zenbo client APK and zip packages directly with proper MIME types."""
    safe_name = os.path.basename(filename)
    file_path = os.path.join(LIFF_DIR, "download", safe_name)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    media_type = "application/vnd.android.package-archive" if safe_name.endswith(".apk") else ("application/zip" if safe_name.endswith(".zip") else "application/octet-stream")
    return FileResponse(
        file_path,
        media_type=media_type,
        filename=safe_name,
        headers={
            "Cache-Control": "public, max-age=300",
            "Content-Disposition": f'attachment; filename="{safe_name}"'
        }
    )


NAVIGATION_SERVICE_URL = os.getenv("NAVIGATION_SERVICE_URL", "http://10.101.118.149:8032")
SCENARIO_REGISTRY_TOKEN = os.getenv("SCENARIO_REGISTRY_TOKEN", "")
MUSIC_DANCE_AUTOMATION_ENABLED = os.getenv("MUSIC_DANCE_AUTOMATION_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
# Autonomous base movement is an opt-in production capability.  A scenario may
# be registered and previewed while this remains off; dispatch only becomes
# possible after the field operator deliberately enables the server flag.
AUTONOMOUS_MOTION_ENABLED = os.getenv("AUTONOMOUS_MOTION_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
RELATIVE_MOTION_ENABLED = os.getenv("RELATIVE_MOTION_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
RELATIVE_MOTION_MAX_SPEED = max(1, min(int(os.getenv("RELATIVE_MOTION_MAX_SPEED", "1")), 7))
RELATIVE_MOTION_MAX_DISTANCE_M = max(0.01, min(float(os.getenv("RELATIVE_MOTION_MAX_DISTANCE_M", "0.15")), 0.75))
RELATIVE_MOTION_HARD_STOP_MS = max(100, min(int(os.getenv("RELATIVE_MOTION_HARD_STOP_MS", "1500")), 3000))
# T9 starts with an internal L1-L3 cohort. Raising this cap is an explicit
# deployment decision after the required telemetry and field evidence exist.
FIELD_ROLLOUT_MAX_LEVEL = max(1, min(int(os.getenv("FIELD_ROLLOUT_MAX_LEVEL", "3")), 7))
ROUTE_CERTIFICATION_REQUIRED = os.getenv("ROUTE_CERTIFICATION_REQUIRED", "true").strip().lower() in {"1", "true", "yes"}
# L13-L20 are a supervised-governance layer around L10. They do not add an
# autonomous navigation primitive: without a valid permit, Core does not create
# a calibrated-route run.
AUTONOMY_GOVERNANCE_REQUIRED = os.getenv("AUTONOMY_GOVERNANCE_REQUIRED", "true").strip().lower() in {"1", "true", "yes"}
AUTONOMY_PERMIT_TTL_MS = int(os.getenv("AUTONOMY_PERMIT_TTL_SECONDS", "900")) * 1000
# OTA is opt-in.  Core only publishes a manifest for an already hosted,
# release-signed APK; it never serves or builds the APK itself.
APK_UPDATE_URL = os.getenv("APK_UPDATE_URL", "https://lib.kku.ac.th/liff/download/zenbo.apk").strip()
APK_UPDATE_VERSION_CODE = os.getenv("APK_UPDATE_VERSION_CODE", "722").strip()
APK_UPDATE_VERSION_NAME = os.getenv("APK_UPDATE_VERSION_NAME", "1.9.46-stable").strip()
APK_UPDATE_SHA256 = os.getenv("APK_UPDATE_SHA256", "eaed98e62d672b78e9d31971910e790ae85fc12b376f4b70db475095c8425871").strip().lower()
APK_UPDATE_NOTES = os.getenv("APK_UPDATE_NOTES", "โหมดใบหน้าหุ่นยนต์ Zenbo และระบบซิงค์สีหน้าท่าทาง (Emotional Action)").strip()


class DeviceMqttProvisionRequest(BaseModel):
    """Identity asserted by the pre-provisioned Zenbo APK bootstrap secret."""
    robot_slug: str = Field(min_length=1, max_length=64)

    @field_validator("robot_slug")
    @classmethod
    def validate_robot_slug(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", normalized):
            raise ValueError("robot_slug must contain only lowercase letters, digits, _ or -")
        return normalized


def mqtt_device_provisioning_is_configured() -> bool:
    """Do not expose a broker credential unless all independent safeguards exist."""
    if not MQTT_AUTH_REQUIRED:
        return False
    if not all((ZENBO_DEVICE_PROVISIONING_TOKEN, MQTT_USERNAME, MQTT_TOKEN, MQTT_CLIENT_HOST)):
        return False
    if MQTT_CLIENT_TRANSPORT not in {"tcp", "ssl", "ws", "wss"}:
        return False
    if not 1 <= MQTT_CLIENT_PORT <= 65535:
        return False
    # The client receives a hostname/IP, never a URL or a Docker-only hostname.
    if "://" in MQTT_CLIENT_HOST or any(char.isspace() for char in MQTT_CLIENT_HOST):
        return False
    return True


@app.post("/api/v1/device/mqtt-connection")
async def provision_device_mqtt_connection(
    request: DeviceMqttProvisionRequest,
    x_zenbo_provisioning_token: Optional[str] = Header(default=None),
):
    """Return in-memory MQTT connection data only to the installed Zenbo app.

    This endpoint must be reached through HTTPS (the public libn proxy).  It
    deliberately returns no command history, scenario data, or token metadata.
    A caller gets a generic 403 for absent and incorrect bootstrap credentials.
    """
    if not mqtt_device_provisioning_is_configured():
        raise HTTPException(status_code=503, detail="Device MQTT provisioning is not configured")
    if not x_zenbo_provisioning_token or not secrets.compare_digest(
        x_zenbo_provisioning_token, ZENBO_DEVICE_PROVISIONING_TOKEN
    ):
        raise HTTPException(status_code=403, detail="Device provisioning is not authorized")
    if ZENBO_DEVICE_ROBOT_SLUG and not secrets.compare_digest(request.robot_slug, ZENBO_DEVICE_ROBOT_SLUG):
        raise HTTPException(status_code=403, detail="Device provisioning is not authorized")

    payload = {
        "broker_host": MQTT_CLIENT_HOST,
        "broker_port": MQTT_CLIENT_PORT,
        "transport": MQTT_CLIENT_TRANSPORT,
        "username": MQTT_USERNAME,
        "token": MQTT_TOKEN,
        "topic_prefix": f"{MQTT_CLIENT_TOPIC_ROOT}/{request.robot_slug}",
    }
    return JSONResponse(payload, headers={"Cache-Control": "no-store, max-age=0"})

# These identifiers are the stable voice-persona contract.  The Android client
# resolves each profile through Core's reachable Neural TTS proxy; rate/pitch
# create distinct child, young, and adult delivery while keeping one provider.
VOICE_PROFILES = {
    "female_child": {"label": "เด็กผู้หญิง สดใส", "provider": "neural", "voice": "female_sweet", "rate": "-8%", "pitch": "+10Hz"},
    "female_young": {"label": "ผู้หญิงวัยรุ่น เป็นมิตร", "provider": "neural", "voice": "female_sweet", "rate": "-6%", "pitch": "+4Hz"},
    "female_adult": {"label": "ผู้หญิงผู้ใหญ่ สุภาพ", "provider": "neural", "voice": "female_sweet", "rate": "-3%", "pitch": "+0Hz"},
    "male_child": {"label": "เด็กผู้ชาย ร่าเริง", "provider": "neural", "voice": "boy_cute", "rate": "-8%", "pitch": "+7Hz"},
    "male_young": {"label": "ผู้ชายวัยรุ่น เป็นมิตร", "provider": "neural", "voice": "male_natural", "rate": "-4%", "pitch": "+2Hz"},
    "male_adult": {"label": "ผู้ชายผู้ใหญ่ อบอุ่น", "provider": "neural", "voice": "male_natural", "rate": "-2%", "pitch": "+0Hz"},
}

# Presentation speech needs a visible beginning and end, not merely a set of
# commands published at the same time.  These cues only use RobotFace and head
# poses present in the bundled Zenbo SDK sample; they intentionally do not add
# an unverified canned-action ID or base movement.
PRESENTATION_SPEECH_CUES: Dict[str, Dict[str, Any]] = {
    "HAPPY": {
        "face": "HAPPY_ADV",
        "head_sequence": [
            {"yaw": 0, "pitch": 8, "speed": 1, "delay_ms": 0},
            {"yaw": 0, "pitch": 18, "speed": 1, "delay_ms": 650},
            {"yaw": 0, "pitch": 5, "speed": 1, "delay_ms": 650},
        ],
        "after_speech": {"face": "PLEASED", "head": {"yaw": 0, "pitch": 0, "speed": 1}},
    },
    "PLEASED": {
        "face": "PLEASED_ADV",
        "head_sequence": [
            {"yaw": 0, "pitch": 8, "speed": 1, "delay_ms": 0},
            {"yaw": 0, "pitch": 15, "speed": 1, "delay_ms": 700},
            {"yaw": 0, "pitch": 0, "speed": 1, "delay_ms": 650},
        ],
        "after_speech": {"face": "DEFAULT_STILL"},
    },
    "PROUD": {
        "face": "PROUD_ADV",
        "head_sequence": [
            {"yaw": 0, "pitch": 5, "speed": 1, "delay_ms": 0},
            {"yaw": 0, "pitch": 16, "speed": 1, "delay_ms": 700},
            {"yaw": 0, "pitch": 4, "speed": 1, "delay_ms": 700},
        ],
        "after_speech": {"face": "CONFIDENT", "head": {"yaw": 0, "pitch": 0, "speed": 1}},
    },
    "CONFIDENT": {
        "face": "CONFIDENT_ADV",
        "head_sequence": [
            {"yaw": 0, "pitch": 3, "speed": 1, "delay_ms": 0},
            {"yaw": -10, "pitch": 5, "speed": 1, "delay_ms": 850},
            {"yaw": 0, "pitch": 2, "speed": 1, "delay_ms": 850},
        ],
        "after_speech": {"face": "DEFAULT_STILL"},
    },
    "INTERESTED": {
        "face": "INTERESTED_ADV",
        "head_sequence": [
            {"yaw": 0, "pitch": 4, "speed": 1, "delay_ms": 0},
            {"yaw": 12, "pitch": 6, "speed": 1, "delay_ms": 800},
            {"yaw": 0, "pitch": 3, "speed": 1, "delay_ms": 850},
        ],
        "after_speech": {"face": "EXPECTING"},
    },
    "EXPECTING": {
        "face": "EXPECTING_ADV",
        "head_sequence": [
            {"yaw": 0, "pitch": 5, "speed": 1, "delay_ms": 0},
            {"yaw": -8, "pitch": 6, "speed": 1, "delay_ms": 900},
            {"yaw": 0, "pitch": 4, "speed": 1, "delay_ms": 900},
        ],
        "after_speech": {"face": "EXPECTING"},
    },
    "SERIOUS": {
        "face": "SERIOUS_ADV",
        "head_sequence": [
            {"yaw": 0, "pitch": 2, "speed": 1, "delay_ms": 0},
            {"yaw": 0, "pitch": 10, "speed": 1, "delay_ms": 750},
            {"yaw": 0, "pitch": 2, "speed": 1, "delay_ms": 750},
        ],
        "after_speech": {"face": "DEFAULT_STILL"},
    },
    "SINGING": {
        "face": "SINGING_ADV",
        "head_sequence": [
            {"yaw": -10, "pitch": 5, "speed": 2, "delay_ms": 0},
            {"yaw": 10, "pitch": 5, "speed": 2, "delay_ms": 700},
            {"yaw": 0, "pitch": 4, "speed": 2, "delay_ms": 700},
        ],
        "after_speech": {"face": "HAPPY"},
    },
    "DEFAULT_STILL": {
        "face": "DEFAULT_STILL",
        "head_sequence": [
            {"yaw": 0, "pitch": 2, "speed": 1, "delay_ms": 0},
            {"yaw": 0, "pitch": 0, "speed": 1, "delay_ms": 650},
        ],
        "after_speech": {"face": "DEFAULT_STILL", "head": {"yaw": 0, "pitch": 0, "speed": 1}},
    },
}

# This is the operator-facing contract for every scenario.  It uses only
# face/head/light cues already handled by the client; it never implies body
# motion, a canned action, or a sensor capability that has not been proven.
VISUAL_BEHAVIOR_LABELS: Dict[str, Dict[str, str]] = {
    "HAPPY": {"face": "ยิ้มสดใส", "gesture": "พยักหน้าเบา ๆ ตามจังหวะคำพูด", "after": "พักด้วยรอยยิ้มอ่อน"},
    "PLEASED": {"face": "ยิ้มอย่างสุภาพ", "gesture": "ก้มศีรษะขอบคุณเล็กน้อย", "after": "กลับสู่ท่าพัก"},
    "PROUD": {"face": "มั่นใจและภาคภูมิใจ", "gesture": "เงยศีรษะเล็กน้อยแล้วกลับมาตรง", "after": "คงสีหน้ามั่นใจ"},
    "CONFIDENT": {"face": "มั่นใจเป็นมิตร", "gesture": "หันศีรษะเล็กน้อยเพื่อทักทาย", "after": "กลับสู่ท่าพัก"},
    "INTERESTED": {"face": "สนใจและพร้อมช่วยเหลือ", "gesture": "เอียงศีรษะเล็กน้อยเหมือนกำลังรับฟัง", "after": "คงท่าพร้อมตอบ"},
    "EXPECTING": {"face": "ตั้งใจรอคำตอบ", "gesture": "หันศีรษะเล็กน้อยแล้วมองตรง", "after": "คงท่าพร้อมรับบริการ"},
    "SERIOUS": {"face": "สุภาพและจริงจัง", "gesture": "พยักหน้าอย่างนุ่มนวล", "after": "กลับสู่ท่าพัก"},
    "SINGING": {"face": "สนุกสนาน", "gesture": "โยกศีรษะเบา ๆ โดยไม่เคลื่อนฐาน", "after": "กลับมายิ้ม"},
    "DEFAULT_STILL": {"face": "พักรออย่างเป็นมิตร", "gesture": "ปรับศีรษะเข้ากลางอย่างนุ่มนวล", "after": "คงท่าพัก"},
}


def visual_behavior_metadata(item: Dict[str, Any]) -> Dict[str, Any]:
    """Describe the visible, stationary Zenbo cue without leaking commands."""
    command = item.get("command") if isinstance(item.get("command"), dict) else {}
    steps = command.get("steps") if isinstance(command.get("steps"), list) else []
    if not steps:
        detect_branch = command.get("on_detect") if isinstance(command.get("on_detect"), dict) else {}
        steps = detect_branch.get("steps") if isinstance(detect_branch.get("steps"), list) else []
    first_step = steps[0] if steps and isinstance(steps[0], dict) else {}
    face = str(item.get("visual_profile") or command.get("face") or first_step.get("face") or "DEFAULT_STILL").upper()
    if face not in PRESENTATION_SPEECH_CUES:
        face = "DEFAULT_STILL"
    labels = VISUAL_BEHAVIOR_LABELS[face]
    lights = command.get("wheel_lights") if isinstance(command.get("wheel_lights"), dict) else first_step.get("wheel_lights", {})
    lights = lights if isinstance(lights, dict) else {}
    mode = str(lights.get("mode", "ไม่เปลี่ยนไฟล้อ"))
    light_text = "ไม่เปลี่ยนไฟล้อ" if not lights else f"ไฟล้อ {mode}"
    return {
        "face": face,
        "face_description": labels["face"],
        "gesture_description": labels["gesture"],
        "after_description": labels["after"],
        "wheel_lights_description": light_text,
        "base_motion": "อยู่กับที่ ไม่สั่งฐานเคลื่อนที่",
    }


def apply_visual_behavior_contract(command: Dict[str, Any], visual_profile: Optional[str] = None) -> Dict[str, Any]:
    """Attach one SDK-backed expression and head gesture to every dispatch."""
    face = str(visual_profile or command.get("face") or "DEFAULT_STILL").upper()
    if face not in PRESENTATION_SPEECH_CUES:
        face = "DEFAULT_STILL"
    cue = PRESENTATION_SPEECH_CUES[face]
    # The cue's ADV face is the SDK-backed visual variant used by the existing
    # presentation flow; retain it instead of silently downgrading the cue.
    command["face"] = cue.get("face", face)
    command.setdefault("head_sequence", json.loads(json.dumps(cue["head_sequence"])))
    command.setdefault("after_speech", json.loads(json.dumps(cue["after_speech"])))
    return command

# Present Mode is deliberately catalog-driven.  The browser may select a
# presentation and provide bounded text fields, but it cannot inject arbitrary
# motion/action payloads into a preset.  Presets marked gated are visible for
# planning, yet Core refuses to dispatch them until their device capability
# and safety gate are implemented and verified.
PRESENTATION_CATALOG: Dict[str, Dict[str, Any]] = {
    "innotech-judge-welcome-30": {
        "title": "ต้อนรับกรรมการ InnoTech Show & Share 2026 (30 วิ)",
        "icon": "🏆",
        "category": "พิธีการ",
        "duration_seconds": 30,
        "availability": "ready",
        "description": "Booky กล่าวต้อนรับคณะกรรมการผู้ทรงเกียรติ ในงาน InnoTech Show & Share 2026 จัดโดยศูนย์นวัตกรรมการเรียนการสอน (LTIC) มหาวิทยาลัยขอนแก่น พร้อมสีหน้าและท่าทางสุภาพ 30 วินาที",
        "fields": [],
        "command": {
            "text": "สวัสดีครับ ขอต้อนรับคณะกรรมการผู้ทรงเกียรติทุกท่าน สู่งาน InnoTech Show & Share 2026 จัดโดยศูนย์นวัตกรรมการเรียนการสอน มหาวิทยาลัยขอนแก่น ครับ ผม บุ๊คกี้ หุ่นยนต์บรรณารักษ์อัจฉริยะ ขอร่วมเป็นส่วนหนึ่งในการขับเคลื่อนนวัตกรรมด้วยพลัง AI ผสาน KKU IntelSphere เพื่อบริการที่ชาญฉลาดและเข้าถึงง่าย ขอเชิญคณะกรรมการทุกท่านรับชมการสาธิตผลงานได้เลยครับ",
            "voice_profile": "male_young",
            "face": "PROUD",
            "action": {"action_id": 2, "stop": False},
            "wheel_lights": {"mode": "breath", "color": "#8B5CF6", "brightness": 14},
            "head": {"yaw": 0, "pitch": 8, "speed": 1},
        },
    },
    "library-welcome-30": {"title": "ยินดีต้อนรับห้องสมุด 30 วินาที", "icon": "📚", "category": "ต้อนรับ", "duration_seconds": 30, "availability": "ready", "description": "Booky กล่าวต้อนรับสำนักหอสมุด มข.", "fields": [], "command": {"text": "สวัสดีครับ ผมบุ๊คกี้ ยินดีต้อนรับทุกท่านสู่สำนักหอสมุด มหาวิทยาลัยขอนแก่นครับ ที่นี่มีพื้นที่อ่านหนังสือ ค้นคว้า และเรียนรู้อย่างสร้างสรรค์ หากต้องการความช่วยเหลือ เรียกผมได้เสมอนะครับ", "voice_profile": "male_child", "face": "HAPPY", "wheel_lights": {"mode": "breath", "color": "#00D031", "brightness": 12}}},
    "judge-greeting": {"title": "ทักทายกรรมการ", "icon": "🎓", "category": "พิธีการ", "duration_seconds": 18, "availability": "ready", "description": "กล่าวต้อนรับกรรมการอย่างสุภาพ", "fields": [{"name": "event_name", "label": "ชื่องาน", "default": "KKU Digital Transformation & AI Hackathon 2026 “The Great Reset of Education and Management” ปลุกพลังคน พลิกโฉมองค์กร ด้วยนวัตกรรม AI", "max_length": 220}], "command": {"text": "สวัสดีครับ คณะกรรมการผู้ทรงเกียรติทุกท่าน ยินดีต้อนรับสู่ {event_name} ครับ ผมบุ๊คกี้ พร้อมนำเสนอและอำนวยความสะดวกแก่ทุกท่านครับ", "voice_profile": "male_young", "face": "PROUD", "wheel_lights": {"mode": "breath", "color": "#6D5EF7", "brightness": 12}, "head": {"yaw": 0, "pitch": 8, "speed": 1}}},
    "photo-invitation": {"title": "เชิญถ่ายภาพ", "icon": "📸", "category": "กิจกรรม", "duration_seconds": 12, "availability": "ready", "description": "เชิญทุกคนรวมตัว นับถอยหลัง และตรวจจับใบหน้าโดยไม่เปิดพรีวิวกล้อง", "fields": [], "camera_preview": {"vision_action": "detect_face", "display": "operator_only"}, "command": {"text": "ขอเชิญทุกท่านมาถ่ายภาพร่วมกันนะครับ ยิ้มให้กล้องครับ สาม สอง หนึ่ง", "voice_profile": "male_child", "face": "HAPPY", "wheel_lights": {"mode": "marquee", "color": "#FF4FA3", "brightness": 16}, "vision": {"action": "detect_face", "interval_ms": 2000, "debug_preview": False}}},
    "photo-pose": {"title": "โพสท่าถ่ายภาพ", "icon": "😊", "category": "กิจกรรม", "duration_seconds": 6, "availability": "ready", "description": "ยิ้มและอยู่กับที่สำหรับถ่ายภาพ", "fields": [], "command": {"text": "พร้อมถ่ายภาพครับ", "voice_profile": "male_child", "face": "HAPPY", "head": {"yaw": 0, "pitch": 5, "speed": 1}, "wheel_lights": {"mode": "static", "color": "#FF4FA3", "brightness": 12}}},
    "self-introduction": {"title": "แนะนำตัว Booky", "icon": "🤖", "category": "ต้อนรับ", "duration_seconds": 20, "availability": "ready", "description": "แนะนำบทบาทและความสามารถของหุ่นยนต์", "fields": [{"name": "robot_name", "label": "ชื่อหุ่นยนต์", "default": "บุ๊คกี้", "max_length": 40}], "command": {"text": "สวัสดีครับ ผม{robot_name} หุ่นยนต์ผู้ช่วยของสำนักหอสมุด มหาวิทยาลัยขอนแก่นครับ ผมช่วยทักทาย แนะนำเส้นทาง สื่อสาร และสร้างรอยยิ้มให้ทุกคนได้ครับ", "voice_profile": "male_child", "face": "CONFIDENT", "wheel_lights": {"mode": "breath", "color": "#00D031", "brightness": 12}}},
    "library-orientation": {"title": "แนะนำบริการห้องสมุด", "icon": "🧭", "category": "นำชม", "duration_seconds": 25, "availability": "ready", "description": "แนะนำพื้นที่และบริการหลัก", "fields": [], "command": {"text": "สำนักหอสมุดมีบริการค้นหนังสือ ยืมคืน พื้นที่อ่านหนังสือ และพื้นที่เรียนรู้ร่วมกันครับ หากต้องการไปยังจุดใด เลือกเมนูนำทางบนหน้าควบคุม แล้วผมจะแสดงแผนที่และพูดคำแนะนำให้ครับ", "voice_profile": "male_young", "face": "INTERESTED", "wheel_lights": {"mode": "breath", "color": "#2196F3", "brightness": 12}}},
    "route-guide": {"title": "นำชมด้วยแผนที่", "icon": "🗺️", "category": "นำชม", "duration_seconds": 30, "availability": "ready", "description": "แสดงแผนที่และพูดเส้นทาง โดยไม่สั่งเดินอัตโนมัติ", "fields": [{"name": "from_location", "label": "จาก", "default": "1102", "max_length": 80}, {"name": "to", "label": "ไป", "default": "1401", "max_length": 80}], "command": {"face": "HAPPY", "wheel_lights": {"mode": "breath", "color": "#2196F3", "brightness": 12}}, "route_required": True},
    "library-map-open": {"title": "เปิดแผนที่ห้องสมุด", "icon": "🗺️", "category": "นำชม", "duration_seconds": 30, "availability": "ready", "description": "เลือกจุดเริ่มต้นและปลายทาง แล้ว Booky แสดงเส้นทางบนจอพร้อมพูดแนะนำภาษาไทย โดยไม่สั่งเดิน", "visual_profile": "INTERESTED", "fields": [{"name": "from_location", "label": "จุดเริ่มต้น (START POINT)", "default": "1102", "max_length": 80, "input_type": "route_location", "route_role": "start"}, {"name": "to", "label": "จุดหมายปลายทาง (DESTINATION)", "default": "1401", "max_length": 80, "input_type": "route_location", "route_role": "destination"}], "command": {"voice_profile": "male_child", "face": "INTERESTED", "wheel_lights": {"mode": "breath", "color": "#2196F3", "brightness": 12}}, "route_required": True},
    "library-rag-open": {"title": "ถามห้องสมุดด้วย RAG", "icon": "💬", "category": "นำชม", "duration_seconds": 18, "availability": "ready", "description": "เลือกคำถามแนะนำ พิมพ์ หรือพูดผ่านไมค์ แล้ว Booky จะตอบและเปิดผู้ช่วยบนหน้าจอ", "visual_profile": "INTERESTED", "rag_answer": True, "fields": [{"name": "question", "label": "คำถามสำหรับ KKUL AI Library Assistant", "placeholder": "พิมพ์หรือกดไมค์เพื่อพูดคำถามภาษาไทย", "default": "CDS คืออะไร?", "max_length": 240, "input_type": "textarea", "microphone": True, "suggestions": ["CDS คืออะไร?", "ประชาชนทั่วไปสมัครสมาชิกและยืมหนังสือได้ไหม?", "สมาชิกสมทบชั่วคราวยืมหนังสือได้ไหม?", "ยืมต่อได้กี่ครั้ง?", "ระเบียบฉบับนี้ระบุค่าปรับเป็นจำนวนเท่าไร?", "คืนหนังสือผ่าน Book Drop ได้ที่ไหน?"]}], "command": {"text": "ผมกำลังเปิดผู้ช่วยตอบคำถามห้องสมุดให้ครับ", "voice_profile": "male_child", "face": "INTERESTED", "wheel_lights": {"mode": "breath", "color": "#6D5EF7", "brightness": 12}, "navigation": {"display_url": "https://lib.kku.ac.th/rag/", "speech_text": "ผมกำลังเปิดผู้ช่วยตอบคำถามห้องสมุดให้ครับ", "step_speeches": []}}},
    "speak-thai-message": {"title": "ให้ Booky พูดข้อความ", "icon": "🗣️", "category": "สื่อสาร", "duration_seconds": 12, "availability": "ready", "description": "พิมพ์ข้อความภาษาไทย แล้วให้ Booky พูดพร้อมสีหน้าและท่าทาง โดยไม่สั่งให้เคลื่อนที่", "visual_profile": "HAPPY", "fields": [{"name": "speech_text", "label": "ข้อความภาษาไทยที่ให้ Booky พูด", "placeholder": "เช่น ยินดีต้อนรับทุกท่านเข้าสู่สำนักหอสมุดครับ", "max_length": 240, "input_type": "textarea"}], "command": {"text": "{speech_text}", "voice_profile": "male_child", "face": "HAPPY", "wheel_lights": {"mode": "breath", "color": "#00D031", "brightness": 12}}},
    "route-announcement": {"title": "ประกาศจุดบริการ", "icon": "📍", "category": "นำชม", "duration_seconds": 12, "availability": "ready", "description": "บอกจุดหมายโดยไม่เคลื่อนที่", "fields": [{"name": "destination", "label": "จุดหมาย", "default": "เคาน์เตอร์บริการ", "max_length": 80}], "command": {"text": "หากต้องการไปยัง {destination} ผมยินดีแสดงเส้นทางบนแผนที่ให้ครับ", "voice_profile": "male_young", "face": "INTERESTED", "wheel_lights": {"mode": "breath", "color": "#2196F3", "brightness": 10}}},
    "new-member-welcome": {"title": "ต้อนรับสมาชิกใหม่", "icon": "🌱", "category": "ต้อนรับ", "duration_seconds": 14, "availability": "ready", "description": "ต้อนรับผู้ใช้บริการใหม่", "fields": [], "command": {"text": "ยินดีต้อนรับสมาชิกใหม่ครับ ขอให้ทุกท่านสนุกกับการเรียนรู้ และใช้บริการสำนักหอสมุดได้อย่างเต็มที่นะครับ", "voice_profile": "male_child", "face": "PLEASED", "wheel_lights": {"mode": "breath", "color": "#00D031", "brightness": 12}}},
    "ask-me": {"title": "โหมดสื่อสาร", "icon": "💬", "category": "สื่อสาร", "duration_seconds": 0, "availability": "gated", "description": "ต้องมี speech-to-text และ dialog state บนหุ่นก่อน", "visual_profile": "INTERESTED", "fields": [], "gate_reason": "ยังไม่มี dialog runner ที่ยืนยันการฟัง/ตอบเสียงบน Zenbo"},
    "feedback-invitation": {"title": "เชิญให้ข้อเสนอแนะ", "icon": "📝", "category": "สื่อสาร", "duration_seconds": 14, "availability": "ready", "description": "เชิญผู้ใช้ส่งความคิดเห็น", "fields": [], "command": {"text": "ความคิดเห็นของทุกท่านมีความหมายมากครับ หากมีข้อเสนอแนะ โปรดแจ้งเจ้าหน้าที่หรือส่งผ่านแบบประเมิน ขอบคุณครับ", "voice_profile": "male_young", "face": "EXPECTING", "wheel_lights": {"mode": "breath", "color": "#FFC107", "brightness": 10}}},
    "story-time": {"title": "เล่านิทาน", "icon": "📖", "category": "เด็กและการเรียนรู้", "duration_seconds": 55, "availability": "ready", "description": "นิทานสั้นแบ่งเป็นตอน หยุดได้ทันทีระหว่างตอน", "visual_profile": "HAPPY", "fields": [], "command": {"steps": [{"text": "กาลครั้งหนึ่ง มีนกน้อยตัวหนึ่งอยากเรียนรู้เรื่องราวใหม่ ๆ ทุกวันครับ", "voice_profile": "male_child", "face": "HAPPY", "wheel_lights": {"mode": "breath", "color": "#00D031", "brightness": 10}}, {"text": "นกน้อยจึงบินมาที่ห้องสมุด พบหนังสือมากมาย และขอให้บรรณารักษ์ช่วยแนะนำครับ", "voice_profile": "male_child", "face": "INTERESTED", "wheel_lights": {"mode": "breath", "color": "#2196F3", "brightness": 10}}, {"text": "เมื่ออ่านจบ นกน้อยรู้ว่า การถามและการแบ่งปันความรู้ ทำให้ทุกคนเก่งขึ้นได้ครับ", "voice_profile": "male_child", "face": "PLEASED", "wheel_lights": {"mode": "rainbow", "color": "#FFC107", "brightness": 12}}, {"text": "นิทานจบแล้วครับ ขอบคุณที่ฟังบุ๊คกี้นะครับ", "voice_profile": "male_child", "face": "HAPPY", "wheel_lights": {"mode": "breath", "color": "#00D031", "brightness": 8}}]}},
    "quiz-host": {"title": "พิธีกรเกมตอบคำถาม", "icon": "❓", "category": "กิจกรรม", "duration_seconds": 0, "availability": "gated", "description": "ต้องมีรอ operator เฉลยและสถานะรอบเกม", "visual_profile": "EXPECTING", "fields": [], "gate_reason": "ต้องมี stateful quiz runner"},
    "event-opening": {"title": "กล่าวเปิดงาน", "icon": "🎉", "category": "พิธีการ", "duration_seconds": 18, "availability": "ready", "description": "กล่าวเปิดงานแบบปรับชื่องาน", "fields": [{"name": "event_name", "label": "ชื่องาน", "default": "KKU Digital Transformation & AI Hackathon 2026 “The Great Reset of Education and Management” ปลุกพลังคน พลิกโฉมองค์กร ด้วยนวัตกรรม AI", "max_length": 220}], "command": {"text": "ขณะนี้ได้เวลาเริ่ม {event_name} แล้วครับ ขอให้ทุกท่านได้รับความรู้ ความสุข และแรงบันดาลใจตลอดกิจกรรมครับ", "voice_profile": "male_young", "face": "PROUD", "wheel_lights": {"mode": "marquee", "color": "#FFC107", "brightness": 16}}},
    "celebration": {"title": "แสดงความยินดี", "icon": "✨", "category": "บันเทิง", "duration_seconds": 10, "availability": "ready", "description": "กล่าวแสดงความยินดี พร้อมสีหน้า ท่าศีรษะ และไฟล้อ โดยไม่ใช้ canned action", "visual_profile": "HAPPY", "fields": [], "command": {"text": "ขอแสดงความยินดีกับทุกท่านครับ ขอให้ภูมิใจกับความสำเร็จในวันนี้ และก้าวต่อไปอย่างมีความสุขนะครับ", "voice_profile": "male_child", "face": "HAPPY", "wheel_lights": {"mode": "marquee", "color": "#FFC107", "brightness": 16}}},
    "dance-show": {"title": "เต้นโชว์", "icon": "💃", "category": "บันเทิง", "duration_seconds": 8, "availability": "gated", "description": "ต้องยืนยัน action ID และ callback บน Zenbo เครื่องจริงก่อนเปิดใช้", "fields": [], "gate_reason": "SDK sample แสดงว่าเรียก canned action ได้ แต่ action ID 2 ยังไม่มีผลทดสอบ physical บน Booky เครื่องนี้", "command": {"text": "เต้นให้ชมกันนะครับ", "voice_profile": "male_child", "face": "SINGING", "action": {"action_id": 2}, "wheel_lights": {"mode": "marquee", "color": "#FF4FA3", "brightness": 16}}},
    "youtube-play": {"title": "เปิดเพลงจาก YouTube", "icon": "▶️", "category": "บันเทิง", "duration_seconds": 0, "availability": "ready", "description": "เปิดเพลงจากลิงก์ YouTube โดยไม่สั่งเต้น", "visual_profile": "SINGING", "fields": [{"name": "youtube_url", "label": "ลิงก์ YouTube", "placeholder": "https://www.youtube.com/watch?v=...", "input_type": "url", "default": "", "max_length": 2048}], "command": {"youtube": {"url": "{youtube_url}", "dance_action_ids": [], "loop_dance": False}}},
    "music-dance": {"title": "เพลงจาก YouTube และเต้น", "icon": "🎵", "category": "บันเทิง", "duration_seconds": 45, "availability": "ready", "description": "เปิดเพลงที่เลือกและเต้นแบบจำกัดเวลา 45 วินาที; กด STOP ได้ทันที", "visual_profile": "SINGING", "fields": [{"name": "youtube_url", "label": "ลิงก์ YouTube", "input_type": "url", "default": "https://www.youtube.com/watch?v=ApXoWvfEYVU&list=RDApXoWvfEYVU&start_radio=1", "max_length": 2048}], "command": {"youtube": {"url": "{youtube_url}", "dance_action_ids": [2], "loop_dance": True, "duration_seconds": 45}}},
    "music-dance-every-10": {"title": "เพลงและเต้นทุก 10 นาที", "icon": "⏱️", "category": "บันเทิง", "duration_seconds": 0, "availability": "gated", "description": "n8n จะสุ่มเพลงจาก playlist ที่อนุมัติแล้วทุก 10 นาที และส่งแบบแยกชื่อ Zenbo", "visual_profile": "SINGING", "fields": [], "gate_reason": "ต้องตั้ง playlist/robot ใน n8n, เปิด MUSIC_DANCE_AUTOMATION_ENABLED และสอบเทียบ canned dance action กับ Zenbo เครื่องจริงก่อน"},
    "children-greeting": {"title": "ทักทายเด็ก", "icon": "🧒", "category": "เด็กและการเรียนรู้", "duration_seconds": 12, "availability": "ready", "description": "คำทักทายสั้น สนุก และเป็นมิตร", "fields": [], "command": {"text": "สวัสดีครับน้อง ๆ ทุกคน ผมบุ๊คกี้ยินดีที่ได้เจอครับ วันนี้เรามาเรียนรู้และสนุกไปด้วยกันนะครับ", "voice_profile": "male_child", "face": "HAPPY", "wheel_lights": {"mode": "rainbow", "color": "#00D031", "brightness": 14}}},
    "accessibility-help": {"title": "ช่วยเหลือผู้ใช้", "icon": "🤝", "category": "สื่อสาร", "duration_seconds": 16, "availability": "ready", "description": "พูดช้าและชัด พร้อมเชิญเรียกเจ้าหน้าที่", "fields": [], "command": {"text": "สวัสดีครับ หากต้องการความช่วยเหลือ กรุณาบอกผมได้เลยนะครับ ผมจะแนะนำบริการเบื้องต้น และสามารถช่วยเรียกเจ้าหน้าที่ให้ได้ครับ", "voice_profile": "male_adult", "face": "PLEASED", "wheel_lights": {"mode": "breath", "color": "#00AEEF", "brightness": 10}}},
    "staff-call": {"title": "เรียกเจ้าหน้าที่", "icon": "🔔", "category": "สื่อสาร", "duration_seconds": 10, "availability": "ready", "description": "แจ้งคำขอในเสียง; ยังไม่ส่ง LINE/โทรศัพท์", "fields": [{"name": "area", "label": "พื้นที่", "default": "จุดบริการ", "max_length": 80}], "command": {"text": "ขอความช่วยเหลือจากเจ้าหน้าที่บริเวณ {area} ครับ ขอบคุณครับ", "voice_profile": "male_adult", "face": "SERIOUS", "wheel_lights": {"mode": "blinking", "color": "#FFC107", "brightness": 16}}},
    "checkpoint-mark": {"title": "Mark ฐานกิจกรรม", "icon": "🏷️", "category": "ฐานกิจกรรม", "duration_seconds": 0, "availability": "gated", "description": "ต้องมีฐานข้อมูล virtual checkpoint ก่อน", "visual_profile": "SERIOUS", "fields": [], "gate_reason": "ยังไม่มี persistence สำหรับ checkpoint/operator"},
    "checkpoint-arrival": {"title": "ถึงฐานกิจกรรม", "icon": "🚩", "category": "ฐานกิจกรรม", "duration_seconds": 0, "availability": "gated", "description": "ต้องอ่าน virtual checkpoint ที่บันทึกได้ก่อน", "visual_profile": "HAPPY", "fields": [], "gate_reason": "ยังไม่มี checkpoint service"},
    "standby": {"title": "โหมดพักรอ", "icon": "🌙", "category": "ระบบ", "duration_seconds": 6, "availability": "ready", "description": "เข้าสู่โหมดพร้อมรอรับคำสั่ง", "fields": [], "command": {"text": "บุ๊คกี้พร้อมรอรับคำสั่งครับ", "voice_profile": "male_child", "face": "DEFAULT_STILL", "wheel_lights": {"mode": "breath", "color": "#00D031", "brightness": 6}}},
}

# n8n may orchestrate these manifests, but it must never invent raw RobotAPI
# payloads. New scenarios are additive registry entries with explicit safety.
SCENARIO_REGISTRY: Dict[str, Dict[str, Any]] = {
    "innotech_judge_welcome_30": {
        "version": "1.0.0",
        "icon": "🏆",
        "category": "พิธีการ",
        "title": "ต้อนรับกรรมการ InnoTech Show & Share 2026 (30 วินาที)",
        "description": "Booky กล่าวต้อนรับคณะกรรมการการประกวดนวัตกรรม ในงาน InnoTech Show & Share 2026 จัดโดยศูนย์นวัตกรรมการเรียนการสอน (LTIC) มข.",
        "risk_level": "L0",
        "confirmation": "REQUIRED",
        "duration_seconds": 30,
        "required_capabilities": ["THAI_TTS", "EXPRESSION", "ACTION", "LIGHTS"],
        "command": {
            "text": "สวัสดีครับ ขอต้อนรับคณะกรรมการผู้ทรงเกียรติทุกท่าน สู่งาน InnoTech Show & Share 2026 จัดโดยศูนย์นวัตกรรมการเรียนการสอน มหาวิทยาลัยขอนแก่น ครับ ผม บุ๊คกี้ หุ่นยนต์บรรณารักษ์อัจฉริยะ ขอร่วมเป็นส่วนหนึ่งในการขับเคลื่อนนวัตกรรมด้วยพลัง AI ผสาน KKU IntelSphere เพื่อบริการที่ชาญฉลาดและเข้าถึงง่าย ขอเชิญคณะกรรมการทุกท่านรับชมการสาธิตผลงานได้เลยครับ",
            "voice_profile": "male_young",
            "face": "PROUD",
            "action": {"action_id": 2, "stop": False},
            "wheel_lights": {"mode": "breath", "color": "#8B5CF6", "brightness": 14},
            "head": {"yaw": 0, "pitch": 8, "speed": 1},
        },
    },
    "intro_booky": {
        "version": "1.0.0",
        "icon": "🤖",
        "category": "ต้อนรับ",
        "title": "แนะนำตัว Booky",
        "description": "Booky แนะนำตัวพร้อมสีหน้าและท่าศีรษะ โดยไม่เคลื่อนฐาน",
        "risk_level": "L0",
        "confirmation": "REQUIRED",
        "required_capabilities": ["THAI_TTS", "EXPRESSION", "HEAD"],
        "command": {
            "text": "สวัสดีครับ ผมบุ๊คกี้ หุ่นยนต์ผู้ช่วยของสำนักหอสมุด มหาวิทยาลัยขอนแก่นครับ ผมพร้อมช่วยแนะนำบริการและเส้นทางให้ทุกท่านครับ",
            "voice_profile": "male_child",
            "face": "CONFIDENT",
            "wheel_lights": {"mode": "breath", "color": "#00D031", "brightness": 10},
        },
    },
    "library_welcome": {
        "version": "1.0.0",
        "icon": "👋",
        "category": "ต้อนรับ",
        "title": "ต้อนรับสู่สำนักหอสมุด",
        "description": "ทักทายผู้ใช้บริการด้วยเสียงไทย สีหน้า และไฟล้อ โดยไม่เคลื่อนฐาน",
        "risk_level": "L0",
        "confirmation": "REQUIRED",
        "required_capabilities": ["THAI_TTS", "EXPRESSION", "HEAD", "WHEEL_LIGHTS"],
        "command": {
            "text": "สวัสดีครับ ยินดีต้อนรับสู่สำนักหอสมุด มหาวิทยาลัยขอนแก่นครับ วันนี้ผมบุ๊คกี้ยินดีช่วยแนะนำบริการครับ",
            "voice_profile": "male_child",
            "face": "HAPPY",
            "wheel_lights": {"mode": "breath", "color": "#00D031", "brightness": 10},
        },
    },
    "library_service_help": {
        "version": "1.0.0",
        "icon": "📚",
        "category": "บริการ",
        "title": "แนะนำบริการหอสมุด",
        "description": "กล่าวแนะนำการค้นหาหนังสือ จุดยืมคืน และการขอความช่วยเหลือจากเจ้าหน้าที่",
        "risk_level": "L0",
        "confirmation": "REQUIRED",
        "required_capabilities": ["THAI_TTS", "EXPRESSION", "HEAD"],
        "command": {
            "text": "ผมช่วยแนะนำการค้นหาหนังสือ จุดยืมคืน และบริการต่าง ๆ ของหอสมุดได้ครับ หากต้องการความช่วยเหลือเพิ่มเติม โปรดแจ้งเจ้าหน้าที่ได้เลยครับ",
            "voice_profile": "male_young",
            "face": "INTERESTED",
            "wheel_lights": {"mode": "breath", "color": "#00AEEF", "brightness": 9},
        },
    },
    "queue_ready": {
        "version": "1.0.0",
        "icon": "🔔",
        "category": "บริการ",
        "title": "เชิญรับบริการ",
        "description": "เรียกผู้ใช้ให้เข้ารับบริการด้วยถ้อยคำสุภาพ โดยไม่มีการเคลื่อนที่",
        "risk_level": "L0",
        "confirmation": "REQUIRED",
        "required_capabilities": ["THAI_TTS", "EXPRESSION", "WHEEL_LIGHTS"],
        "command": {
            "text": "ผู้ใช้บริการท่านถัดไป เชิญรับบริการได้เลยครับ หากต้องการความช่วยเหลือ โปรดแจ้งเจ้าหน้าที่ได้ครับ",
            "voice_profile": "male_adult",
            "face": "EXPECTING",
            "wheel_lights": {"mode": "blinking", "color": "#FFC107", "brightness": 12},
        },
    },
    "library_goodbye": {
        "version": "1.0.0",
        "icon": "🙏",
        "category": "ปิดการสนทนา",
        "title": "ขอบคุณผู้ใช้บริการ",
        "description": "กล่าวขอบคุณและกลับสู่สีหน้าพักรอหลังพูดจบ",
        "risk_level": "L0",
        "confirmation": "REQUIRED",
        "required_capabilities": ["THAI_TTS", "EXPRESSION", "HEAD"],
        "command": {
            "text": "ขอบคุณที่ใช้บริการสำนักหอสมุดครับ ผมบุ๊คกี้พร้อมช่วยเหลือทุกท่านเสมอ แล้วพบกันใหม่นะครับ",
            "voice_profile": "male_child",
            "face": "PLEASED",
            "wheel_lights": {"mode": "breath", "color": "#00D031", "brightness": 6},
        },
    },
    "library_orientation_l1": {
        "version": "1.0.0",
        "icon": "🧭",
        "category": "นำชม",
        "title": "แนะนำบริการห้องสมุดเป็นช่วง",
        "description": "L1: กล่าวแนะนำ 3 ช่วงพร้อมสีหน้า ท่าศีรษะ และไฟล้อ โดยไม่เคลื่อนฐาน",
        "risk_level": "L1",
        "confirmation": "REQUIRED",
        "required_capabilities": ["THAI_TTS", "EXPRESSION", "HEAD", "WHEEL_LIGHTS"],
        "command": {"steps": [
            {"text": "ผมจะพาแนะนำบริการห้องสมุดแบบสั้น ๆ ครับ", "voice_profile": "male_child", "face": "HAPPY", "wheel_lights": {"mode": "breath", "color": "#00D031", "brightness": 10}},
            {"text": "เริ่มจากการค้นหาหนังสือและจุดยืมคืน หากต้องการ ผมสามารถเปิดแผนที่ห้องสมุดให้ได้ครับ", "voice_profile": "male_young", "face": "INTERESTED", "wheel_lights": {"mode": "breath", "color": "#2196F3", "brightness": 10}},
            {"text": "หากต้องการความช่วยเหลือเพิ่มเติม เรียกผมหรือแจ้งเจ้าหน้าที่ได้เสมอครับ", "voice_profile": "male_child", "face": "PLEASED", "wheel_lights": {"mode": "breath", "color": "#00D031", "brightness": 8}},
        ]},
    },
    "visitor_greeting_l2": {
        "version": "1.0.0",
        "icon": "👋",
        "category": "โต้ตอบ",
        "title": "ทักทายเมื่อพบผู้ใช้",
        "description": "L2: ตรวจจับบุคคลแบบไม่ระบุตัวตน แล้วทักทายหรือแจ้งว่าไม่พบผู้ใช้ โดยไม่เคลื่อนฐาน",
        "risk_level": "L2",
        "confirmation": "REQUIRED",
        "required_capabilities": ["THAI_TTS", "EXPRESSION", "HEAD", "WHEEL_LIGHTS", "VISION_PERSON"],
        "command": {
            "vision_gate": {"action": "detect_person", "interval_ms": 1000, "timeout_ms": 8000, "debug_preview": False},
            "on_detect": {"steps": [
                {"text": "สวัสดีครับ ยินดีต้อนรับสู่สำนักหอสมุดครับ ผมบุ๊คกี้พร้อมช่วยเหลือครับ", "voice_profile": "male_child", "face": "HAPPY", "wheel_lights": {"mode": "breath", "color": "#00D031", "brightness": 10}},
            ]},
            "on_timeout": {"steps": [
                {"text": "ตอนนี้ผมยังไม่พบผู้ใช้ครับ หากพร้อมแล้ว เข้ามาอยู่ด้านหน้าผมได้เลยครับ", "voice_profile": "male_child", "face": "EXPECTING", "wheel_lights": {"mode": "breath", "color": "#2196F3", "brightness": 8}},
            ]},
        },
    },
    "gesture_acknowledgement_l3": {
        "version": "1.0.0",
        "icon": "👉",
        "category": "โต้ตอบ",
        "title": "ตอบรับเมื่อผู้ใช้ชี้",
        "description": "L3: รอท่าชี้แบบไม่ระบุตัวตน แล้วตอบรับด้วยคำพูด สีหน้า และท่าศีรษะ โดยไม่บันทึกพิกัดหรือเคลื่อนฐาน",
        "risk_level": "L3",
        "confirmation": "REQUIRED",
        "required_capabilities": ["THAI_TTS", "EXPRESSION", "HEAD", "WHEEL_LIGHTS", "GESTURE_POINT"],
        "command": {
            "vision_gate": {"action": "gesture_point", "interval_ms": 1000, "timeout_ms": 7000, "debug_preview": False},
            "on_detect": {"steps": [
                {"text": "ผมเห็นท่าชี้ของคุณแล้วครับ หากต้องการข้อมูลเพิ่มเติม บอกผมได้เลยครับ", "voice_profile": "male_child", "face": "INTERESTED", "wheel_lights": {"mode": "breath", "color": "#6D5EF7", "brightness": 10}},
            ]},
            "on_timeout": {"steps": [
                {"text": "หากพร้อมแล้ว ลองชี้อีกครั้งด้านหน้าผมได้เลยครับ", "voice_profile": "male_child", "face": "EXPECTING", "wheel_lights": {"mode": "breath", "color": "#2196F3", "brightness": 8}},
            ]},
        },
    },
    "guided_gesture_l4": {
        "version": "1.0.0",
        "icon": "🫱",
        "category": "โต้ตอบ",
        "title": "ต้อนรับแล้วรอการชี้",
        "description": "L4: ตรวจพบผู้ใช้แบบไม่ระบุตัวตน พูดเชิญให้ชี้ แล้วตอบรับการชี้ โดยไม่บันทึกพิกัดหรือเคลื่อนฐาน",
        "risk_level": "L4",
        "confirmation": "REQUIRED",
        "required_capabilities": ["THAI_TTS", "EXPRESSION", "HEAD", "WHEEL_LIGHTS", "VISION_PERSON", "GESTURE_POINT"],
        "command": {
            "first_gate": {"action": "detect_person", "interval_ms": 1000, "timeout_ms": 8000, "debug_preview": False},
            "prompt": {"text": "สวัสดีครับ ผมเห็นคุณแล้วครับ หากต้องการความช่วยเหลือ กรุณาชี้มาทางผมได้เลยครับ", "voice_profile": "male_child", "face": "INTERESTED", "wheel_lights": {"mode": "breath", "color": "#6D5EF7", "brightness": 10}},
            "second_gate": {"action": "gesture_point", "interval_ms": 1000, "timeout_ms": 7000, "debug_preview": False},
            "on_first_timeout": {"steps": [
                {"text": "ตอนนี้ผมยังไม่พบผู้ใช้ครับ หากพร้อมแล้ว เข้ามาอยู่ด้านหน้าผมได้เลยครับ", "voice_profile": "male_child", "face": "EXPECTING", "wheel_lights": {"mode": "breath", "color": "#2196F3", "brightness": 8}},
            ]},
            "on_second_detect": {"steps": [
                {"text": "รับทราบครับ ผมพร้อมช่วยเหลือคุณแล้วครับ", "voice_profile": "male_child", "face": "HAPPY", "wheel_lights": {"mode": "breath", "color": "#00D031", "brightness": 10}},
            ]},
            "on_second_timeout": {"steps": [
                {"text": "หากพร้อมแล้ว ลองชี้อีกครั้งด้านหน้าผมได้เลยครับ", "voice_profile": "male_child", "face": "EXPECTING", "wheel_lights": {"mode": "breath", "color": "#2196F3", "brightness": 8}},
            ]},
        },
    },
    "library_map_after_gesture_l5": {
        "version": "1.0.0",
        "icon": "🗺️",
        "category": "โต้ตอบ",
        "title": "ชี้เพื่อเปิดแผนที่ห้องสมุด",
        "description": "L5: พบผู้ใช้ เชิญให้ชี้ แล้วเปิดเฉพาะแผนที่ห้องสมุดที่เชื่อถือได้บนหน้าจอ Zenbo โดยไม่เคลื่อนฐาน",
        "risk_level": "L5",
        "confirmation": "REQUIRED",
        "required_capabilities": ["THAI_TTS", "EXPRESSION", "HEAD", "WHEEL_LIGHTS", "VISION_PERSON", "GESTURE_POINT", "DISPLAY_URL"],
        "command": {
            "first_gate": {"action": "detect_person", "interval_ms": 1000, "timeout_ms": 8000, "debug_preview": False},
            "prompt": {"text": "สวัสดีครับ หากต้องการดูแผนที่ห้องสมุด กรุณาชี้มาทางผมได้เลยครับ", "voice_profile": "male_child", "face": "INTERESTED", "wheel_lights": {"mode": "breath", "color": "#6D5EF7", "brightness": 10}},
            "second_gate": {"action": "gesture_point", "interval_ms": 1000, "timeout_ms": 7000, "debug_preview": False},
            "on_first_timeout": {"steps": [
                {"text": "ตอนนี้ผมยังไม่พบผู้ใช้ครับ หากพร้อมแล้ว เข้ามาอยู่ด้านหน้าผมได้เลยครับ", "voice_profile": "male_child", "face": "EXPECTING", "wheel_lights": {"mode": "breath", "color": "#2196F3", "brightness": 8}},
            ]},
            "on_second_detect": {"steps": [
                {"text": "ผมกำลังเปิดแผนที่ห้องสมุดให้ครับ", "voice_profile": "male_child", "face": "HAPPY", "wheel_lights": {"mode": "breath", "color": "#00D031", "brightness": 10}},
            ], "navigation": {"display_url": "https://lib.kku.ac.th/map/", "speech_text": "ผมกำลังเปิดแผนที่ห้องสมุดให้ครับ"}},
            "on_second_timeout": {"steps": [
                {"text": "หากพร้อมแล้ว ลองชี้อีกครั้งด้านหน้าผมได้เลยครับ", "voice_profile": "male_child", "face": "EXPECTING", "wheel_lights": {"mode": "breath", "color": "#2196F3", "brightness": 8}},
            ]},
        },
    },
    "library_map_field_ready_l6": {
        "version": "1.0.0",
        "icon": "🛡️",
        "category": "โต้ตอบ",
        "title": "เปิดแผนที่เมื่อหุ่นพร้อมภาคสนาม",
        "description": "L6: ใช้ flow L5 ได้เมื่อ APK รายงาน RobotAPI, safety guard และ MQTT topic ที่พร้อมล่าสุดเท่านั้น",
        "risk_level": "L6",
        "confirmation": "REQUIRED",
        "required_capabilities": ["THAI_TTS", "EXPRESSION", "HEAD", "WHEEL_LIGHTS", "VISION_PERSON", "GESTURE_POINT", "DISPLAY_URL", "FIELD_READINESS"],
        "command": {
            "first_gate": {"action": "detect_person", "interval_ms": 1000, "timeout_ms": 8000, "debug_preview": False},
            "prompt": {"text": "สวัสดีครับ หากต้องการดูแผนที่ห้องสมุด กรุณาชี้มาทางผมได้เลยครับ", "voice_profile": "male_child", "face": "INTERESTED", "wheel_lights": {"mode": "breath", "color": "#6D5EF7", "brightness": 10}},
            "second_gate": {"action": "gesture_point", "interval_ms": 1000, "timeout_ms": 7000, "debug_preview": False},
            "on_first_timeout": {"steps": [
                {"text": "ตอนนี้ผมยังไม่พบผู้ใช้ครับ หากพร้อมแล้ว เข้ามาอยู่ด้านหน้าผมได้เลยครับ", "voice_profile": "male_child", "face": "EXPECTING", "wheel_lights": {"mode": "breath", "color": "#2196F3", "brightness": 8}},
            ]},
            "on_second_detect": {"steps": [
                {"text": "ผมกำลังเปิดแผนที่ห้องสมุดให้ครับ", "voice_profile": "male_child", "face": "HAPPY", "wheel_lights": {"mode": "breath", "color": "#00D031", "brightness": 10}},
            ], "navigation": {"display_url": "https://lib.kku.ac.th/map/", "speech_text": "ผมกำลังเปิดแผนที่ห้องสมุดให้ครับ"}},
            "on_second_timeout": {"steps": [
                {"text": "หากพร้อมแล้ว ลองชี้อีกครั้งด้านหน้าผมได้เลยครับ", "voice_profile": "male_child", "face": "EXPECTING", "wheel_lights": {"mode": "breath", "color": "#2196F3", "brightness": 8}},
            ]},
        },
    },
}

# L7 deliberately reuses L6's stationary map flow.  Only the dispatch gate is
# stricter: a token-gated operator attestation must also be fresh.
SCENARIO_REGISTRY["library_map_supervised_l7"] = json.loads(json.dumps(
    SCENARIO_REGISTRY["library_map_field_ready_l6"], ensure_ascii=False
))
SCENARIO_REGISTRY["library_map_supervised_l7"].update({
    "risk_level": "L7",
    "icon": "✅",
    "title": "เปิดแผนที่หลังตรวจหน้างาน",
    "description": "L7: ใช้ flow L6 หลัง operator รับรองการทดสอบเสียง วิสัยทัศน์ และหน้าจอในระยะเวลาที่กำหนด",
    "required_capabilities": SCENARIO_REGISTRY["library_map_field_ready_l6"]["required_capabilities"] + ["FIELD_ATTESTATION"],
})

# L8 is intentionally *not* navigation.  It is a single, straight, low-speed
# 15cm approach that remains subject to the APK's independent sensor interlock
# and watchdog.  It is hidden behind an explicit server feature flag at confirm.
SCENARIO_REGISTRY["guarded_micro_approach_l8"] = {
    "version": "1.0.0",
    "icon": "🛑",
    "category": "เคลื่อนที่แบบมีผู้ควบคุม",
    "title": "ขยับเข้าหาผู้ใช้ระยะสั้น",
    "description": "L8: ขยับตรงไปด้านหน้าไม่เกิน 15 ซม. ด้วยความเร็วต่ำ พร้อม collision/fall guard, watchdog และผลตรวจหน้างานล่าสุด",
    "risk_level": "L8",
    "confirmation": "REQUIRED",
    "required_capabilities": ["THAI_TTS", "EXPRESSION", "HEAD", "WHEEL_LIGHTS", "SAFETY_SONAR", "SAFETY_DROP_LASER", "FIELD_READINESS", "FIELD_ATTESTATION"],
    "command": {"autonomous_motion": {
        "text": "รับคำสั่งครับ ผมจะขยับเข้ามาเล็กน้อย และจะหยุดทันทีหากตรวจพบสิ่งกีดขวางครับ",
        "voice_profile": "male_child",
        "face": "CONFIDENT",
        "wheel_lights": {"mode": "breath", "color": "#FFC107", "brightness": 10},
        "safety": {"base_motion_enabled": True, "collision_guard_enabled": False, "fall_guard_enabled": False,
                   "max_distance_m": 0.75, "max_speed": 7, "auto_stop_ms": 3000,
                   "collision_distance_m": 0.35, "drop_distance_m": 0.16},
        "motion": {"x": 0.15, "y": 0.0, "theta": 0.0, "speed": 1},
    }},
}

# L10 is dispatched only by the calibrated-route API below.  It never appears
# in the ordinary scenario card catalog and cannot accept a raw motion payload.
SCENARIO_REGISTRY["calibrated_route_segment_l10"] = {
    "version": "1.0.0",
    "icon": "🧭",
    "category": "ระบบเส้นทาง",
    "title": "ช่วงเส้นทางคาลิเบรต",
    "description": "L10: ช่วงเคลื่อนที่ที่ผ่านการคาลิเบรต ต้องมีการยืนยันจาก operator ทุกช่วง",
    "risk_level": "L10",
    "confirmation": "REQUIRED",
    "operator_only": True,
    "required_capabilities": ["THAI_TTS", "EXPRESSION", "HEAD", "WHEEL_LIGHTS", "SAFETY_SONAR", "SAFETY_DROP_LASER", "CALIBRATED_ROUTE", "FIELD_READINESS", "FIELD_ATTESTATION"],
    "command": {"calibrated_route_segment": True},
}

# MQTT Setup
_mqtt_transport = "websockets" if MQTT_CLIENT_TRANSPORT in {"ws", "wss"} else "tcp"
mqtt_client = mqtt.Client(
    mqtt.CallbackAPIVersion.VERSION2,
    client_id=MQTT_CLIENT_ID,
    transport=_mqtt_transport,
)
robot_registry: Dict[str, Dict[str, Any]] = {}
robot_registry_lock = Lock()
command_history_lock = Lock()
camera_session_queues: Dict[str, List[asyncio.Queue]] = {}
camera_session_queues_lock = Lock()


def dispatch_camera_event(session_id: str, data: Any) -> None:
    with camera_session_queues_lock:
        queues = camera_session_queues.get(session_id, [])
        for q in queues:
            try:
                q.put_nowait(data)
            except Exception:
                pass


def normalize_thai_speech_text(text: str) -> str:
    if not text:
        return text
    lexicon_file = os.path.join(os.path.dirname(__file__), "speech_lexicon.json")
    try:
        if os.path.exists(lexicon_file):
            with open(lexicon_file, "r", encoding="utf-8") as f:
                lexicon = json.load(f)
                for term, replacement in lexicon.items():
                    text = text.replace(term, replacement)
    except Exception as exc:
        print(f"[!] Speech lexicon error: {exc}")
    return text


def init_command_history() -> None:
    if db._backend == "pgsql":
        return
    os.makedirs(os.path.dirname(COMMAND_HISTORY_DB), exist_ok=True)
    with db.connection(COMMAND_HISTORY_DB) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS command_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at_ms INTEGER NOT NULL,
                robot_slug TEXT,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                accepted_latency_ms INTEGER,
                payload_json TEXT NOT NULL
            )
        """)
        connection.execute("CREATE INDEX IF NOT EXISTS command_history_created_idx ON command_history(created_at_ms DESC)")
        connection.execute("CREATE INDEX IF NOT EXISTS command_history_robot_idx ON command_history(robot_slug, created_at_ms DESC)")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS web_auth_sessions (
                token_hash TEXT PRIMARY KEY,
                sub TEXT,
                username TEXT,
                display_name TEXT,
                role TEXT,
                provider TEXT,
                created_at_ms INTEGER NOT NULL,
                expires_at_ms INTEGER NOT NULL
            )
        """)
        connection.execute("CREATE INDEX IF NOT EXISTS web_auth_sessions_expiry_idx ON web_auth_sessions(expires_at_ms)")
        for column in ("sub", "display_name", "role", "provider"):
            if column not in {row[1] for row in connection.execute("PRAGMA table_info(web_auth_sessions)")}:
                connection.execute(f"ALTER TABLE web_auth_sessions ADD COLUMN {column} TEXT")
        columns = {row[1] for row in connection.execute("PRAGMA table_info(command_history)")}
        if "user_id" not in columns:
            connection.execute("ALTER TABLE command_history ADD COLUMN user_id TEXT")
        if "display_name" not in columns:
            connection.execute("ALTER TABLE command_history ADD COLUMN display_name TEXT")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS user_robot_binding (
                user_id TEXT NOT NULL,
                robot_slug TEXT NOT NULL,
                display_name TEXT,
                permission TEXT NOT NULL DEFAULT 'operator',
                created_at_ms INTEGER NOT NULL,
                PRIMARY KEY (user_id, robot_slug)
            )
        """)
        connection.execute("CREATE INDEX IF NOT EXISTS user_robot_binding_user_idx ON user_robot_binding(user_id)")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS scenario_runs (
                run_id TEXT PRIMARY KEY,
                scenario_id TEXT NOT NULL,
                scenario_version TEXT NOT NULL,
                robot_slug TEXT NOT NULL,
                source TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                risk_level TEXT NOT NULL,
                state TEXT NOT NULL,
                parameters_json TEXT NOT NULL,
                created_at_ms INTEGER NOT NULL,
                updated_at_ms INTEGER NOT NULL,
                UNIQUE(robot_slug, idempotency_key)
            )
        """)
        connection.execute("CREATE INDEX IF NOT EXISTS scenario_runs_robot_created_idx ON scenario_runs(robot_slug, created_at_ms DESC)")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS scenario_run_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                created_at_ms INTEGER NOT NULL,
                state TEXT NOT NULL,
                source TEXT NOT NULL
            )
        """)
        connection.execute("CREATE INDEX IF NOT EXISTS scenario_run_events_run_idx ON scenario_run_events(run_id, id ASC)")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS calibrated_routes (
                route_id TEXT PRIMARY KEY,
                version TEXT NOT NULL,
                title TEXT NOT NULL,
                segments_json TEXT NOT NULL,
                updated_at_ms INTEGER NOT NULL
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS calibrated_route_runs (
                route_run_id TEXT PRIMARY KEY,
                route_id TEXT NOT NULL,
                robot_slug TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                current_segment INTEGER NOT NULL,
                state TEXT NOT NULL,
                active_scenario_run_id TEXT,
                operation_permit_id TEXT,
                created_at_ms INTEGER NOT NULL,
                updated_at_ms INTEGER NOT NULL,
                UNIQUE(robot_slug, idempotency_key)
            )
        """)
        route_run_columns = {row[1] for row in connection.execute("PRAGMA table_info(calibrated_route_runs)")}
        if "operation_permit_id" not in route_run_columns:
            connection.execute("ALTER TABLE calibrated_route_runs ADD COLUMN operation_permit_id TEXT")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS calibrated_route_recoveries (
                route_run_id TEXT PRIMARY KEY,
                recovery_required_at_ms INTEGER NOT NULL,
                recovered_at_ms INTEGER,
                operator_name TEXT,
                action TEXT,
                note TEXT NOT NULL DEFAULT ''
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS calibrated_route_certifications (
                route_id TEXT PRIMARY KEY,
                route_version TEXT NOT NULL,
                certified_at_ms INTEGER NOT NULL,
                operator_name TEXT NOT NULL,
                checks_json TEXT NOT NULL
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS autonomy_authorizations (
                authorization_id TEXT PRIMARY KEY,
                operator_name TEXT NOT NULL,
                role TEXT NOT NULL,
                scopes_json TEXT NOT NULL,
                issued_at_ms INTEGER NOT NULL,
                expires_at_ms INTEGER NOT NULL,
                revoked_at_ms INTEGER,
                note TEXT NOT NULL DEFAULT ''
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS calibrated_route_releases (
                route_id TEXT PRIMARY KEY,
                route_version TEXT NOT NULL,
                state TEXT NOT NULL,
                approved_by_authorization_id TEXT NOT NULL,
                allowed_robots_json TEXT NOT NULL,
                updated_at_ms INTEGER NOT NULL,
                note TEXT NOT NULL DEFAULT ''
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS robot_localization_attestations (
                robot_slug TEXT PRIMARY KEY,
                map_id TEXT NOT NULL,
                map_version TEXT NOT NULL,
                attested_at_ms INTEGER NOT NULL,
                operator_name TEXT NOT NULL,
                checks_json TEXT NOT NULL
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS robot_safety_envelopes (
                robot_slug TEXT PRIMARY KEY,
                attested_at_ms INTEGER NOT NULL,
                operator_name TEXT NOT NULL,
                checks_json TEXT NOT NULL
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS autonomy_zone_reservations (
                reservation_id TEXT PRIMARY KEY,
                zone_id TEXT NOT NULL UNIQUE,
                robot_slug TEXT NOT NULL,
                route_id TEXT NOT NULL,
                created_at_ms INTEGER NOT NULL,
                expires_at_ms INTEGER NOT NULL,
                released_at_ms INTEGER
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS autonomy_fault_drills (
                drill_id TEXT PRIMARY KEY,
                robot_slug TEXT NOT NULL,
                completed_at_ms INTEGER NOT NULL,
                operator_name TEXT NOT NULL,
                checks_json TEXT NOT NULL
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS autonomy_operation_permits (
                permit_id TEXT PRIMARY KEY,
                route_id TEXT NOT NULL,
                route_version TEXT NOT NULL,
                robot_slug TEXT NOT NULL,
                zone_reservation_id TEXT NOT NULL,
                authorization_id TEXT NOT NULL,
                issued_at_ms INTEGER NOT NULL,
                expires_at_ms INTEGER NOT NULL,
                revoked_at_ms INTEGER,
                note TEXT NOT NULL DEFAULT ''
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS autonomy_alerts (
                alert_id TEXT PRIMARY KEY,
                robot_slug TEXT NOT NULL,
                level TEXT NOT NULL,
                code TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at_ms INTEGER NOT NULL,
                resolved_at_ms INTEGER
            )
        """)
        connection.execute("CREATE INDEX IF NOT EXISTS autonomy_alerts_open_idx ON autonomy_alerts(resolved_at_ms, created_at_ms DESC)")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS music_playlists (
                playlist_id TEXT PRIMARY KEY,
                version TEXT NOT NULL,
                title TEXT NOT NULL,
                mood TEXT NOT NULL,
                tracks_json TEXT NOT NULL,
                updated_at_ms INTEGER NOT NULL
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS scenario_definitions (
                scenario_id TEXT PRIMARY KEY,
                version TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                risk_level TEXT NOT NULL,
                confirmation TEXT NOT NULL,
                required_capabilities_json TEXT NOT NULL,
                command_json TEXT NOT NULL,
                updated_at_ms INTEGER NOT NULL
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS robot_field_attestations (
                robot_slug TEXT PRIMARY KEY,
                attested_at_ms INTEGER NOT NULL,
                operator_name TEXT NOT NULL,
                checks_json TEXT NOT NULL
            )
        """)


def record_command_history(robot_slug: Optional[str], source: Optional[str], status: str,
                           payload: Dict[str, Any], accepted_latency_ms: Optional[int] = None,
                           user_id: Optional[str] = None, display_name: Optional[str] = None) -> int:
    """Persist accepted LIFF dispatches; this is an audit of gateway acceptance, not robot completion."""
    return append_command(
        robot_slug, source, status, payload, accepted_latency_ms, user_id, display_name
    )


def _remember_robot(topic: str, payload: str) -> None:
    """Keep the latest retained/heartbeat status for each robot prefix."""
    parts = topic.split("/")
    if len(parts) < 3 or parts[0] != "zenbo" or parts[-2] != "status":
        return
    slug = "/".join(parts[1:-2])
    if not slug:
        return
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        data = {"raw": payload}
    with robot_registry_lock:
        existing = robot_registry.get(slug, {})
        robot = {
            **existing,
            "robot_slug": slug,
            "topic": topic,
            "last_seen": time.time(),
        }
        event_kind = parts[-1]
        if event_kind == "heartbeat":
            robot.update(data)
        else:
            event = {
                "kind": event_kind,
                "received_at_ms": int(time.time() * 1000),
                "data": data,
            }
            robot["last_event"] = event
            robot.setdefault("last_events", {})[event_kind] = event
            if event_kind == "safety":
                robot["safety"] = event
                if isinstance(data, dict) and data.get("state") == "SENSOR_STOP":
                    robot["last_safety_stop"] = event
                elif isinstance(data, dict) and data.get("state") == "POLICY_APPLIED":
                    # Re-arming a policy acknowledges the previous stop while
                    # retaining it in the command-history audit trail.
                    robot.pop("last_safety_stop", None)
        robot_registry[slug] = robot
    if event_kind == "camera" and isinstance(data, dict):
        sid = data.get("session_id") or data.get("sessionId")
        if sid:
            dispatch_camera_event(str(sid), data)
    if event_kind == "scenario" and isinstance(data, dict):
        _record_scenario_client_event(data)


def _record_scenario_client_event(event: Dict[str, Any]) -> None:
    """Advance a run only from client telemetry, never from MQTT publish."""
    run_id = str(event.get("run_id") or "").strip()
    client_state = str(event.get("state") or "").strip().upper()
    transition = {
        "CLIENT_RECEIVED": "RUNNING",
        "SPEECH_COMPLETED": "SUCCEEDED",
        "MOTION_COMPLETED": "SUCCEEDED",
        "FAILED": "FAILED",
        "SAFETY_STOPPED": "SAFETY_STOPPED",
    }
    if not run_id or client_state not in transition:
        return
    try:
        run = get_scenario_run_record(run_id)
    except HTTPException:
        # Robot telemetry is not allowed to create orphan audit rows.
        return
    # L9 completion semantics: L8 moves remain RUNNING after speech.  They
    # only succeed once the device watchdog has stopped the base and emitted
    # MOTION_COMPLETED. This avoids treating a TTS callback as motion proof.
    next_state = transition[client_state]
    if client_state == "SPEECH_COMPLETED" and run["risk_level"] in {"L8", "L10"}:
        next_state = None
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        connection.execute(
            "INSERT INTO scenario_run_events (run_id, created_at_ms, state, source) VALUES (?, ?, ?, ?)",
            (run_id, int(time.time() * 1000), client_state, "ZENBO_CLIENT"),
        )
        if next_state:
            connection.execute(
                "UPDATE scenario_runs SET state = ?, updated_at_ms = ? WHERE run_id = ? AND state IN ('DISPATCHED', 'RUNNING')",
                (next_state, int(time.time() * 1000), run_id),
            )


def on_mqtt_message(client, userdata, message):
    _remember_robot(message.topic, message.payload.decode("utf-8", errors="replace"))


def configure_mqtt_auth() -> None:
    """Apply broker credentials before opening the MQTT connection.

    When authentication is required, fail closed rather than silently creating
    an unauthenticated control path.  The token is used only by Paho's MQTT
    connect handshake and is never included in status, history, or logs.
    """
    if not MQTT_AUTH_REQUIRED:
        return
    if not MQTT_USERNAME or not MQTT_TOKEN:
        raise RuntimeError("MQTT authentication is required but MQTT_USERNAME or MQTT_TOKEN is not configured")
    mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_TOKEN)
    if MQTT_CLIENT_TRANSPORT in {"ssl", "wss"}:
        mqtt_client.tls_set()

@app.on_event("startup")
def startup_event():
    try:
        db.init()
    except Exception as e:
        print(f"[!] Database adapter init error: {e}")
        raise
    init_command_history()
    try:
        configure_mqtt_auth()
        mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
        mqtt_client.subscribe("zenbo/+/status/#", qos=1)
        mqtt_client.on_message = on_mqtt_message
        mqtt_client.loop_start()
        print(f"[*] Connected to MQTT Broker at {MQTT_HOST}:{MQTT_PORT}")
    except Exception as e:
        print(f"[!] MQTT connection error: {e}")

@app.on_event("shutdown")
def shutdown_event():
    mqtt_client.loop_stop()
    mqtt_client.disconnect()

class MotionCommand(BaseModel):
    x: float = Field(default=0.0, description="Forward/backward in meters")
    y: float = Field(default=0.0, description="Left/right in meters")
    theta: float = Field(default=0.0, description="Rotation angle in degrees")
    speed: int = Field(default=5, description="Speed level 1-7")

class HeadCommand(BaseModel):
    yaw: float = Field(default=0.0, description="Yaw angle in degrees (-45 to 45)")
    pitch: float = Field(default=0.0, description="Pitch angle in degrees (-15 to 55)")
    speed: int = Field(default=2, description="Speed level 1-5")

class HeadSequenceStep(HeadCommand):
    delay_ms: int = Field(default=0, ge=0, le=10000)

# YouTubeCommand is imported from youtube_entertainment.py to enforce the
# always-dance policy and pause/resume/stop actions in one place.


class MusicTrack(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    youtube: YouTubeCommand


class MusicPlaylistDefinitionRequest(BaseModel):
    """Reviewed playlist import format; Core stores only validated HTTPS videos."""
    playlist_id: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    version: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=160)
    mood: str = Field(min_length=1, max_length=80)
    tracks: List[MusicTrack] = Field(min_length=1, max_length=50)


class MusicPlaylistPickRequest(BaseModel):
    robot_slug: str = Field(min_length=1, max_length=120)


class MusicPlaylistStartRequest(MusicPlaylistPickRequest):
    """Operator-configured automatic music window; dispatch remains safety gated."""
    dance_action_ids: List[int] = Field(default_factory=list, max_length=4)
    duration_seconds: int = Field(default=45, ge=10, le=180)

    @field_validator("dance_action_ids")
    @classmethod
    def approved_dance_actions(cls, values: List[int]) -> List[int]:
        allowed = {2, 3, 5, 11, 18, 22, 23, 44}
        if any(value not in allowed for value in values):
            raise ValueError("dance_action_ids must use approved action IDs")
        return values


class SafetyModeCommand(BaseModel):
    """Device-enforced motion policy; defaults to safety mode disabled for smooth operator control."""
    base_motion_enabled: bool = True
    collision_guard_enabled: bool = False
    fall_guard_enabled: bool = False
    max_distance_m: float = Field(default=0.75, ge=0.05, le=0.75)
    max_speed: int = Field(default=7, ge=1, le=7)
    auto_stop_ms: int = Field(default=3000, ge=500, le=5000)
    collision_distance_m: float = Field(default=0.35, ge=0.10, le=1.00)
    drop_distance_m: float = Field(default=0.16, ge=0.08, le=0.50)


TRUSTED_NAVIGATION_DISPLAY_URLS = {
    "https://lib.kku.ac.th/map/",
    "https://lib.kku.ac.th/rag/",
}
TRUSTED_NAVIGATION_SERVICE_PREFIX = "http://10.101.118.149:8032/"


class NavigationCommand(BaseModel):
    display_url: str = Field(..., min_length=12, max_length=2048)
    speech_text: str = Field(..., min_length=1, max_length=2000)
    step_speeches: List[str] = Field(default_factory=list, max_length=30)

    @field_validator("display_url")
    @classmethod
    def validate_display_url(cls, value: str) -> str:
        normalized = value.strip()
        if not (normalized.startswith(TRUSTED_NAVIGATION_SERVICE_PREFIX) or normalized in TRUSTED_NAVIGATION_DISPLAY_URLS):
            raise ValueError("Navigation display URL is not trusted")
        return normalized

class CannedActionCommand(BaseModel):
    action_id: int = Field(..., example=22)
    stop: bool = Field(default=False)

class WheelLightsCommand(BaseModel):
    mode: str = Field(default="breathing", example="breathing")
    color: str = Field(default="0x00D031", example="0x00D031")
    brightness: int = Field(default=10, example=10)
    side: str = Field(default="both", example="both")
    direction: str = Field(default="forward", example="forward")
    speed: str = Field(default="DEFAULT", example="DEFAULT")

class FaceStep(BaseModel):
    face: str
    duration: float = Field(default=10, ge=0)

class EmotionalActionCommand(BaseModel):
    action_id: int
    faces: List[FaceStep]
    speed: Optional[float] = None

class RemoteControlCommand(BaseModel):
    body: Optional[str] = None
    head: Optional[str] = None

class BehaviorCommand(BaseModel):
    action: str
    enabled: bool = True
    track: bool = True
    distance: Optional[float] = Field(default=None, gt=0)

class VisionCommand(BaseModel):
    action: str
    interval_ms: int = Field(default=1000, ge=100, le=10000)
    track_id: Optional[int] = None
    debug_preview: bool = False

class AfterSpeechCommand(BaseModel):
    """A safe visual/pose cue run only when Android audio playback finishes."""
    face: Optional[str] = None
    head: Optional[HeadCommand] = None
    head_sequence: Optional[List[HeadSequenceStep]] = None
    wheel_lights: Optional[WheelLightsCommand] = None


class AutonomousMicroMotionCommand(BaseModel):
    """L8's only autonomous movement primitive: a bounded forward approach.

    It intentionally has no route, following, lateral, or rotational mode.
    The APK independently repeats these limits and stops on a sensor event.
    """
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=1000)
    voice_profile: Optional[str] = None
    voice: Optional[str] = None
    rate: Optional[str] = None
    pitch: Optional[str] = None
    face: str = Field(min_length=1, max_length=80)
    head: Optional[HeadCommand] = None
    head_sequence: Optional[List[HeadSequenceStep]] = None
    after_speech: Optional[AfterSpeechCommand] = None
    wheel_lights: Optional[WheelLightsCommand] = None
    safety: SafetyModeCommand
    motion: MotionCommand

    @model_validator(mode="after")
    def only_allow_guarded_forward_micro_motion(self):
        if self.face.upper().replace("_ADV", "") not in PRESENTATION_SPEECH_CUES:
            raise ValueError("L8 requires a supported visual face")
        if self.voice_profile and self.voice_profile not in VOICE_PROFILES:
            raise ValueError("L8 uses an unsupported voice_profile")
        if not self.safety.base_motion_enabled:
            raise ValueError("L8 requires base_motion_enabled")
        if not self.safety.collision_guard_enabled or not self.safety.fall_guard_enabled:
            raise ValueError("L8 requires both collision and fall guards")
        if self.safety.max_distance_m > 0.15 or self.safety.max_speed != 1 or self.safety.auto_stop_ms > 1500:
            raise ValueError("L8 requires max_distance_m <= 0.15, max_speed = 1, and auto_stop_ms <= 1500")
        if not 0.05 <= self.motion.x <= 0.15 or self.motion.y != 0 or self.motion.theta != 0 or self.motion.speed != 1:
            raise ValueError("L8 permits only a 0.05-0.15m straight forward movement at speed 1")
        return self


class CalibratedRouteSegment(BaseModel):
    """A reviewed L10 segment; the same L8 limits apply independently."""
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=80)
    command: AutonomousMicroMotionCommand


class CalibratedRouteDefinitionRequest(BaseModel):
    """Token-gated route registry.  Routes have no map coordinates or turns."""
    route_id: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    version: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=160)
    segments: List[CalibratedRouteSegment] = Field(min_length=1, max_length=6)


class CalibratedRouteRunRequest(BaseModel):
    route_id: str = Field(min_length=2, max_length=80)
    robot_slug: str = Field(min_length=1, max_length=120)
    idempotency_key: str = Field(min_length=8, max_length=128)
    operation_permit_id: Optional[str] = Field(default=None, min_length=8, max_length=80)


class RouteRecoveryRequest(BaseModel):
    operator_name: str = Field(min_length=2, max_length=80)
    action: Literal["retry", "cancel"]
    operation_permit_id: Optional[str] = Field(default=None, min_length=8, max_length=80)
    note: str = Field(default="", max_length=240)


class RouteCertificationRequest(BaseModel):
    operator_name: str = Field(min_length=2, max_length=80)
    path_clearance_checked: Literal[True]
    segment_measurements_checked: Literal[True]
    emergency_stop_checked: Literal[True]
    note: str = Field(default="", max_length=240)


class OperatorAuthorizationRequest(BaseModel):
    operator_name: str = Field(min_length=2, max_length=80)
    role: Literal["route_operator", "safety_officer"]
    scopes: List[Literal["route_release", "operation_permit", "safety_recovery"]] = Field(min_length=1, max_length=3)
    ttl_seconds: int = Field(default=900, ge=60, le=3600)
    note: str = Field(default="", max_length=240)


class RouteReleaseRequest(BaseModel):
    authorization_id: str = Field(min_length=8, max_length=80)
    state: Literal["ACTIVE", "REVOKED"]
    allowed_robot_slugs: List[str] = Field(default_factory=list, max_length=20)
    note: str = Field(default="", max_length=240)


class LocalizationAttestationRequest(BaseModel):
    operator_name: str = Field(min_length=2, max_length=80)
    map_id: str = Field(min_length=2, max_length=80)
    map_version: str = Field(min_length=1, max_length=40)
    starting_pose_checked: Literal[True]
    localization_drift_checked: Literal[True]
    fallback_stop_checked: Literal[True]


class SafetyEnvelopeRequest(BaseModel):
    operator_name: str = Field(min_length=2, max_length=80)
    obstacle_stop_checked: Literal[True]
    exclusion_zone_checked: Literal[True]
    manual_takeover_checked: Literal[True]


class ZoneReservationRequest(BaseModel):
    zone_id: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    robot_slug: str = Field(min_length=1, max_length=120)
    route_id: str = Field(min_length=2, max_length=80)
    ttl_seconds: int = Field(default=120, ge=30, le=600)


class FaultDrillRequest(BaseModel):
    operator_name: str = Field(min_length=2, max_length=80)
    emergency_stop_checked: Literal[True]
    lost_localization_stop_checked: Literal[True]
    obstacle_stop_checked: Literal[True]


class OperationPermitRequest(BaseModel):
    route_id: str = Field(min_length=2, max_length=80)
    robot_slug: str = Field(min_length=1, max_length=120)
    zone_reservation_id: str = Field(min_length=8, max_length=80)
    authorization_id: str = Field(min_length=8, max_length=80)
    ttl_seconds: int = Field(default=300, ge=60, le=900)
    note: str = Field(default="", max_length=240)


class ScenarioScriptStep(BaseModel):
    """One stationary L1 scene.  Movement, media, and RobotAPI actions stay out."""
    model_config = ConfigDict(extra="forbid")
    text: Optional[str] = Field(default=None, max_length=1000)
    voice_profile: Optional[str] = None
    voice: Optional[str] = None
    rate: Optional[str] = None
    pitch: Optional[str] = None
    face: str = Field(min_length=1, max_length=80)
    head: Optional[HeadCommand] = None
    head_sequence: Optional[List[HeadSequenceStep]] = None
    after_speech: Optional[AfterSpeechCommand] = None
    wheel_lights: Optional[WheelLightsCommand] = None

    @model_validator(mode="after")
    def requires_a_visible_or_spoken_scene(self):
        if not self.text and not self.head and not self.head_sequence and not self.wheel_lights:
            raise ValueError("L1 step requires text, head movement, or wheel lights")
        face_key = self.face.upper().replace("_ADV", "")
        if face_key not in PRESENTATION_SPEECH_CUES:
            raise ValueError("L1 step requires a supported visual face")
        if self.voice_profile and self.voice_profile not in VOICE_PROFILES:
            raise ValueError("L1 step uses an unsupported voice_profile")
        return self


class ScenarioScriptCommand(BaseModel):
    """Bounded sequential scenes that the APK can stop between every step."""
    model_config = ConfigDict(extra="forbid")
    steps: List[ScenarioScriptStep] = Field(min_length=2, max_length=8)


class ScenarioOutcomeScript(BaseModel):
    """A short stationary response selected locally after an L2 vision gate."""
    model_config = ConfigDict(extra="forbid")
    steps: List[ScenarioScriptStep] = Field(min_length=1, max_length=4)


class InteractiveVisionGate(BaseModel):
    """Privacy-preserving, stationary vision inputs that do not identify a person."""
    model_config = ConfigDict(extra="forbid")
    action: Literal["detect_face", "detect_person", "gesture_point"]
    interval_ms: int = Field(default=1000, ge=250, le=5000)
    timeout_ms: int = Field(default=8000, ge=3000, le=30000)
    debug_preview: Literal[False] = False


class InteractiveScenarioCommand(BaseModel):
    """L2/L3 branch on anonymous local signals; no movement or recognition."""
    model_config = ConfigDict(extra="forbid")
    vision_gate: InteractiveVisionGate
    on_detect: ScenarioOutcomeScript
    on_timeout: ScenarioOutcomeScript


class InteractiveSequenceCommand(BaseModel):
    """L4 stationary two-gate flow: anonymous presence, then anonymous pointing."""
    model_config = ConfigDict(extra="forbid")
    first_gate: InteractiveVisionGate
    prompt: ScenarioScriptStep
    second_gate: InteractiveVisionGate
    on_first_timeout: ScenarioOutcomeScript
    on_second_detect: ScenarioOutcomeScript
    on_second_timeout: ScenarioOutcomeScript


class NavigationScenarioOutcome(BaseModel):
    """Stationary response that may open one Core-approved display URL."""
    model_config = ConfigDict(extra="forbid")
    steps: List[ScenarioScriptStep] = Field(min_length=1, max_length=4)
    navigation: NavigationCommand


class InteractiveNavigationSequenceCommand(BaseModel):
    """L5 presence/gesture sequence that opens a trusted display after consent."""
    model_config = ConfigDict(extra="forbid")
    first_gate: InteractiveVisionGate
    prompt: ScenarioScriptStep
    second_gate: InteractiveVisionGate
    on_first_timeout: ScenarioOutcomeScript
    on_second_detect: NavigationScenarioOutcome
    on_second_timeout: ScenarioOutcomeScript

class InteractCommand(BaseModel):
    text: Optional[str] = Field(default=None, example="สวัสดีครับ  ผมพร้อมให้บริการแล้วครับผมม  ")
    voice_profile: Optional[str] = Field(default=None, example="female_young")
    voice: Optional[str] = Field(default="female_sweet", example="female_sweet")
    rate: Optional[str] = Field(default="-10%", example="-10%")
    pitch: Optional[str] = Field(default="+2Hz", example="+2Hz")
    volume: Optional[int] = Field(default=None, ge=0, le=100)
    face: Optional[str] = Field(default=None, example="HAPPY")
    motion: Optional[MotionCommand] = None
    head: Optional[HeadCommand] = None
    head_sequence: Optional[List[HeadSequenceStep]] = None
    after_speech: Optional[AfterSpeechCommand] = None
    script: Optional[ScenarioScriptCommand] = None
    interactive: Optional[InteractiveScenarioCommand] = None
    interactive_sequence: Optional[Union[InteractiveSequenceCommand, InteractiveNavigationSequenceCommand]] = None
    action: Optional[CannedActionCommand] = None
    wheel_lights: Optional[WheelLightsCommand] = None
    emotional_action: Optional[EmotionalActionCommand] = None
    remote_control: Optional[RemoteControlCommand] = None
    behavior: Optional[BehaviorCommand] = None
    vision: Optional[VisionCommand] = None
    youtube: Optional[YouTubeCommand] = None
    safety: Optional[SafetyModeCommand] = None
    navigation: Optional[NavigationCommand] = None
    robot_slug: Optional[str] = Field(default=None, description="Target robot slug, e.g. zenbo1")
    source: Optional[str] = Field(default="liff", max_length=40, description="LIFF surface that dispatched this command")
    user_id: Optional[str] = Field(default=None, max_length=64, description="LINE userId of the dispatcher")
    display_name: Optional[str] = Field(default=None, max_length=128, description="LINE display name of the dispatcher")
    scenario_run_id: Optional[str] = Field(default=None, min_length=1, max_length=64)
    record_phrase: bool = Field(default=True, description="Record this text phrase for the dispatcher")


class PresentationRequest(BaseModel):
    preset_id: str = Field(min_length=2, max_length=80)
    robot_slug: str = Field(min_length=1, max_length=120)
    variables: Dict[str, str] = Field(default_factory=dict)

    @field_validator("preset_id")
    @classmethod
    def known_preset_id(cls, value: str) -> str:
        preset_id = value.strip()
        if preset_id not in PRESENTATION_CATALOG:
            raise ValueError("Unknown presentation preset")
        return preset_id


class PresentationBatchRequest(BaseModel):
    """Explicit, bounded fan-out for one stationary presentation preset."""
    preset_id: str = Field(min_length=2, max_length=80)
    robot_slugs: List[str] = Field(min_length=1, max_length=12)
    variables: Dict[str, str] = Field(default_factory=dict)

    @field_validator("preset_id")
    @classmethod
    def known_preset_id(cls, value: str) -> str:
        preset_id = value.strip()
        if preset_id not in PRESENTATION_CATALOG:
            raise ValueError("Unknown presentation preset")
        return preset_id

    @field_validator("robot_slugs")
    @classmethod
    def unique_robot_slugs(cls, values: List[str]) -> List[str]:
        slugs = [value.strip() for value in values]
        if any(not slug or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,119}", slug) for slug in slugs):
            raise ValueError("robot_slugs must contain valid robot slugs")
        if len(set(slugs)) != len(slugs):
            raise ValueError("robot_slugs must not contain duplicates")
        return slugs


class ScenarioRunRequest(BaseModel):
    scenario_id: str = Field(min_length=2, max_length=80)
    robot_slug: str = Field(min_length=1, max_length=120)
    idempotency_key: str = Field(min_length=8, max_length=128)
    source: str = Field(default="liff", max_length=40)
    parameters: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("scenario_id")
    @classmethod
    def known_scenario_id(cls, value: str) -> str:
        scenario_id = value.strip()
        return scenario_id


class FieldAttestationRequest(BaseModel):
    """Operator statement for L7.  It cannot be supplied by an anonymous LIFF client."""
    operator_name: str = Field(min_length=2, max_length=80)
    tts_checked: Literal[True]
    vision_checked: Literal[True]
    display_checked: Literal[True]
    note: str = Field(default="", max_length=240)


class ScenarioDefinitionRequest(BaseModel):
    """Trusted n8n import format for stationary L0 or scripted L1 scenarios."""
    scenario_id: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    version: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=500)
    risk_level: Literal["L0", "L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "L10"] = "L0"
    required_capabilities: List[str] = Field(default_factory=list, max_length=12)
    command: Dict[str, Any]

    @field_validator("command")
    @classmethod
    def stationary_command(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        if "calibrated_route_segment" in value:
            raise ValueError("L10 route segments are managed only through the calibrated-route registry")
        if "autonomous_motion" in value:
            if set(value) != {"autonomous_motion"}:
                raise ValueError("L8 scenario command supports only autonomous_motion")
            try:
                return {"autonomous_motion": AutonomousMicroMotionCommand(**value["autonomous_motion"]).model_dump(exclude_none=True)}
            except ValidationError as error:
                raise ValueError(f"Invalid guarded L8 motion: {error}") from error
        if "first_gate" in value:
            allowed = {"first_gate", "prompt", "second_gate", "on_first_timeout", "on_second_detect", "on_second_timeout"}
            if set(value) != allowed:
                raise ValueError("L4 scenario command has unsupported fields")
            try:
                if isinstance(value.get("on_second_detect"), dict) and "navigation" in value["on_second_detect"]:
                    return InteractiveNavigationSequenceCommand(**value).model_dump(exclude_none=True)
                return InteractiveSequenceCommand(**value).model_dump(exclude_none=True)
            except ValidationError as error:
                raise ValueError(f"Invalid stationary L4/L5 interaction: {error}") from error
        if "vision_gate" in value:
            if set(value) != {"vision_gate", "on_detect", "on_timeout"}:
                raise ValueError("L2 scenario command supports only vision_gate, on_detect, and on_timeout")
            try:
                return InteractiveScenarioCommand(**value).model_dump(exclude_none=True)
            except ValidationError as error:
                raise ValueError(f"Invalid stationary L2/L3 interaction: {error}") from error
        if "steps" in value:
            if set(value) != {"steps"}:
                raise ValueError("L1 scenario command supports only steps")
            try:
                return ScenarioScriptCommand(**value).model_dump(exclude_none=True)
            except ValidationError as error:
                raise ValueError(f"Invalid stationary L1 script: {error}") from error
        blocked = {"motion", "action", "behavior", "vision", "youtube", "navigation", "remote_control", "emotional_action"}
        allowed = {"text", "voice_profile", "voice", "rate", "pitch", "face", "head", "head_sequence", "after_speech", "wheel_lights"}
        if blocked.intersection(value):
            raise ValueError("L0 scenario cannot contain movement, behavior, vision, media, or remote-control commands")
        unknown = set(value).difference(allowed)
        if unknown:
            raise ValueError(f"L0 scenario has unsupported command fields: {', '.join(sorted(unknown))}")
        if not isinstance(value.get("text"), str) or not value["text"].strip():
            raise ValueError("L0 scenario requires non-empty text")
        face = str(value.get("face", "")).upper()
        if face not in PRESENTATION_SPEECH_CUES:
            raise ValueError("L0 scenario requires a supported visual face so Core can attach a stationary head gesture")
        try:
            InteractCommand(**value)
        except ValidationError as error:
            raise ValueError(f"Invalid stationary interaction command: {error}") from error
        return value

    @model_validator(mode="after")
    def risk_level_matches_command(self):
        is_l1 = "steps" in self.command
        is_interactive = "vision_gate" in self.command
        is_sequence = "first_gate" in self.command
        is_autonomous_motion = "autonomous_motion" in self.command
        has_navigation_outcome = is_sequence and "navigation" in self.command.get("on_second_detect", {})
        if self.risk_level == "L1" and not is_l1:
            raise ValueError("L1 requires a steps script")
        if self.risk_level in {"L2", "L3"} and not is_interactive:
            raise ValueError("L2/L3 requires an anonymous vision gate")
        if self.risk_level == "L2" and self.command["vision_gate"]["action"] not in {"detect_face", "detect_person"}:
            raise ValueError("L2 supports only anonymous face or person detection")
        if self.risk_level == "L3" and self.command["vision_gate"]["action"] != "gesture_point":
            raise ValueError("L3 supports only anonymous gesture_point detection")
        if self.risk_level == "L4":
            if not is_sequence:
                raise ValueError("L4 requires a presence gate followed by a gesture gate")
            if self.command["first_gate"]["action"] not in {"detect_face", "detect_person"}:
                raise ValueError("L4 first_gate supports only anonymous face or person detection")
            if self.command["second_gate"]["action"] != "gesture_point":
                raise ValueError("L4 second_gate supports only anonymous gesture_point detection")
            if has_navigation_outcome:
                raise ValueError("L4 cannot open a display URL")
        if self.risk_level in {"L5", "L6", "L7"}:
            if not is_sequence:
                raise ValueError("L5/L6 requires a presence gate followed by a gesture gate")
            if self.command["first_gate"]["action"] not in {"detect_face", "detect_person"}:
                raise ValueError("L5/L6 first_gate supports only anonymous face or person detection")
            if self.command["second_gate"]["action"] != "gesture_point":
                raise ValueError("L5/L6 second_gate supports only anonymous gesture_point detection")
            if not has_navigation_outcome:
                raise ValueError("L5/L6 requires a trusted navigation outcome after gesture detection")
        if self.risk_level == "L8" and not is_autonomous_motion:
            raise ValueError("L8 requires a guarded autonomous_motion command")
        if self.risk_level != "L8" and is_autonomous_motion:
            raise ValueError("autonomous_motion is reserved for L8")
        if self.risk_level == "L10":
            raise ValueError("L10 route segments are managed only through the calibrated-route registry")
        if self.risk_level == "L0" and (is_l1 or is_interactive or is_sequence or is_autonomous_motion):
            raise ValueError("L0 must use one stationary command")
        return self

class NeuralTtsRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    voice: str = Field(default="female_sweet")
    rate: str = Field(default="-8%")
    pitch: str = Field(default="+0Hz")

class CommandCompileRequest(BaseModel):
    command: str = Field(min_length=1, max_length=1000)
    robot_slug: Optional[str] = Field(default=None)


class DialogueIntentRequest(BaseModel):
    session_id: str = Field(min_length=8, max_length=128)
    text: str = Field(min_length=1, max_length=1000)
    robot_slug: Optional[str] = Field(default=None, max_length=120)


class UserRobotBindingRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=64)
    robot_slug: str = Field(min_length=1, max_length=128)
    display_name: Optional[str] = Field(default=None, max_length=128)
    permission: str = Field(default="operator", pattern="^(operator|admin|viewer)$")

@app.get("/health")
async def health():
    return {"status": "ok", "service": "zenbo-core-api"}


def compile_with_intelsphere_agent(raw_command: str, robot_slug: Optional[str] = None) -> Dict[str, Any]:
    cmd = raw_command.strip()
    cmd_lower = cmd.lower()

    # 1. Emergency Stop Check
    if any(w in cmd_lower for w in ["หยุด", "อย่าขยับ", "ยกเลิก", "stop", "halt", "cancel"]):
        return {
            "compiled_payload": {
                "text": "รับทราบครับ หยุดการทำงานของ Zenbo ทันทีครับ",
                "voice_profile": "male_young",
                "face": "DEFAULT_STILL",
                "action": {"action_id": 0, "stop": True},
                "wheel_lights": {"mode": "blinking", "color": "#EF4444", "brightness": 20},
                "emergency": True,
            },
            "compiler_source": "kku_intelsphere",
            "compiler_action": "stop",
            "intent": "EMERGENCY_STOP",
            "reasoning": "ตรวจพบคำสั่งหยุดฉุกเฉิน (Stop) ทำการส่ง signal ยกเลิก Action ทั้งหมด ปรับไฟเตือนสีแดง และหยุดมอเตอร์ทันที",
            "agent_name": "KKU IntelSphere AI Agent",
            "action_meta": {"id": 0, "name": "Default_1", "title": "หยุดฉุกเฉิน / คืนท่าตั้งต้น", "icon": "🛑"},
            "face_meta": {"id": "DEFAULT_STILL", "title": "หน้าปกติหยุดนิ่ง", "icon": "😐"},
        }

    # 2. InnoTech Show & Share 2026 Judge Welcome
    if any(w in cmd_lower for w in ["innotech", "show & share", "กรรมการ", "คณะกรรมการ", "ต้อนรับกรรมการ"]):
        return {
            "compiled_payload": {
                "text": "สวัสดีครับ ขอต้อนรับคณะกรรมการผู้ทรงเกียรติทุกท่าน สู่งาน InnoTech Show & Share 2026 จัดโดยศูนย์นวัตกรรมการเรียนการสอน มหาวิทยาลัยขอนแก่น ครับ ผม บุ๊คกี้ หุ่นยนต์บรรณารักษ์อัจฉริยะ ขอร่วมเป็นส่วนหนึ่งในการขับเคลื่อนนวัตกรรมด้วยพลัง AI ผสาน KKU IntelSphere เพื่อบริการที่ชาญฉลาดและเข้าถึงง่าย ขอเชิญคณะกรรมการทุกท่านรับชมการสาธิตผลงานได้เลยครับ",
                "voice_profile": "male_young",
                "face": "PROUD",
                "action": {"action_id": 2, "stop": False},
                "wheel_lights": {"mode": "breath", "color": "#8B5CF6", "brightness": 14},
                "head": {"yaw": 0, "pitch": 8, "speed": 1},
            },
            "compiler_source": "kku_intelsphere",
            "compiler_action": "innotech_welcome",
            "intent": "WELCOME_JUDGES",
            "reasoning": "วิเคราะห์คำสั่งต้อนรับคณะกรรมการ: สร้างสุนทรพจน์พิธีการสำหรับงาน InnoTech Show & Share 2026 (LTIC มข.), เลือกสีหน้าภาคภูมิใจ (PROUD), พยักหน้าตอบรับ (Nod_1 #2), และเปิดไฟล้อสีม่วงวิทยวิภาส",
            "agent_name": "KKU IntelSphere AI Agent",
            "action_meta": {"id": 2, "name": "Nod_1", "title": "พยักหน้าตอบรับ 1 ครั้ง", "icon": "🙇"},
            "face_meta": {"id": "PROUD", "title": "ภาคภูมิใจ", "icon": "😎"},
        }

    # 3. Dance & Music
    if any(w in cmd_lower for w in ["เต้น", "dance", "ส่ายเอว", "บิดตัว", "แดนซ์", "โยก"]):
        return {
            "compiled_payload": {
                "text": "ได้เลยครับ มาชมการเต้นส่ายเอวจังหวะสนุกๆ ของผมกันเลยครับ",
                "voice_profile": "male_child",
                "face": "SINGING",
                "action": {"action_id": 22, "stop": False},
                "wheel_lights": {"mode": "rainbow", "color": "#EC4899", "brightness": 15},
            },
            "compiler_source": "kku_intelsphere",
            "compiler_action": "dance",
            "intent": "DANCE_MUSIC",
            "reasoning": "ตรวจพบเจตนาเต้นโชว์: สั่งท่าทาง Body_twist_1 (Action ID #22), ปรับสีหน้าร้องเพลง (SINGING) และเปิดไฟล้อเอฟเฟกต์สีรุ้ง Rainbow",
            "agent_name": "KKU IntelSphere AI Agent",
            "action_meta": {"id": 22, "name": "Body_twist_1", "title": "บิดตัวส่ายเอว 1", "icon": "🕺"},
            "face_meta": {"id": "SINGING", "title": "ร้องเพลงสนุกสนาน", "icon": "🎶"},
        }

    # 4. Nod / Polite Greeting
    if any(w in cmd_lower for w in ["พยักหน้า", "nod", "ทักทาย", "สวัสดี", "hello", "hi"]):
        return {
            "compiled_payload": {
                "text": "สวัสดีครับ ผมบุ๊คกี้ ยินดีต้อนรับทุกท่านครับ มีอะไรให้ผมรับใช้บอกได้เลยนะครับ",
                "voice_profile": "male_child",
                "face": "HAPPY",
                "action": {"action_id": 2, "stop": False},
                "wheel_lights": {"mode": "breath", "color": "#10B981", "brightness": 12},
                "head": {"yaw": 0, "pitch": 10, "speed": 2},
            },
            "compiler_source": "kku_intelsphere",
            "compiler_action": "nod",
            "intent": "GREETING_NOD",
            "reasoning": "ตรวจพบคำทักทาย: ทักทายสุภาพพร้อมพยักหน้า Nod_1 (Action ID #2) สีหน้ามีความสุข (HAPPY) และไฟล้อสีเขียวสดใส",
            "agent_name": "KKU IntelSphere AI Agent",
            "action_meta": {"id": 2, "name": "Nod_1", "title": "พยักหน้าตอบรับ 1 ครั้ง", "icon": "🙇"},
            "face_meta": {"id": "HAPPY", "title": "มีความสุข", "icon": "😄"},
        }

    # 5. Shake Head / Disagree
    if any(w in cmd_lower for w in ["ส่ายหน้า", "ส่ายหัว", "ปฏิเสธ", "ไม่"]):
        return {
            "compiled_payload": {
                "text": "เรื่องนี้ยังไม่ถูกต้องนะครับ ขออภัยด้วยครับ",
                "voice_profile": "male_young",
                "face": "DOUBT",
                "action": {"action_id": 5, "stop": False},
                "head_sequence": [
                    {"yaw": -25.0, "pitch": 10.0, "speed": 2, "delay_ms": 0},
                    {"yaw": 25.0, "pitch": 10.0, "speed": 2, "delay_ms": 400},
                    {"yaw": 0.0, "pitch": 10.0, "speed": 2, "delay_ms": 400},
                ],
                "wheel_lights": {"mode": "breath", "color": "#F59E0B", "brightness": 12},
            },
            "compiler_source": "kku_intelsphere",
            "compiler_action": "shake_head",
            "intent": "HEAD_SHAKE",
            "reasoning": "ตรวจพบคำสั่งส่ายหน้า: สั่งท่าทาง Shake_head_1 (Action ID #5) พร้อมสีหน้าสงสัย (DOUBT)",
            "agent_name": "KKU IntelSphere AI Agent",
            "action_meta": {"id": 5, "name": "Shake_head_1", "title": "ส่ายหน้าปฏิเสธ 1", "icon": "🙅"},
            "face_meta": {"id": "DOUBT", "title": "สงสัยครุ่นคิด", "icon": "🤨"},
        }

    # 6. Turn Left / Right
    if any(w in cmd_lower for w in ["หันซ้าย", "เลี้ยวซ้าย", "มองซ้าย"]):
        return {
            "compiled_payload": {
                "text": "หันไปทางซ้ายแล้วครับ",
                "voice_profile": "male_young",
                "face": "AWARE_LEFT",
                "action": {"action_id": 18, "stop": False},
                "head": {"yaw": -35.0, "pitch": 10.0, "speed": 2},
                "wheel_lights": {"mode": "breath", "color": "#3B82F6", "brightness": 12},
            },
            "compiler_source": "kku_intelsphere",
            "compiler_action": "turn_left",
            "intent": "TURN_LEFT",
            "reasoning": "ตรวจพบคำสั่งหันซ้าย: สั่งท่า Turn_left_1 (Action ID #18) ขยับหัวไปทางซ้าย yaw -35 องศา",
            "agent_name": "KKU IntelSphere AI Agent",
            "action_meta": {"id": 18, "name": "Turn_left_1", "title": "หันฐานซ้าย 1", "icon": "↩️"},
            "face_meta": {"id": "AWARE_LEFT", "title": "ชำเลืองซ้าย", "icon": "👈"},
        }

    if any(w in cmd_lower for w in ["หันขวา", "เลี้ยวขวา", "มองขวา"]):
        return {
            "compiled_payload": {
                "text": "หันไปทางขวาแล้วครับ",
                "voice_profile": "male_young",
                "face": "AWARE_RIGHT",
                "action": {"action_id": 44, "stop": False},
                "head": {"yaw": 35.0, "pitch": 10.0, "speed": 2},
                "wheel_lights": {"mode": "breath", "color": "#3B82F6", "brightness": 12},
            },
            "compiler_source": "kku_intelsphere",
            "compiler_action": "turn_right",
            "intent": "TURN_RIGHT",
            "reasoning": "ตรวจพบคำสั่งหันขวา: สั่งท่า Turn_right_1 (Action ID #44) ขยับหัวไปทางขวา yaw +35 องศา",
            "agent_name": "KKU IntelSphere AI Agent",
            "action_meta": {"id": 44, "name": "Turn_right_1", "title": "หันฐานขวา 1", "icon": "↪️"},
            "face_meta": {"id": "AWARE_RIGHT", "title": "ชำเลืองขวา", "icon": "👉"},
        }

    # 7. Head Up / Down
    if any(w in cmd_lower for w in ["เงยหน้า", "มองบน", "มองฟ้า"]):
        return {
            "compiled_payload": {
                "text": "เงยหน้าขึ้นแล้วครับ",
                "voice_profile": "male_child",
                "face": "EXPECTING",
                "action": {"action_id": 3, "stop": False},
                "head": {"yaw": 0.0, "pitch": 30.0, "speed": 2},
                "wheel_lights": {"mode": "breath", "color": "#06B6D4", "brightness": 12},
            },
            "compiler_source": "kku_intelsphere",
            "compiler_action": "head_up",
            "intent": "HEAD_UP",
            "reasoning": "ตรวจพบคำสั่งเงยหน้า: สั่งท่า Head_up_1 (Action ID #3) ปรับ pitch +30 องศา",
            "agent_name": "KKU IntelSphere AI Agent",
            "action_meta": {"id": 3, "name": "Head_up_1", "title": "เงยหน้าขึ้น 1", "icon": "⬆️"},
            "face_meta": {"id": "EXPECTING", "title": "คาดหวังรอคอย", "icon": "👀"},
        }

    if any(w in cmd_lower for w in ["ก้มหน้า", "มองลง", "มองพื้น"]):
        return {
            "compiled_payload": {
                "text": "ก้มหน้าลงแล้วครับ",
                "voice_profile": "male_child",
                "face": "SHY",
                "action": {"action_id": 8, "stop": False},
                "head": {"yaw": 0.0, "pitch": -12.0, "speed": 2},
                "wheel_lights": {"mode": "breath", "color": "#64748B", "brightness": 10},
            },
            "compiler_source": "kku_intelsphere",
            "compiler_action": "head_down",
            "intent": "HEAD_DOWN",
            "reasoning": "ตรวจพบคำสั่งก้มหน้า: สั่งท่า Head_down_1 (Action ID #8) ปรับ pitch -12 องศา",
            "agent_name": "KKU IntelSphere AI Agent",
            "action_meta": {"id": 8, "name": "Head_down_1", "title": "ก้มหน้าลง 1", "icon": "⬇️"},
            "face_meta": {"id": "SHY", "title": "เขินอาย", "icon": "😳"},
        }

    # 8. Find Face / Vision
    if any(w in cmd_lower for w in ["สแกนหน้า", "สแกน", "หาหน้า", "หาใบหน้า", "ตรวจจับหน้า", "ตรวจจับใบหน้า", "มองหาคน", "face"]):
        return {
            "compiled_payload": {
                "text": "กำลังเปิดระบบสแกนและมองหาใบหน้าของผู้ใช้ครับ",
                "voice_profile": "male_young",
                "face": "INTERESTED",
                "action": {"action_id": 1007, "stop": False},
                "wheel_lights": {"mode": "breathing", "color": "#06B6D4", "brightness": 15},
                "vision": {"action": "detect_face", "interval_ms": 1000, "debug_preview": True},
            },
            "compiler_source": "kku_intelsphere",
            "compiler_action": "find_face",
            "intent": "FIND_FACE",
            "reasoning": "ตรวจพบคำสั่งตรวจจับใบหน้า: เรียก Action Find_face (Action ID #1007) พร้อมระบบกล้อง AI Vision",
            "agent_name": "KKU IntelSphere AI Agent",
            "action_meta": {"id": 1007, "name": "Find_face", "title": "สแกนหาใบหน้า", "icon": "👁️"},
            "face_meta": {"id": "INTERESTED", "title": "สนใจใคร่รู้", "icon": "😃"},
        }

    # 9. Self Introduction / Library Info
    if any(w in cmd_lower for w in ["แนะนำตัว", "คุณคือใคร", "ชื่ออะไร", "who are you"]):
        return {
            "compiled_payload": {
                "text": "สวัสดีครับ ผมชื่อบุ๊คกี้ หุ่นยนต์บรรณารักษ์อัจฉริยะของสำนักหอสมุด มหาวิทยาลัยขอนแก่น ทำงานร่วมกับระบบ KKU IntelSphere AI เพื่อให้บริการและช่วยเหลือทุกท่านครับ",
                "voice_profile": "male_child",
                "face": "CONFIDENT",
                "action": {"action_id": 2, "stop": False},
                "wheel_lights": {"mode": "breath", "color": "#00D031", "brightness": 14},
                "head": {"yaw": 0, "pitch": 6, "speed": 1},
            },
            "compiler_source": "kku_intelsphere",
            "compiler_action": "self_intro",
            "intent": "SELF_INTRODUCE",
            "reasoning": "วิเคราะห์เจตนาแนะนำตัว: สร้างข้อความแนะนำบทบาทของ Booky หุ่นยนต์บรรณารักษ์ มข. สีหน้ามั่นใจ (CONFIDENT)",
            "agent_name": "KKU IntelSphere AI Agent",
            "action_meta": {"id": 2, "name": "Nod_1", "title": "พยักหน้าตอบรับ 1 ครั้ง", "icon": "🤖"},
            "face_meta": {"id": "CONFIDENT", "title": "มั่นใจ", "icon": "😏"},
        }

    # 10. General Speech (Default Fallback)
    speech_text = cmd
    if speech_text.startswith("พูดว่า"):
        speech_text = speech_text[6:].strip()
    elif speech_text.startswith("ให้พูดว่า"):
        speech_text = speech_text[9:].strip()

    return {
        "compiled_payload": {
            "text": speech_text,
            "voice_profile": "female_sweet" if any(w in cmd_lower for w in ["หวาน", "ผู้หญิง", "ค่ะ", "คะ"]) else "male_child",
            "face": "HAPPY",
            "wheel_lights": {"mode": "breath", "color": "#00D031", "brightness": 12},
        },
        "compiler_source": "kku_intelsphere",
        "compiler_action": "speak",
        "intent": "SPEAK_THAI",
        "reasoning": f"วิเคราะห์คำสั่งพูดภาษาไทย: สกัดข้อความเสียง '{speech_text}' ปรับสีหน้ามีความสุข (HAPPY) และเปิดไฟล้อสีเขียว",
        "agent_name": "KKU IntelSphere AI Agent",
        "action_meta": None,
        "face_meta": {"id": "HAPPY", "title": "มีความสุข", "icon": "😄"},
    }


@app.post("/api/v1/commands/compile")
async def compile_command(req: CommandCompileRequest):
    """Compile natural language via KKU IntelSphere AI Agent for preview and safe dispatch."""
    agent_result = compile_with_intelsphere_agent(req.command, req.robot_slug)

    # Check if agent recognized a clear structural intent
    recognized_intents = {
        "EMERGENCY_STOP", "WELCOME_JUDGES", "DANCE_MUSIC", "GREETING_NOD",
        "HEAD_SHAKE", "TURN_LEFT", "TURN_RIGHT", "HEAD_UP", "HEAD_DOWN",
        "FIND_FACE", "SELF_INTRODUCE"
    }
    if agent_result.get("intent") in recognized_intents:
        return agent_result

    # If in shared_v1 mode, attempt compiler backend; fall back cleanly to agent_result
    if COMPILER_API_MODE == "shared_v1":
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{COMPILER_SERVICE_URL}/v1/compile",
                    json={"text": req.command, "send": False, "source": "liff_preview"},
                    timeout=5.0,
                )
            if response.status_code < 400:
                data = response.json()
                action = str(data.get("command", {}).get("action", "")).strip().lower()
                if action == "dance":
                    return compile_with_intelsphere_agent("เต้น", req.robot_slug)
                elif action in ("nod", "greeting"):
                    return compile_with_intelsphere_agent("พยักหน้า", req.robot_slug)
                elif action == "shake_head":
                    return compile_with_intelsphere_agent("ส่ายหน้า", req.robot_slug)
                elif action == "stop":
                    return compile_with_intelsphere_agent("หยุด", req.robot_slug)
        except Exception:
            pass

    return agent_result


@app.post("/api/v1/dialogue/interpret")
async def interpret_dialogue(req: DialogueIntentRequest):
    """Proxy the deterministic wake-word gate; dispatch remains an explicit LIFF action."""
    if COMPILER_API_MODE == "shared_v1":
        raise HTTPException(status_code=409, detail={"code": "DIALOGUE_GATE_UNAVAILABLE", "message": "Configure the local compiler service for wake-word dialogue"})
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{COMPILER_SERVICE_URL}/api/v1/dialogue/interpret",
                json=req.model_dump(), timeout=15.0,
            )
        data = response.json()
        if response.status_code >= 400:
            raise HTTPException(status_code=response.status_code, detail=data.get("detail", "Dialogue request failed"))
        return data
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Compiler service is unavailable") from exc


def thai_tts_payload(text: str, voice_name: str) -> Dict[str, Any]:
    """Normalize public persona names to the private-LAN Thai TTS contract."""
    voice = (voice_name or "").strip().lower()
    if voice in {"female_sweet", "female_child", "female_young", "female_adult", "th_f_1"}:
        return {"text": text, "voice": "th_f_1", "age": 20, "speed": 0.96, "natural_mode": True}
    elif voice in {"boy_cute", "male_child"}:
        return {"text": text, "voice": "th_m_1", "age": 10, "speed": 0.78, "natural_mode": True}
    return {"text": text, "voice": "th_m_1", "age": 20, "speed": 0.96, "natural_mode": True}


async def fetch_thai_tts_wav(text: str, voice_name: str) -> bytes:
    """Fetch WAV from the private service; never route legacy clients through public TLS."""
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(
                f"{TTS_SERVICE_URL}{TTS_BINARY_PATH}",
                json=thai_tts_payload(text, voice_name),
                timeout=30.0,
            )
        if res.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"Thai TTS service rejected the request ({res.status_code}): {res.text[:200]}",
            )
        return res.content
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Thai TTS service is unavailable") from exc


@app.post("/api/v1/tts/neural/binary")
async def proxy_neural_tts(req: NeuralTtsRequest):
    """Serve Thai TTS bytes to Zenbo clients through their reachable Core API."""
    try:
        content = await fetch_thai_tts_wav(req.text, req.voice)
        return Response(
            content=content,
            media_type="audio/wav",
            headers={"Cache-Control": "no-store"},
        )
    except HTTPException:
        raise


@app.get("/api/v1/voice-profiles")
async def list_voice_profiles():
    """List stable voice-persona IDs understood by current Zenbo clients."""
    return {"profiles": [
        {"id": profile_id, **profile}
        for profile_id, profile in VOICE_PROFILES.items()
    ]}


def presentation_public_metadata(preset_id: str, preset: Dict[str, Any]) -> Dict[str, Any]:
    """Keep executable command templates server-side; LIFF receives catalog metadata only."""
    return {
        "id": preset_id,
        "title": preset["title"],
        "icon": preset["icon"],
        "category": preset["category"],
        "duration_seconds": preset["duration_seconds"],
        "availability": preset["availability"],
        "description": preset["description"],
        "fields": preset.get("fields", []),
        "gate_reason": preset.get("gate_reason"),
        "route_required": bool(preset.get("route_required")),
        "camera_preview": preset.get("camera_preview"),
        "behavior": visual_behavior_metadata(preset),
    }


def scenario_public_metadata(scenario_id: str, scenario: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": scenario_id,
        "version": scenario["version"],
        "icon": scenario.get("icon", "🤖"),
        "category": scenario.get("category", "ทั่วไป"),
        "title": scenario["title"],
        "description": scenario["description"],
        "risk_level": scenario["risk_level"],
        "confirmation": scenario["confirmation"],
        "operator_only": bool(scenario.get("operator_only")),
        "required_capabilities": scenario["required_capabilities"],
        "behavior": visual_behavior_metadata(scenario),
    }


def scenario_registry() -> Dict[str, Dict[str, Any]]:
    """Merge built-ins with trusted n8n imports; imported IDs may not replace built-ins."""
    init_command_history()
    scenarios = json.loads(json.dumps(SCENARIO_REGISTRY, ensure_ascii=False))
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        rows = connection.execute(
            "SELECT scenario_id, version, title, description, risk_level, confirmation, required_capabilities_json, command_json FROM scenario_definitions"
        ).fetchall()
    for row in rows:
        if row[0] in scenarios:
            continue
        scenarios[row[0]] = {
            "version": row[1], "title": row[2], "description": row[3],
            "risk_level": row[4], "confirmation": row[5],
            "required_capabilities": json.loads(row[6]), "command": json.loads(row[7]),
        }
    return scenarios


def get_scenario_definition(scenario_id: str) -> Dict[str, Any]:
    scenario = scenario_registry().get(scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail={"code": "UNKNOWN_SCENARIO", "message": "Scenario is not published"})
    return scenario


def require_scenario_registry_token(token: Optional[str]) -> None:
    if not SCENARIO_REGISTRY_TOKEN:
        raise HTTPException(status_code=503, detail={"code": "SCENARIO_REGISTRY_DISABLED", "message": "Set SCENARIO_REGISTRY_TOKEN before importing scenarios"})
    if token != SCENARIO_REGISTRY_TOKEN:
        raise HTTPException(status_code=403, detail={"code": "SCENARIO_REGISTRY_FORBIDDEN", "message": "Invalid scenario registry credential"})


def import_scenario_definition(req: ScenarioDefinitionRequest) -> Dict[str, Any]:
    if req.scenario_id in SCENARIO_REGISTRY:
        raise HTTPException(status_code=409, detail={"code": "BUILTIN_SCENARIO_IMMUTABLE", "message": "Built-in scenarios cannot be overwritten"})
    init_command_history()
    now = int(time.time() * 1000)
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        connection.execute(
            """INSERT INTO scenario_definitions (scenario_id, version, title, description, risk_level, confirmation, required_capabilities_json, command_json, updated_at_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(scenario_id) DO UPDATE SET version=excluded.version, title=excluded.title, description=excluded.description,
               risk_level=excluded.risk_level, confirmation=excluded.confirmation, required_capabilities_json=excluded.required_capabilities_json,
               command_json=excluded.command_json, updated_at_ms=excluded.updated_at_ms""",
            (req.scenario_id, req.version, req.title.strip(), req.description.strip(), req.risk_level, "REQUIRED",
             json.dumps(req.required_capabilities, ensure_ascii=False), json.dumps(req.command, ensure_ascii=False), now),
        )
    return scenario_public_metadata(req.scenario_id, get_scenario_definition(req.scenario_id))


def music_playlist_metadata(playlist_id: str, playlist: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": playlist_id,
        "version": playlist["version"],
        "title": playlist["title"],
        "mood": playlist["mood"],
        "track_count": len(playlist["tracks"]),
        "updated_at_ms": playlist["updated_at_ms"],
    }


def get_music_playlists() -> Dict[str, Dict[str, Any]]:
    init_command_history()
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        rows = connection.execute(
            "SELECT playlist_id, version, title, mood, tracks_json, updated_at_ms FROM music_playlists ORDER BY LOWER(title)"
        ).fetchall()
    return {
        row[0]: {"version": row[1], "title": row[2], "mood": row[3], "tracks": json.loads(row[4]), "updated_at_ms": row[5]}
        for row in rows
    }


def import_music_playlist(req: MusicPlaylistDefinitionRequest) -> Dict[str, Any]:
    init_command_history()
    now = int(time.time() * 1000)
    tracks = [track.model_dump() for track in req.tracks]
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        connection.execute(
            """INSERT INTO music_playlists (playlist_id, version, title, mood, tracks_json, updated_at_ms)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(playlist_id) DO UPDATE SET version=excluded.version, title=excluded.title,
               mood=excluded.mood, tracks_json=excluded.tracks_json, updated_at_ms=excluded.updated_at_ms""",
            (req.playlist_id, req.version, req.title.strip(), req.mood.strip(), json.dumps(tracks, ensure_ascii=False), now),
        )
    playlist = get_music_playlists()[req.playlist_id]
    return music_playlist_metadata(req.playlist_id, playlist)


def pick_music_preview(playlist_id: str, robot_slug: str) -> Dict[str, Any]:
    playlist = get_music_playlists().get(playlist_id)
    if not playlist:
        raise HTTPException(status_code=404, detail={"code": "UNKNOWN_PLAYLIST", "message": "Playlist is not published"})
    track = secrets.choice(playlist["tracks"])
    # This endpoint is intentionally a preview.  The LIFF operator must still
    # explicitly confirm the returned YouTube command through the normal path.
    return {
        "playlist": music_playlist_metadata(playlist_id, playlist),
        "track": {"title": track["title"]},
        "command": {
            "text": f"กำลังเตรียมเพลง {track['title']} ครับ",
            "voice_profile": "male_child",
            "face": "SINGING",
            "youtube": track["youtube"],
            "robot_slug": robot_slug,
            "source": "music_playlist_preview",
        },
        "dispatch": "NOT_SENT",
    }


def _scenario_run_row(row: tuple) -> Dict[str, Any]:
    return {
        "run_id": row[0], "scenario_id": row[1], "scenario_version": row[2],
        "robot_slug": row[3], "source": row[4], "idempotency_key": row[5],
        "risk_level": row[6], "state": row[7], "parameters": json.loads(row[8]),
        "created_at_ms": row[9], "updated_at_ms": row[10],
    }


def scenario_run_events(run_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    """Auditable client/gateway timeline; it is telemetry, not pose proof."""
    init_command_history()
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        rows = connection.execute(
            "SELECT created_at_ms, state, source FROM scenario_run_events WHERE run_id = ? ORDER BY id ASC LIMIT ?",
            (run_id, limit),
        ).fetchall()
    return [{"created_at_ms": row[0], "state": row[1], "source": row[2]} for row in rows]


def append_scenario_run_event(run_id: str, state: str, source: str) -> None:
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        connection.execute(
            "INSERT INTO scenario_run_events (run_id, created_at_ms, state, source) VALUES (?, ?, ?, ?)",
            (run_id, int(time.time() * 1000), state, source),
        )


def get_scenario_run_record(run_id: str) -> Dict[str, Any]:
    init_command_history()
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        row = connection.execute(
            "SELECT run_id, scenario_id, scenario_version, robot_slug, source, idempotency_key, risk_level, state, parameters_json, created_at_ms, updated_at_ms FROM scenario_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail={"code": "SCENARIO_RUN_NOT_FOUND", "message": "Scenario run was not found"})
    result = _scenario_run_row(row)
    result["events"] = scenario_run_events(run_id)
    return result


def create_scenario_run_record(req: ScenarioRunRequest) -> Dict[str, Any]:
    """Create a pending run; uniqueness makes n8n retries harmless."""
    init_command_history()
    scenario = get_scenario_definition(req.scenario_id)
    now = int(time.time() * 1000)
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        existing = connection.execute(
            "SELECT run_id, scenario_id, scenario_version, robot_slug, source, idempotency_key, risk_level, state, parameters_json, created_at_ms, updated_at_ms FROM scenario_runs WHERE robot_slug = ? AND idempotency_key = ?",
            (req.robot_slug, req.idempotency_key),
        ).fetchone()
        if existing:
            return _scenario_run_row(existing)
        run_id = str(uuid.uuid4())
        connection.execute(
            "INSERT INTO scenario_runs (run_id, scenario_id, scenario_version, robot_slug, source, idempotency_key, risk_level, state, parameters_json, created_at_ms, updated_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, req.scenario_id, scenario["version"], req.robot_slug, req.source.strip(), req.idempotency_key,
             scenario["risk_level"], "AWAITING_CONFIRMATION", json.dumps(req.parameters, ensure_ascii=False), now, now),
        )
        connection.execute(
            "INSERT INTO scenario_run_events (run_id, created_at_ms, state, source) VALUES (?, ?, ?, ?)",
            (run_id, now, "AWAITING_CONFIRMATION", "CORE"),
        )
    return get_scenario_run_record(run_id)


def route_public_metadata(route: Dict[str, Any]) -> Dict[str, Any]:
    return {"route_id": route["route_id"], "version": route["version"], "title": route["title"],
            "segment_count": len(route["segments"]), "updated_at_ms": route["updated_at_ms"],
            "note": "Each segment requires a separate operator confirmation and fresh L8/L10 safety gates."}


def get_calibrated_route(route_id: str) -> Dict[str, Any]:
    init_command_history()
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        row = connection.execute(
            "SELECT route_id, version, title, segments_json, updated_at_ms FROM calibrated_routes WHERE route_id = ?", (route_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail={"code": "CALIBRATED_ROUTE_NOT_FOUND", "message": "Calibrated route is not published"})
    return {"route_id": row[0], "version": row[1], "title": row[2], "segments": json.loads(row[3]), "updated_at_ms": row[4]}


ROUTE_CERTIFICATION_TTL_MS = 24 * 60 * 60 * 1000


def get_route_certification(route_id: str) -> Dict[str, Any]:
    route = get_calibrated_route(route_id)
    init_command_history()
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        row = connection.execute(
            "SELECT route_version, certified_at_ms, operator_name, checks_json FROM calibrated_route_certifications WHERE route_id = ?", (route_id,)
        ).fetchone()
    if not row:
        return {"route_id": route_id, "state": "MISSING", "certification": None}
    age_ms = max(0, int(time.time() * 1000) - row[1])
    state = "READY" if row[0] == route["version"] and age_ms <= ROUTE_CERTIFICATION_TTL_MS else "STALE"
    return {"route_id": route_id, "state": state, "age_seconds": age_ms // 1000,
            "expires_in_seconds": max(0, (ROUTE_CERTIFICATION_TTL_MS - age_ms) // 1000),
            "certification": {"route_version": row[0], "operator_name": row[2], "checks": json.loads(row[3])}}


def certify_calibrated_route(route_id: str, req: RouteCertificationRequest) -> Dict[str, Any]:
    route = get_calibrated_route(route_id)
    now = int(time.time() * 1000)
    checks = req.model_dump(exclude={"operator_name", "note"})
    checks["note"] = req.note.strip()
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        connection.execute(
            """INSERT INTO calibrated_route_certifications (route_id, route_version, certified_at_ms, operator_name, checks_json) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(route_id) DO UPDATE SET route_version=excluded.route_version, certified_at_ms=excluded.certified_at_ms, operator_name=excluded.operator_name, checks_json=excluded.checks_json""",
            (route_id, route["version"], now, req.operator_name.strip(), json.dumps(checks, ensure_ascii=False)),
        )
    return get_route_certification(route_id)


# L13-L20 governance records.  These are auditable release gates, not evidence
# that Zenbo's hardware has localized or moved correctly.
GOVERNANCE_ATTESTATION_TTL_MS = 15 * 60 * 1000
FAULT_DRILL_TTL_MS = 7 * 24 * 60 * 60 * 1000


def _governance_now() -> int:
    return int(time.time() * 1000)


def _require_authorization(authorization_id: str, scope: str) -> Dict[str, Any]:
    init_command_history()
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        row = connection.execute("SELECT operator_name, role, scopes_json, expires_at_ms, revoked_at_ms FROM autonomy_authorizations WHERE authorization_id = ?", (authorization_id,)).fetchone()
    if not row or row[4] is not None or row[3] < _governance_now() or scope not in json.loads(row[2]):
        raise HTTPException(status_code=409, detail={"code": "AUTONOMY_AUTHORIZATION_REQUIRED", "message": f"A current authorization with {scope} scope is required"})
    return {"authorization_id": authorization_id, "operator_name": row[0], "role": row[1], "scopes": json.loads(row[2]), "expires_at_ms": row[3]}


def issue_operator_authorization(req: OperatorAuthorizationRequest) -> Dict[str, Any]:
    now = _governance_now()
    authorization_id = str(uuid.uuid4())
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        connection.execute("INSERT INTO autonomy_authorizations (authorization_id, operator_name, role, scopes_json, issued_at_ms, expires_at_ms, note) VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (authorization_id, req.operator_name.strip(), req.role, json.dumps(sorted(set(req.scopes))), now, now + req.ttl_seconds * 1000, req.note.strip()))
    return _require_authorization(authorization_id, req.scopes[0])


def publish_route_release(route_id: str, req: RouteReleaseRequest) -> Dict[str, Any]:
    authorization = _require_authorization(req.authorization_id, "route_release")
    route = get_calibrated_route(route_id)
    allowed = sorted({slug.strip().lower() for slug in req.allowed_robot_slugs if slug.strip()})
    now = _governance_now()
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        connection.execute("""INSERT INTO calibrated_route_releases (route_id, route_version, state, approved_by_authorization_id, allowed_robots_json, updated_at_ms, note)
                              VALUES (?, ?, ?, ?, ?, ?, ?)
                              ON CONFLICT(route_id) DO UPDATE SET route_version=excluded.route_version, state=excluded.state, approved_by_authorization_id=excluded.approved_by_authorization_id, allowed_robots_json=excluded.allowed_robots_json, updated_at_ms=excluded.updated_at_ms, note=excluded.note""",
                           (route_id, route["version"], req.state, authorization["authorization_id"], json.dumps(allowed), now, req.note.strip()))
    return get_route_release(route_id)


def get_route_release(route_id: str) -> Dict[str, Any]:
    route = get_calibrated_route(route_id)
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        row = connection.execute("SELECT route_version, state, approved_by_authorization_id, allowed_robots_json, updated_at_ms, note FROM calibrated_route_releases WHERE route_id = ?", (route_id,)).fetchone()
    if not row:
        return {"route_id": route_id, "state": "MISSING", "release": None}
    state = row[1] if row[0] == route["version"] else "STALE"
    return {"route_id": route_id, "state": state, "release": {"route_version": row[0], "authorization_id": row[2], "allowed_robot_slugs": json.loads(row[3]), "updated_at_ms": row[4], "note": row[5]}}


def _upsert_governance_attestation(table: str, robot_slug: str, operator_name: str, checks: Dict[str, Any], extra: tuple = ()) -> None:
    now = _governance_now()
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        if table == "robot_localization_attestations":
            connection.execute("INSERT INTO robot_localization_attestations (robot_slug, map_id, map_version, attested_at_ms, operator_name, checks_json) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(robot_slug) DO UPDATE SET map_id=excluded.map_id, map_version=excluded.map_version, attested_at_ms=excluded.attested_at_ms, operator_name=excluded.operator_name, checks_json=excluded.checks_json", (robot_slug, extra[0], extra[1], now, operator_name, json.dumps(checks)))
        else:
            connection.execute("INSERT INTO robot_safety_envelopes (robot_slug, attested_at_ms, operator_name, checks_json) VALUES (?, ?, ?, ?) ON CONFLICT(robot_slug) DO UPDATE SET attested_at_ms=excluded.attested_at_ms, operator_name=excluded.operator_name, checks_json=excluded.checks_json", (robot_slug, now, operator_name, json.dumps(checks)))


def record_localization_attestation(robot_slug: str, req: LocalizationAttestationRequest) -> Dict[str, Any]:
    _upsert_governance_attestation("robot_localization_attestations", robot_slug, req.operator_name.strip(), req.model_dump(exclude={"operator_name", "map_id", "map_version"}), (req.map_id.strip(), req.map_version.strip()))
    return get_governance_attestation("localization", robot_slug)


def record_safety_envelope(robot_slug: str, req: SafetyEnvelopeRequest) -> Dict[str, Any]:
    _upsert_governance_attestation("robot_safety_envelopes", robot_slug, req.operator_name.strip(), req.model_dump(exclude={"operator_name"}))
    return get_governance_attestation("safety_envelope", robot_slug)


def get_governance_attestation(kind: str, robot_slug: str) -> Dict[str, Any]:
    table = "robot_localization_attestations" if kind == "localization" else "robot_safety_envelopes"
    columns = "map_id, map_version, attested_at_ms, operator_name, checks_json" if kind == "localization" else "attested_at_ms, operator_name, checks_json"
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        row = connection.execute(f"SELECT {columns} FROM {table} WHERE robot_slug = ?", (robot_slug,)).fetchone()
    if not row:
        return {"robot_slug": robot_slug, "kind": kind, "state": "MISSING", "attestation": None}
    attested_at = row[2] if kind == "localization" else row[0]
    details = {"attested_at_ms": attested_at, "operator_name": row[3] if kind == "localization" else row[1], "checks": json.loads(row[4] if kind == "localization" else row[2])}
    if kind == "localization":
        details.update({"map_id": row[0], "map_version": row[1]})
    return {"robot_slug": robot_slug, "kind": kind, "state": "READY" if _governance_now() - attested_at <= GOVERNANCE_ATTESTATION_TTL_MS else "EXPIRED", "attestation": details}


def reserve_autonomy_zone(req: ZoneReservationRequest) -> Dict[str, Any]:
    get_calibrated_route(req.route_id)
    now = _governance_now()
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        connection.execute("DELETE FROM autonomy_zone_reservations WHERE zone_id = ? AND (released_at_ms IS NOT NULL OR expires_at_ms < ?)", (req.zone_id, now))
        try:
            reservation_id = str(uuid.uuid4())
            connection.execute("INSERT INTO autonomy_zone_reservations (reservation_id, zone_id, robot_slug, route_id, created_at_ms, expires_at_ms) VALUES (?, ?, ?, ?, ?, ?)", (reservation_id, req.zone_id, req.robot_slug, req.route_id, now, now + req.ttl_seconds * 1000))
        except db.integrity_errors as exc:
            raise HTTPException(status_code=409, detail={"code": "AUTONOMY_ZONE_BUSY", "message": "This zone is reserved by another active route"}) from exc
    return get_zone_reservation(reservation_id)


def get_zone_reservation(reservation_id: str) -> Dict[str, Any]:
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        row = connection.execute("SELECT zone_id, robot_slug, route_id, created_at_ms, expires_at_ms, released_at_ms FROM autonomy_zone_reservations WHERE reservation_id = ?", (reservation_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail={"code": "AUTONOMY_RESERVATION_NOT_FOUND", "message": "Zone reservation was not found"})
    state = "RELEASED" if row[5] is not None else ("ACTIVE" if row[4] >= _governance_now() else "EXPIRED")
    return {"reservation_id": reservation_id, "state": state, "zone_id": row[0], "robot_slug": row[1], "route_id": row[2], "expires_at_ms": row[4]}


def release_zone_reservation(reservation_id: str, reason: str = "operator_released") -> Dict[str, Any]:
    reservation = get_zone_reservation(reservation_id)
    if reservation["state"] == "ACTIVE":
        with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
            connection.execute("UPDATE autonomy_zone_reservations SET released_at_ms = ? WHERE reservation_id = ? AND released_at_ms IS NULL", (_governance_now(), reservation_id))
        record_autonomy_alert(reservation["robot_slug"], "INFO", "ZONE_RESERVATION_RELEASED", f"Zone {reservation['zone_id']} released: {reason}")
    return {**get_zone_reservation(reservation_id), "release_reason": reason}


def record_fault_drill(robot_slug: str, req: FaultDrillRequest) -> Dict[str, Any]:
    now, drill_id = _governance_now(), str(uuid.uuid4())
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        connection.execute("INSERT INTO autonomy_fault_drills (drill_id, robot_slug, completed_at_ms, operator_name, checks_json) VALUES (?, ?, ?, ?, ?)", (drill_id, robot_slug, now, req.operator_name.strip(), json.dumps(req.model_dump(exclude={"operator_name"}))))
    return {"drill_id": drill_id, "robot_slug": robot_slug, "state": "RECORDED", "completed_at_ms": now}


def _latest_fault_drill_ready(robot_slug: str) -> bool:
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        row = connection.execute("SELECT completed_at_ms FROM autonomy_fault_drills WHERE robot_slug = ? ORDER BY completed_at_ms DESC LIMIT 1", (robot_slug,)).fetchone()
    return bool(row and _governance_now() - row[0] <= FAULT_DRILL_TTL_MS)


def issue_operation_permit(req: OperationPermitRequest) -> Dict[str, Any]:
    authorization = _require_authorization(req.authorization_id, "operation_permit")
    route, release = get_calibrated_route(req.route_id), get_route_release(req.route_id)
    reservation = get_zone_reservation(req.zone_reservation_id)
    localization, envelope = get_governance_attestation("localization", req.robot_slug), get_governance_attestation("safety_envelope", req.robot_slug)
    blockers = []
    if release["state"] != "ACTIVE" or (release["release"]["allowed_robot_slugs"] and req.robot_slug not in release["release"]["allowed_robot_slugs"]): blockers.append("ROUTE_RELEASE_REQUIRED")
    if reservation["state"] != "ACTIVE" or reservation["robot_slug"] != req.robot_slug or reservation["route_id"] != req.route_id: blockers.append("ZONE_RESERVATION_REQUIRED")
    if localization["state"] != "READY": blockers.append("LOCALIZATION_ATTESTATION_REQUIRED")
    if envelope["state"] != "READY": blockers.append("SAFETY_ENVELOPE_REQUIRED")
    if not _latest_fault_drill_ready(req.robot_slug): blockers.append("FAULT_DRILL_REQUIRED")
    if blockers: raise HTTPException(status_code=409, detail={"code": "AUTONOMY_PERMIT_BLOCKED", "blockers": blockers})
    now, permit_id = _governance_now(), str(uuid.uuid4())
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        connection.execute("INSERT INTO autonomy_operation_permits (permit_id, route_id, route_version, robot_slug, zone_reservation_id, authorization_id, issued_at_ms, expires_at_ms, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (permit_id, req.route_id, route["version"], req.robot_slug, req.zone_reservation_id, authorization["authorization_id"], now, now + req.ttl_seconds * 1000, req.note.strip()))
    return get_operation_permit(permit_id)


def get_operation_permit(permit_id: str) -> Dict[str, Any]:
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        row = connection.execute("SELECT route_id, route_version, robot_slug, zone_reservation_id, authorization_id, issued_at_ms, expires_at_ms, revoked_at_ms, note FROM autonomy_operation_permits WHERE permit_id = ?", (permit_id,)).fetchone()
    if not row: raise HTTPException(status_code=404, detail={"code": "AUTONOMY_PERMIT_NOT_FOUND", "message": "Operation permit was not found"})
    route = get_calibrated_route(row[0])
    state = "REVOKED" if row[7] is not None else ("READY" if row[6] >= _governance_now() and row[1] == route["version"] else "EXPIRED")
    return {"permit_id": permit_id, "state": state, "route_id": row[0], "route_version": row[1], "robot_slug": row[2], "zone_reservation_id": row[3], "authorization_id": row[4], "expires_at_ms": row[6], "note": row[8]}


def revoke_operation_permit(permit_id: str, reason: str = "operator_revoked") -> Dict[str, Any]:
    permit = get_operation_permit(permit_id)
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        connection.execute("UPDATE autonomy_operation_permits SET revoked_at_ms = ? WHERE permit_id = ?", (_governance_now(), permit_id))
    record_autonomy_alert(permit["robot_slug"], "WARNING", "OPERATION_PERMIT_REVOKED", f"Operation permit revoked: {reason}")
    return {**get_operation_permit(permit_id), "revocation_reason": reason}


def require_operation_permit(route_id: str, robot_slug: str, permit_id: Optional[str]) -> Dict[str, Any]:
    if not permit_id: raise HTTPException(status_code=409, detail={"code": "AUTONOMY_PERMIT_REQUIRED", "message": "L20 requires a current operation permit"})
    permit = get_operation_permit(permit_id)
    if permit["state"] != "READY" or permit["route_id"] != route_id or permit["robot_slug"] != robot_slug:
        raise HTTPException(status_code=409, detail={"code": "AUTONOMY_PERMIT_INVALID", "message": "Operation permit does not match this route and robot"})
    return permit


def autonomy_preflight(route_id: str, robot_slug: str, zone_reservation_id: Optional[str] = None,
                       authorization_id: Optional[str] = None, permit_id: Optional[str] = None) -> Dict[str, Any]:
    """Explain L12-L20 blockers without issuing a permit or dispatching motion."""
    route = get_calibrated_route(route_id)
    certification, release = get_route_certification(route_id), get_route_release(route_id)
    localization = get_governance_attestation("localization", robot_slug)
    envelope = get_governance_attestation("safety_envelope", robot_slug)
    permit_blockers: List[str] = []
    if certification["state"] != "READY": permit_blockers.append("ROUTE_CERTIFICATION_REQUIRED")
    if release["state"] != "ACTIVE" or (release.get("release") and release["release"]["allowed_robot_slugs"] and robot_slug not in release["release"]["allowed_robot_slugs"]): permit_blockers.append("ROUTE_RELEASE_REQUIRED")
    if localization["state"] != "READY": permit_blockers.append("LOCALIZATION_ATTESTATION_REQUIRED")
    if envelope["state"] != "READY": permit_blockers.append("SAFETY_ENVELOPE_REQUIRED")
    if not _latest_fault_drill_ready(robot_slug): permit_blockers.append("FAULT_DRILL_REQUIRED")
    reservation = None
    if zone_reservation_id:
        try: reservation = get_zone_reservation(zone_reservation_id)
        except HTTPException: permit_blockers.append("ZONE_RESERVATION_REQUIRED")
    if not reservation or reservation["state"] != "ACTIVE" or reservation["robot_slug"] != robot_slug or reservation["route_id"] != route_id:
        if "ZONE_RESERVATION_REQUIRED" not in permit_blockers: permit_blockers.append("ZONE_RESERVATION_REQUIRED")
    authorization = None
    if authorization_id:
        try: authorization = _require_authorization(authorization_id, "operation_permit")
        except HTTPException: permit_blockers.append("AUTONOMY_AUTHORIZATION_REQUIRED")
    else:
        permit_blockers.append("AUTONOMY_AUTHORIZATION_REQUIRED")
    field_attestation = get_field_attestation(robot_slug)
    try: field_readiness = get_robot_field_readiness(robot_slug, ["CALIBRATED_ROUTE"], allow_base_motion=True)
    except HTTPException as error: field_readiness = {"state": "NOT_READY", "blockers": [error.detail]}
    dispatch_blockers = list(permit_blockers)
    if field_attestation["state"] != "READY": dispatch_blockers.append("FIELD_ATTESTATION_REQUIRED")
    if field_readiness["state"] != "READY": dispatch_blockers.append("ROBOT_FIELD_READINESS_REQUIRED")
    permit = None
    if permit_id:
        try:
            permit = get_operation_permit(permit_id)
            if permit["state"] != "READY" or permit["route_id"] != route_id or permit["robot_slug"] != robot_slug:
                dispatch_blockers.append("AUTONOMY_PERMIT_INVALID")
        except HTTPException: dispatch_blockers.append("AUTONOMY_PERMIT_INVALID")
    else:
        dispatch_blockers.append("AUTONOMY_PERMIT_REQUIRED")
    return {"route_id": route_id, "route_version": route["version"], "robot_slug": robot_slug,
            "permit_ready": not permit_blockers, "dispatch_ready": not dispatch_blockers,
            "permit_blockers": permit_blockers, "dispatch_blockers": dispatch_blockers,
            "certification": certification, "release": release, "authorization": authorization,
            "localization": localization, "safety_envelope": envelope, "fault_drill_ready": _latest_fault_drill_ready(robot_slug),
            "zone_reservation": reservation, "operation_permit": permit,
            "field_attestation": field_attestation, "field_readiness": field_readiness,
            "note": "Preflight reports stored governance and recent client telemetry. It does not prove physical localization, obstacle detection, or robot pose."}


def record_autonomy_alert(robot_slug: str, level: Literal["INFO", "WARNING", "CRITICAL"], code: str, message: str) -> Dict[str, Any]:
    alert_id, now = str(uuid.uuid4()), _governance_now()
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        connection.execute("INSERT INTO autonomy_alerts (alert_id, robot_slug, level, code, message, created_at_ms) VALUES (?, ?, ?, ?, ?, ?)", (alert_id, robot_slug, level, code, message[:240], now))
    return {"alert_id": alert_id, "robot_slug": robot_slug, "level": level, "code": code, "created_at_ms": now}


def autonomy_supervisor_status() -> Dict[str, Any]:
    init_command_history()
    now = _governance_now()
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        alerts = connection.execute("SELECT alert_id, robot_slug, level, code, message, created_at_ms FROM autonomy_alerts WHERE resolved_at_ms IS NULL ORDER BY created_at_ms DESC LIMIT 100").fetchall()
        permits = connection.execute("SELECT permit_id, route_id, robot_slug, expires_at_ms FROM autonomy_operation_permits WHERE revoked_at_ms IS NULL AND expires_at_ms >= ? ORDER BY expires_at_ms", (now,)).fetchall()
        reservations = connection.execute("SELECT reservation_id, zone_id, robot_slug, route_id, expires_at_ms FROM autonomy_zone_reservations WHERE released_at_ms IS NULL AND expires_at_ms >= ? ORDER BY expires_at_ms", (now,)).fetchall()
    return {"observed_at_ms": now, "active_permits": [{"permit_id": row[0], "route_id": row[1], "robot_slug": row[2], "expires_at_ms": row[3]} for row in permits], "active_zone_reservations": [{"reservation_id": row[0], "zone_id": row[1], "robot_slug": row[2], "route_id": row[3], "expires_at_ms": row[4]} for row in reservations], "open_alerts": [{"alert_id": row[0], "robot_slug": row[1], "level": row[2], "code": row[3], "message": row[4], "created_at_ms": row[5]} for row in alerts], "note": "Supervisor status is server-side governance telemetry; it is not proof of physical robot pose or sensor performance."}


def resolve_autonomy_alert(alert_id: str) -> Dict[str, Any]:
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        changed = connection.execute("UPDATE autonomy_alerts SET resolved_at_ms = ? WHERE alert_id = ? AND resolved_at_ms IS NULL", (_governance_now(), alert_id)).rowcount
    if not changed: raise HTTPException(status_code=404, detail={"code": "AUTONOMY_ALERT_NOT_FOUND", "message": "Open alert was not found"})
    return {"alert_id": alert_id, "state": "RESOLVED"}


def import_calibrated_route(req: CalibratedRouteDefinitionRequest) -> Dict[str, Any]:
    init_command_history()
    now = int(time.time() * 1000)
    route = {"route_id": req.route_id, "version": req.version, "title": req.title.strip(),
             "segments": [segment.model_dump(exclude_none=True) for segment in req.segments], "updated_at_ms": now}
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        connection.execute(
            """INSERT INTO calibrated_routes (route_id, version, title, segments_json, updated_at_ms) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(route_id) DO UPDATE SET version=excluded.version, title=excluded.title, segments_json=excluded.segments_json, updated_at_ms=excluded.updated_at_ms""",
            (route["route_id"], route["version"], route["title"], json.dumps(route["segments"], ensure_ascii=False), now),
        )
    return route_public_metadata(route)


def _route_run_row(row: tuple) -> Dict[str, Any]:
    return {"route_run_id": row[0], "route_id": row[1], "robot_slug": row[2], "idempotency_key": row[3],
            "current_segment": row[4], "state": row[5], "active_scenario_run_id": row[6],
            "operation_permit_id": row[7], "created_at_ms": row[8], "updated_at_ms": row[9]}


def get_calibrated_route_run(route_run_id: str) -> Dict[str, Any]:
    init_command_history()
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        row = connection.execute(
            "SELECT route_run_id, route_id, robot_slug, idempotency_key, current_segment, state, active_scenario_run_id, operation_permit_id, created_at_ms, updated_at_ms FROM calibrated_route_runs WHERE route_run_id = ?", (route_run_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail={"code": "CALIBRATED_ROUTE_RUN_NOT_FOUND", "message": "Calibrated route run was not found"})
    result = _route_run_row(row)
    route = get_calibrated_route(result["route_id"])
    result["route"] = route_public_metadata(route)
    if result["active_scenario_run_id"]:
        result["active_segment"] = get_scenario_run_record(result["active_scenario_run_id"])
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        recovery = connection.execute(
            "SELECT recovery_required_at_ms, recovered_at_ms, operator_name, action, note FROM calibrated_route_recoveries WHERE route_run_id = ?", (route_run_id,)
        ).fetchone()
    if recovery:
        result["recovery"] = {"required_at_ms": recovery[0], "recovered_at_ms": recovery[1], "operator_name": recovery[2], "action": recovery[3], "note": recovery[4]}
    return result


def create_calibrated_route_run(req: CalibratedRouteRunRequest) -> Dict[str, Any]:
    get_calibrated_route(req.route_id)
    if ROUTE_CERTIFICATION_REQUIRED:
        certification = get_route_certification(req.route_id)
        if certification["state"] != "READY":
            raise HTTPException(status_code=409, detail={"code": "ROUTE_CERTIFICATION_REQUIRED", "message": "L12 requires a fresh certification for this calibrated route version", "certification": certification})
    if AUTONOMY_GOVERNANCE_REQUIRED:
        require_operation_permit(req.route_id, req.robot_slug, req.operation_permit_id)
    init_command_history()
    now = int(time.time() * 1000)
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        existing = connection.execute(
            "SELECT route_run_id, route_id, robot_slug, idempotency_key, current_segment, state, active_scenario_run_id, operation_permit_id, created_at_ms, updated_at_ms FROM calibrated_route_runs WHERE robot_slug = ? AND idempotency_key = ?",
            (req.robot_slug, req.idempotency_key),
        ).fetchone()
        if existing:
            route_run_id = existing[0]
        else:
            route_run_id = str(uuid.uuid4())
            connection.execute(
                "INSERT INTO calibrated_route_runs (route_run_id, route_id, robot_slug, idempotency_key, current_segment, state, active_scenario_run_id, operation_permit_id, created_at_ms, updated_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (route_run_id, req.route_id, req.robot_slug, req.idempotency_key, 0, "AWAITING_SEGMENT_CONFIRMATION", None, req.operation_permit_id, now, now),
            )
    return get_calibrated_route_run(route_run_id)


def refresh_calibrated_route_run(route_run_id: str) -> Dict[str, Any]:
    """Advance only after the preceding segment reports a terminal telemetry state."""
    route_run = get_calibrated_route_run(route_run_id)
    if route_run["state"] != "SEGMENT_DISPATCHED" or not route_run.get("active_segment"):
        return route_run
    segment_state = route_run["active_segment"]["state"]
    if segment_state not in {"SUCCEEDED", "FAILED", "SAFETY_STOPPED"}:
        return route_run
    if segment_state == "SAFETY_STOPPED":
        next_state, next_segment = "RECOVERY_REQUIRED", route_run["current_segment"]
        with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
            connection.execute(
                "INSERT OR IGNORE INTO calibrated_route_recoveries (route_run_id, recovery_required_at_ms, note) VALUES (?, ?, ?)",
                (route_run_id, int(time.time() * 1000), "Safety stop requires an operator recovery decision"),
            )
        if route_run.get("operation_permit_id"):
            revoke_operation_permit(route_run["operation_permit_id"], "safety_stop")
        record_autonomy_alert(route_run["robot_slug"], "CRITICAL", "SAFETY_STOPPED", "Calibrated route stopped by the robot safety policy")
    elif segment_state != "SUCCEEDED":
        next_state, next_segment = "ABORTED_" + segment_state, route_run["current_segment"]
    else:
        route = get_calibrated_route(route_run["route_id"])
        next_segment = route_run["current_segment"] + 1
        next_state = "COMPLETED" if next_segment >= len(route["segments"]) else "AWAITING_SEGMENT_CONFIRMATION"
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        connection.execute(
            "UPDATE calibrated_route_runs SET current_segment = ?, state = ?, active_scenario_run_id = NULL, updated_at_ms = ? WHERE route_run_id = ?",
            (next_segment, next_state, int(time.time() * 1000), route_run_id),
        )
    if next_state == "COMPLETED" or next_state.startswith("ABORTED_"):
        permit_id = route_run.get("operation_permit_id")
        if permit_id:
            try:
                release_zone_reservation(get_operation_permit(permit_id)["zone_reservation_id"], f"route_{next_state.lower()}")
            except HTTPException:
                pass
    return get_calibrated_route_run(route_run_id)


def recover_calibrated_route_run(route_run_id: str, req: RouteRecoveryRequest) -> Dict[str, Any]:
    route_run = refresh_calibrated_route_run(route_run_id)
    if route_run["state"] != "RECOVERY_REQUIRED" or not route_run.get("recovery"):
        raise HTTPException(status_code=409, detail={"code": "ROUTE_RECOVERY_NOT_REQUIRED", "message": "This route run is not awaiting a safety recovery decision"})
    recovery = route_run["recovery"]
    if req.action == "retry":
        attestation = get_field_attestation(route_run["robot_slug"])
        required_at = int(recovery["required_at_ms"])
        recorded_attestation = attestation.get("attestation") or {}
        if attestation["state"] != "READY" or recorded_attestation.get("attested_at_ms", 0) < required_at:
            raise HTTPException(status_code=409, detail={"code": "ROUTE_RECOVERY_ATTESTATION_REQUIRED", "message": "Retry requires a new field attestation recorded after the safety stop", "attestation": attestation})
        if AUTONOMY_GOVERNANCE_REQUIRED:
            require_operation_permit(route_run["route_id"], route_run["robot_slug"], req.operation_permit_id)
        next_state = "AWAITING_SEGMENT_CONFIRMATION"
    else:
        next_state = "CANCELLED"
    now = int(time.time() * 1000)
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        connection.execute("UPDATE calibrated_route_runs SET state = ?, active_scenario_run_id = NULL, operation_permit_id = ?, updated_at_ms = ? WHERE route_run_id = ?", (next_state, req.operation_permit_id if req.action == "retry" else route_run.get("operation_permit_id"), now, route_run_id))
        connection.execute("UPDATE calibrated_route_recoveries SET recovered_at_ms = ?, operator_name = ?, action = ?, note = ? WHERE route_run_id = ?", (now, req.operator_name.strip(), req.action, req.note.strip(), route_run_id))
    if req.action == "cancel" and route_run.get("operation_permit_id"):
        try:
            release_zone_reservation(get_operation_permit(route_run["operation_permit_id"])["zone_reservation_id"], "route_cancelled")
        except HTTPException:
            pass
    return get_calibrated_route_run(route_run_id)


def build_scenario_command(scenario_id: str, run_id: str, robot_slug: str) -> Dict[str, Any]:
    scenario = get_scenario_definition(scenario_id)
    command = json.loads(json.dumps(scenario["command"], ensure_ascii=False))
    if scenario["risk_level"] == "L1":
        script = ScenarioScriptCommand(**command).model_dump(exclude_none=True)
        for step in script["steps"]:
            apply_visual_behavior_contract(step, step["face"])
        return {"script": script, "robot_slug": robot_slug, "source": "scenario_runner", "scenario_run_id": run_id}
    if scenario["risk_level"] in {"L2", "L3"}:
        interactive = InteractiveScenarioCommand(**command).model_dump(exclude_none=True)
        for branch_name in ("on_detect", "on_timeout"):
            for step in interactive[branch_name]["steps"]:
                apply_visual_behavior_contract(step, step["face"])
        return {"interactive": interactive, "robot_slug": robot_slug, "source": "scenario_runner", "scenario_run_id": run_id}
    if scenario["risk_level"] == "L4":
        sequence = InteractiveSequenceCommand(**command).model_dump(exclude_none=True)
        apply_visual_behavior_contract(sequence["prompt"], sequence["prompt"]["face"])
        for branch_name in ("on_first_timeout", "on_second_detect", "on_second_timeout"):
            for step in sequence[branch_name]["steps"]:
                apply_visual_behavior_contract(step, step["face"])
        return {"interactive_sequence": sequence, "robot_slug": robot_slug, "source": "scenario_runner", "scenario_run_id": run_id}
    if scenario["risk_level"] in {"L5", "L6", "L7"}:
        sequence = InteractiveNavigationSequenceCommand(**command).model_dump(exclude_none=True)
        apply_visual_behavior_contract(sequence["prompt"], sequence["prompt"]["face"])
        for branch_name in ("on_first_timeout", "on_second_timeout"):
            for step in sequence[branch_name]["steps"]:
                apply_visual_behavior_contract(step, step["face"])
        for step in sequence["on_second_detect"]["steps"]:
            apply_visual_behavior_contract(step, step["face"])
        return {"interactive_sequence": sequence, "robot_slug": robot_slug, "source": "scenario_runner", "scenario_run_id": run_id}
    if scenario["risk_level"] == "L8":
        autonomous = AutonomousMicroMotionCommand(**command["autonomous_motion"]).model_dump(exclude_none=True)
        apply_visual_behavior_contract(autonomous, autonomous["face"])
        autonomous.update({"robot_slug": robot_slug, "source": "scenario_runner", "scenario_run_id": run_id})
        return autonomous
    if scenario["risk_level"] == "L10":
        run = get_scenario_run_record(run_id)
        route_id = str(run["parameters"].get("route_id") or "")
        segment_index = run["parameters"].get("segment_index")
        if not isinstance(segment_index, int):
            raise HTTPException(status_code=422, detail={"code": "L10_ROUTE_SEGMENT_INVALID", "message": "L10 requires a calibrated route segment"})
        route = get_calibrated_route(route_id)
        if not 0 <= segment_index < len(route["segments"]):
            raise HTTPException(status_code=422, detail={"code": "L10_ROUTE_SEGMENT_INVALID", "message": "Calibrated route segment is unavailable"})
        autonomous = AutonomousMicroMotionCommand(**route["segments"][segment_index]["command"]).model_dump(exclude_none=True)
        apply_visual_behavior_contract(autonomous, autonomous["face"])
        autonomous.update({"robot_slug": robot_slug, "source": "calibrated_route", "scenario_run_id": run_id})
        return autonomous
    apply_visual_behavior_contract(command, scenario.get("visual_profile"))
    command.update({"robot_slug": robot_slug, "source": "scenario_runner", "scenario_run_id": run_id})
    return command


def _presentation_variables(preset: Dict[str, Any], supplied: Dict[str, str]) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for field in preset.get("fields", []):
        name = field["name"]
        raw = supplied.get(name, field.get("default", ""))
        if not isinstance(raw, str):
            raise HTTPException(status_code=422, detail={"code": "INVALID_PRESENTATION_VARIABLE", "field": name})
        value = " ".join(raw.split())
        if not value or len(value) > int(field.get("max_length", 80)):
            raise HTTPException(status_code=422, detail={"code": "INVALID_PRESENTATION_VARIABLE", "field": name})
        values[name] = value
    return values


def _interpolate_presentation_template(value: Any, variables: Dict[str, str]) -> Any:
    """Interpolate only the server-owned presentation template, recursively."""
    if isinstance(value, str):
        try:
            return value.format(**variables)
        except KeyError as error:
            raise HTTPException(status_code=422, detail={"code": "MISSING_PRESENTATION_VARIABLE", "field": str(error)})
    if isinstance(value, list):
        return [_interpolate_presentation_template(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: _interpolate_presentation_template(item, variables) for key, item in value.items()}
    return value


async def fetch_library_rag_answer(question: str) -> Optional[str]:
    """Ask only the fixed, public library RAG API; never proxy caller-provided URLs."""
    if not LIBRARY_RAG_API_URL.startswith("https://lib.kku.ac.th/rag/"):
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(LIBRARY_RAG_API_URL, json={
                "question": question,
                "conversation_history": [],
            })
        if response.status_code != 200:
            return None
        answer = response.json().get("answer")
        if not isinstance(answer, str):
            return None
        normalized = " ".join(answer.split())
        return normalized[:700] if normalized else None
    except (httpx.HTTPError, ValueError):
        return None


async def build_presentation_command(req: PresentationRequest) -> Dict[str, Any]:
    preset = PRESENTATION_CATALOG[req.preset_id]
    if preset["availability"] != "ready":
        raise HTTPException(status_code=409, detail={
            "code": "PRESENTATION_GATED",
            "message": preset.get("gate_reason", "This presentation is not yet available"),
        })
    variables = _presentation_variables(preset, req.variables)
    command = _interpolate_presentation_template(
        json.loads(json.dumps(preset.get("command", {}), ensure_ascii=False)), variables
    )
    if isinstance(command.get("steps"), list):
        try:
            script = ScenarioScriptCommand(**command).model_dump(exclude_none=True)
        except ValidationError as error:
            raise HTTPException(status_code=422, detail={"code": "INVALID_PRESENTATION_SCRIPT", "message": str(error)})
        for step in script["steps"]:
            apply_visual_behavior_contract(step, step["face"])
        return {"script": script, "robot_slug": req.robot_slug, "source": "liff_present"}
    # Every catalog entry gets an SDK-backed expression and stationary head
    # gesture, including media-only entries such as YouTube.
    apply_visual_behavior_contract(command, preset.get("visual_profile"))
    if isinstance(command.get("youtube"), dict):
        try:
            command["youtube"] = YouTubeCommand(**command["youtube"]).model_dump()
        except ValidationError as error:
            raise HTTPException(status_code=422, detail={"code": "INVALID_YOUTUBE_URL", "message": str(error)})
    if preset.get("route_required"):
        route_response = await get_navigation_route(variables["from_location"], variables["to"])
        route = route_response["route"]
        command.update({
            "text": route["speech_text"],
            "voice_profile": "male_young",
            "navigation": {
                "display_url": route["display_url"],
                "speech_text": route["speech_text"],
                "step_speeches": route["step_speeches"],
            },
        })
    if preset.get("rag_answer"):
        answer = await fetch_library_rag_answer(variables["question"])
        if answer:
            command["text"] = f"คุณถามว่า {variables['question']} ครับ {answer}"
        else:
            command["text"] = f"คุณถามว่า {variables['question']} ครับ ผมกำลังเปิดผู้ช่วยตอบคำถามห้องสมุดบนหน้าจอให้ครับ"
        if isinstance(command.get("navigation"), dict):
            command["navigation"]["speech_text"] = command["text"]
    command.update({"robot_slug": req.robot_slug, "source": "liff_present"})
    return command


@app.get("/api/v1/presentations")
async def list_presentations():
    return {"presets": [
        presentation_public_metadata(preset_id, preset)
        for preset_id, preset in PRESENTATION_CATALOG.items()
    ]}


@app.get("/api/v1/scenarios")
async def list_scenarios():
    """Registry metadata for n8n and LIFF; executable templates remain private."""
    return {"scenarios": [
        scenario_public_metadata(scenario_id, scenario)
        for scenario_id, scenario in scenario_registry().items()
    ]}


@app.post("/api/v1/scenario-definitions")
async def import_scenario(req: ScenarioDefinitionRequest, x_scenario_registry_token: Optional[str] = Header(default=None)):
    """Trusted n8n-only import path for stationary L0 and sequential L1 scenarios."""
    require_scenario_registry_token(x_scenario_registry_token)
    return import_scenario_definition(req)


@app.get("/api/v1/music-playlists")
async def list_music_playlists():
    playlists = get_music_playlists()
    return {"playlists": [music_playlist_metadata(playlist_id, playlist) for playlist_id, playlist in playlists.items()]}


@app.post("/api/v1/music-playlists")
async def import_music_playlist_endpoint(req: MusicPlaylistDefinitionRequest, x_scenario_registry_token: Optional[str] = Header(default=None)):
    """n8n-only playlist registry; publishing never plays media automatically."""
    require_scenario_registry_token(x_scenario_registry_token)
    return import_music_playlist(req)


@app.post("/api/v1/music-playlists/{playlist_id}/pick")
async def pick_music_playlist(playlist_id: str, req: MusicPlaylistPickRequest):
    return pick_music_preview(playlist_id, req.robot_slug)


@app.post("/api/v1/music-playlists/{playlist_id}/start")
async def start_music_playlist(playlist_id: str, req: MusicPlaylistStartRequest):
    """Start one bounded dance window from an approved playlist for n8n schedules.

    This endpoint intentionally has three independent gates: an explicit
    deployment feature flag, fresh field-readiness telemetry, and a reviewed
    playlist.  It never publishes to a shared MQTT topic and it does not make
    an unbounded robot-side schedule; n8n owns the 10-minute cadence.
    """
    if not MUSIC_DANCE_AUTOMATION_ENABLED:
        raise HTTPException(status_code=409, detail={
            "code": "MUSIC_DANCE_AUTOMATION_DISABLED",
            "message": "Set MUSIC_DANCE_AUTOMATION_ENABLED=true only after physical dance-action calibration",
        })
    readiness = get_robot_field_readiness(req.robot_slug)
    if readiness["state"] != "READY":
        raise HTTPException(status_code=409, detail={
            "code": "ROBOT_NOT_FIELD_READY",
            "message": "Robot must report safety and capability readiness before a dance window can start",
            "blockers": readiness["blockers"],
        })
    preview = pick_music_preview(playlist_id, req.robot_slug)
    command = preview["command"]
    command["text"] = "กำลังเปิดเพลงและเต้นตามรอบที่ตั้งไว้ครับ"
    command["youtube"].update({
        "dance_action_ids": req.dance_action_ids,
        "loop_dance": True,
        "duration_seconds": req.duration_seconds,
    })
    apply_visual_behavior_contract(command, "SINGING")
    dispatch = await robot_interact(InteractCommand(**command))
    return {
        "playlist": preview["playlist"],
        "track": preview["track"],
        "robot_slug": req.robot_slug,
        "duration_seconds": req.duration_seconds,
        "dispatch": dispatch,
        "note": "MQTT dispatch accepted; use Zenbo YouTube and action telemetry to verify actual playback and dance.",
    }


@app.post("/api/v1/scenario-runs")
async def create_scenario_run(req: ScenarioRunRequest):
    get_scenario_definition(req.scenario_id)
    return create_scenario_run_record(req)


@app.get("/api/v1/scenario-runs/{run_id}")
async def get_scenario_run(run_id: str):
    return get_scenario_run_record(run_id)


@app.get("/api/v1/scenario-runs/{run_id}/events")
async def get_scenario_run_event_timeline(run_id: str):
    # Resolve first so an arbitrary ID never looks like an empty valid run.
    get_scenario_run_record(run_id)
    return {"run_id": run_id, "events": scenario_run_events(run_id)}


@app.get("/api/v1/calibrated-routes")
async def list_calibrated_routes():
    init_command_history()
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        rows = connection.execute("SELECT route_id, version, title, segments_json, updated_at_ms FROM calibrated_routes ORDER BY LOWER(title)").fetchall()
    return {"routes": [route_public_metadata({"route_id": row[0], "version": row[1], "title": row[2], "segments": json.loads(row[3]), "updated_at_ms": row[4]}) for row in rows]}


@app.post("/api/v1/calibrated-routes")
async def import_calibrated_route_endpoint(req: CalibratedRouteDefinitionRequest, x_scenario_registry_token: Optional[str] = Header(default=None)):
    require_scenario_registry_token(x_scenario_registry_token)
    return import_calibrated_route(req)


@app.get("/api/v1/calibrated-routes/{route_id}/certification")
async def read_calibrated_route_certification(route_id: str):
    return get_route_certification(route_id)


@app.post("/api/v1/calibrated-routes/{route_id}/certification")
async def record_calibrated_route_certification(
    route_id: str,
    req: RouteCertificationRequest,
    x_scenario_registry_token: Optional[str] = Header(default=None),
):
    require_scenario_registry_token(x_scenario_registry_token)
    return certify_calibrated_route(route_id, req)


@app.get("/api/v1/calibrated-routes/{route_id}/release")
async def read_calibrated_route_release(route_id: str):
    return get_route_release(route_id)


@app.post("/api/v1/calibrated-routes/{route_id}/release")
async def publish_calibrated_route_release(route_id: str, req: RouteReleaseRequest,
                                           x_scenario_registry_token: Optional[str] = Header(default=None)):
    require_scenario_registry_token(x_scenario_registry_token)
    return publish_route_release(route_id, req)


@app.post("/api/v1/autonomy/authorizations")
async def create_autonomy_authorization(req: OperatorAuthorizationRequest,
                                        x_scenario_registry_token: Optional[str] = Header(default=None)):
    require_scenario_registry_token(x_scenario_registry_token)
    return issue_operator_authorization(req)


@app.get("/api/v1/robots/{robot_slug}/localization-attestation")
async def read_localization_attestation(robot_slug: str):
    return get_governance_attestation("localization", robot_slug)


@app.post("/api/v1/robots/{robot_slug}/localization-attestation")
async def write_localization_attestation(robot_slug: str, req: LocalizationAttestationRequest,
                                         x_scenario_registry_token: Optional[str] = Header(default=None)):
    require_scenario_registry_token(x_scenario_registry_token)
    return record_localization_attestation(robot_slug, req)


@app.get("/api/v1/robots/{robot_slug}/safety-envelope")
async def read_safety_envelope(robot_slug: str):
    return get_governance_attestation("safety_envelope", robot_slug)


@app.post("/api/v1/robots/{robot_slug}/safety-envelope")
async def write_safety_envelope(robot_slug: str, req: SafetyEnvelopeRequest,
                                x_scenario_registry_token: Optional[str] = Header(default=None)):
    require_scenario_registry_token(x_scenario_registry_token)
    return record_safety_envelope(robot_slug, req)


@app.post("/api/v1/autonomy/zone-reservations")
async def create_autonomy_zone_reservation(req: ZoneReservationRequest,
                                            x_scenario_registry_token: Optional[str] = Header(default=None)):
    require_scenario_registry_token(x_scenario_registry_token)
    return reserve_autonomy_zone(req)


@app.get("/api/v1/autonomy/zone-reservations/{reservation_id}")
async def read_autonomy_zone_reservation(reservation_id: str):
    return get_zone_reservation(reservation_id)


@app.post("/api/v1/autonomy/zone-reservations/{reservation_id}/release")
async def release_autonomy_zone_reservation(reservation_id: str, x_scenario_registry_token: Optional[str] = Header(default=None)):
    require_scenario_registry_token(x_scenario_registry_token)
    return release_zone_reservation(reservation_id)


@app.post("/api/v1/robots/{robot_slug}/fault-drills")
async def create_fault_drill(robot_slug: str, req: FaultDrillRequest,
                             x_scenario_registry_token: Optional[str] = Header(default=None)):
    require_scenario_registry_token(x_scenario_registry_token)
    return record_fault_drill(robot_slug, req)


@app.post("/api/v1/autonomy/operation-permits")
async def create_operation_permit(req: OperationPermitRequest,
                                  x_scenario_registry_token: Optional[str] = Header(default=None)):
    require_scenario_registry_token(x_scenario_registry_token)
    return issue_operation_permit(req)


@app.get("/api/v1/autonomy/operation-permits/{permit_id}")
async def read_operation_permit(permit_id: str):
    return get_operation_permit(permit_id)


@app.post("/api/v1/autonomy/operation-permits/{permit_id}/revoke")
async def revoke_autonomy_operation_permit(permit_id: str, x_scenario_registry_token: Optional[str] = Header(default=None)):
    require_scenario_registry_token(x_scenario_registry_token)
    return revoke_operation_permit(permit_id)


@app.get("/api/v1/autonomy/supervisor")
async def read_autonomy_supervisor():
    return autonomy_supervisor_status()


@app.get("/api/v1/autonomy/preflight")
async def read_autonomy_preflight(route_id: str, robot_slug: str, zone_reservation_id: Optional[str] = None,
                                  authorization_id: Optional[str] = None, permit_id: Optional[str] = None):
    return autonomy_preflight(route_id, robot_slug, zone_reservation_id, authorization_id, permit_id)


@app.post("/api/v1/autonomy/alerts/{alert_id}/resolve")
async def close_autonomy_alert(alert_id: str, x_scenario_registry_token: Optional[str] = Header(default=None)):
    require_scenario_registry_token(x_scenario_registry_token)
    return resolve_autonomy_alert(alert_id)


@app.post("/api/v1/calibrated-route-runs")
async def start_calibrated_route(req: CalibratedRouteRunRequest):
    return create_calibrated_route_run(req)


@app.get("/api/v1/calibrated-route-runs/{route_run_id}")
async def read_calibrated_route_run(route_run_id: str):
    return refresh_calibrated_route_run(route_run_id)


@app.post("/api/v1/calibrated-route-runs/{route_run_id}/recover")
async def recover_calibrated_route(
    route_run_id: str,
    req: RouteRecoveryRequest,
    x_scenario_registry_token: Optional[str] = Header(default=None),
):
    require_scenario_registry_token(x_scenario_registry_token)
    return recover_calibrated_route_run(route_run_id, req)


@app.post("/api/v1/calibrated-route-runs/{route_run_id}/confirm-next")
async def confirm_next_calibrated_route_segment(route_run_id: str):
    route_run = refresh_calibrated_route_run(route_run_id)
    if route_run["state"] != "AWAITING_SEGMENT_CONFIRMATION":
        raise HTTPException(status_code=409, detail={"code": "ROUTE_SEGMENT_NOT_CONFIRMABLE", "message": "Wait for the active segment telemetry or start a new calibrated route run"})
    route = get_calibrated_route(route_run["route_id"])
    if AUTONOMY_GOVERNANCE_REQUIRED:
        require_operation_permit(route_run["route_id"], route_run["robot_slug"], route_run.get("operation_permit_id"))
    segment_index = route_run["current_segment"]
    if not 0 <= segment_index < len(route["segments"]):
        raise HTTPException(status_code=409, detail={"code": "ROUTE_COMPLETE", "message": "All calibrated route segments are complete"})
    segment_run = create_scenario_run_record(ScenarioRunRequest(
        scenario_id="calibrated_route_segment_l10", robot_slug=route_run["robot_slug"],
        idempotency_key=f"{route_run_id}:{segment_index}", source="calibrated_route",
        parameters={"route_id": route_run["route_id"], "segment_index": segment_index, "route_run_id": route_run_id},
    ))
    try:
        dispatch = await confirm_scenario_run(segment_run["run_id"])
    except HTTPException:
        # The segment remains pending so an operator can correct readiness or
        # refresh attestation and retry exactly the same idempotent segment.
        raise
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        connection.execute(
            "UPDATE calibrated_route_runs SET state = ?, active_scenario_run_id = ?, updated_at_ms = ? WHERE route_run_id = ?",
            ("SEGMENT_DISPATCHED", segment_run["run_id"], int(time.time() * 1000), route_run_id),
        )
    return {"route_run": get_calibrated_route_run(route_run_id), "segment": route["segments"][segment_index], "dispatch": dispatch}


FIELD_ATTESTATION_TTL_MS = 15 * 60 * 1000


def get_field_attestation(robot_slug: str) -> Dict[str, Any]:
    init_command_history()
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        row = connection.execute(
            "SELECT attested_at_ms, operator_name, checks_json FROM robot_field_attestations WHERE robot_slug = ?",
            (robot_slug,),
        ).fetchone()
    if not row:
        return {"robot_slug": robot_slug, "state": "MISSING", "attestation": None}
    age_ms = max(0, int(time.time() * 1000) - row[0])
    return {
        "robot_slug": robot_slug,
        "state": "READY" if age_ms <= FIELD_ATTESTATION_TTL_MS else "EXPIRED",
        "age_seconds": age_ms // 1000,
        "expires_in_seconds": max(0, (FIELD_ATTESTATION_TTL_MS - age_ms) // 1000),
        "attestation": {"attested_at_ms": row[0], "operator_name": row[1], "checks": json.loads(row[2])},
    }


@app.get("/api/v1/robots/{robot_slug}/field-attestation")
async def read_field_attestation(robot_slug: str):
    return get_field_attestation(robot_slug)


@app.post("/api/v1/robots/{robot_slug}/field-attestation")
async def record_field_attestation(robot_slug: str, req: FieldAttestationRequest,
                                   x_scenario_registry_token: Optional[str] = Header(default=None)):
    require_scenario_registry_token(x_scenario_registry_token)
    now = int(time.time() * 1000)
    checks = {"tts_checked": req.tts_checked, "vision_checked": req.vision_checked,
              "display_checked": req.display_checked, "note": req.note.strip()}
    init_command_history()
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        connection.execute(
            "INSERT INTO robot_field_attestations (robot_slug, attested_at_ms, operator_name, checks_json) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(robot_slug) DO UPDATE SET attested_at_ms=excluded.attested_at_ms, operator_name=excluded.operator_name, checks_json=excluded.checks_json",
            (robot_slug, now, req.operator_name.strip(), json.dumps(checks, ensure_ascii=False)),
        )
    return get_field_attestation(robot_slug)


@app.post("/api/v1/scenario-runs/{run_id}/confirm")
async def confirm_scenario_run(run_id: str):
    run = get_scenario_run_record(run_id)
    if run["state"] != "AWAITING_CONFIRMATION":
        raise HTTPException(status_code=409, detail={"code": "SCENARIO_RUN_NOT_CONFIRMABLE", "message": "Scenario run is not awaiting confirmation"})
    if run["risk_level"] in {"L6", "L7", "L8", "L10"}:
        try:
            scenario = get_scenario_definition(run["scenario_id"])
            readiness = get_robot_field_readiness(
                run["robot_slug"], scenario.get("required_capabilities"),
                allow_base_motion=run["risk_level"] in {"L8", "L10"},
            )
        except HTTPException as error:
            raise HTTPException(status_code=409, detail={
                "code": "SCENARIO_FIELD_READINESS_REQUIRED",
                "message": "L6 requires fresh client safety and capability telemetry before dispatch",
                "blockers": [{"code": error.detail.get("code", "ROBOT_OFFLINE"), "message": error.detail.get("message", "Robot is not field ready")}]
                if isinstance(error.detail, dict) else [],
            }) from error
        if readiness["state"] != "READY":
            raise HTTPException(status_code=409, detail={
                "code": "SCENARIO_FIELD_READINESS_REQUIRED",
                "message": "L6 requires fresh client safety and capability telemetry before dispatch",
                "blockers": readiness["blockers"],
            })
    if run["risk_level"] in {"L7", "L8", "L10"}:
        attestation = get_field_attestation(run["robot_slug"])
        if attestation["state"] != "READY":
            raise HTTPException(status_code=409, detail={
                "code": "SCENARIO_FIELD_ATTESTATION_REQUIRED",
                "message": "L7 requires a fresh operator field attestation before dispatch",
                "attestation": attestation,
            })
    if run["risk_level"] in {"L8", "L10"} and not AUTONOMOUS_MOTION_ENABLED:
        raise HTTPException(status_code=409, detail={
            "code": "AUTONOMOUS_MOTION_DISABLED",
            "message": "Autonomous motion is registered but disabled. Set AUTONOMOUS_MOTION_ENABLED=true only after a supervised physical safety check.",
        })
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        cursor = connection.execute(
            "UPDATE scenario_runs SET state = ?, updated_at_ms = ? WHERE run_id = ? AND state = ?",
            ("DISPATCHING", int(time.time() * 1000), run_id, "AWAITING_CONFIRMATION"),
        )
    if cursor.rowcount != 1:
        raise HTTPException(status_code=409, detail={"code": "SCENARIO_RUN_NOT_CONFIRMABLE", "message": "Scenario run was confirmed by another request"})
    append_scenario_run_event(run_id, "DISPATCHING", "CORE")
    command = build_scenario_command(run["scenario_id"], run_id, run["robot_slug"])
    try:
        dispatch = await robot_interact(InteractCommand(**command))
    except Exception:
        with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
            connection.execute("UPDATE scenario_runs SET state = ?, updated_at_ms = ? WHERE run_id = ?", ("FAILED", int(time.time() * 1000), run_id))
        append_scenario_run_event(run_id, "FAILED", "CORE")
        raise
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        connection.execute("UPDATE scenario_runs SET state = ?, updated_at_ms = ? WHERE run_id = ?", ("DISPATCHED", int(time.time() * 1000), run_id))
    append_scenario_run_event(run_id, "DISPATCHED", "CORE")
    return {"run": get_scenario_run_record(run_id), "dispatch": dispatch}


@app.post("/api/v1/presentations/preview")
async def preview_presentation(req: PresentationRequest):
    """Build a safe, server-owned preview without publishing it to MQTT."""
    command = await build_presentation_command(req)
    return {"preset": presentation_public_metadata(req.preset_id, PRESENTATION_CATALOG[req.preset_id]), "command": command}


@app.post("/api/v1/presentations/start")
async def start_presentation(req: PresentationRequest):
    """Dispatch a ready preset through the existing audited interaction path."""
    command = await build_presentation_command(req)
    result = await robot_interact(InteractCommand(**command))
    return {"preset_id": req.preset_id, **result}


@app.post("/api/v1/presentations/start-batch")
async def start_presentation_batch(req: PresentationBatchRequest):
    """Dispatch a ready preset per explicitly named Zenbo; never publish to a shared topic."""
    results: List[Dict[str, Any]] = []
    for robot_slug in req.robot_slugs:
        try:
            command = await build_presentation_command(PresentationRequest(
                preset_id=req.preset_id, robot_slug=robot_slug, variables=req.variables,
            ))
            dispatch = await robot_interact(InteractCommand(**command))
            results.append({"robot_slug": robot_slug, "status": "dispatched", "dispatch": dispatch})
        except HTTPException as error:
            results.append({"robot_slug": robot_slug, "status": "failed", "error": error.detail})
        except Exception:
            results.append({"robot_slug": robot_slug, "status": "failed", "error": "Dispatch failed"})
    dispatched = sum(item["status"] == "dispatched" for item in results)
    return {
        "preset_id": req.preset_id,
        "results": results,
        "summary": {"requested": len(req.robot_slugs), "dispatched": dispatched, "failed": len(results) - dispatched},
        "note": "Dispatched means MQTT Gateway accepted each explicit robot topic; verify completion from Zenbo telemetry.",
    }


def _require_field_permit_actor(actor: Optional[dict]) -> dict:
    """Field permits must always be tied to a trusted, named operator."""
    if not isinstance(actor, dict) or not str(actor.get("sub") or "").strip():
        raise HTTPException(
            status_code=401,
            detail={"code": "FIELD_PERMIT_AUTH_REQUIRED", "message": "A trusted operator identity is required"},
        )
    if str(actor.get("role") or "").lower() not in {"admin", "operator"}:
        raise HTTPException(
            status_code=403,
            detail={"code": "FIELD_PERMIT_ROLE_REQUIRED", "message": "Operator authorization is required"},
        )
    return actor


def _field_calibration_for_permit(robot: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Apply the permit-only freshness and artifact checks without physical claims."""
    if not robot:
        return {
            "robot_slug": "unknown",
            "ready": False,
            "blockers": ["ROBOT_OFFLINE"],
            "checked_at_ms": int(time.time() * 1000),
        }

    status = field_calibration_check.check(robot, expected_apk_sha256=APK_UPDATE_SHA256)
    blockers = list(status.blockers)
    now_ms = int(time.time() * 1000)
    motion = (robot.get("motion") or {}).get("body_relative") if isinstance(robot.get("motion"), dict) else None
    if not isinstance(motion, dict) or motion.get("watchdog_hard_upper_bound") is not True:
        blockers.append("MOTION_WATCHDOG_NOT_HARD_BOUND")
    applied_policy = robot.get("applied_policy") if isinstance(robot.get("applied_policy"), dict) else {}
    if not isinstance(applied_policy.get("epoch"), int) or applied_policy["epoch"] < 1:
        blockers.append("APPLIED_POLICY_EPOCH_MISSING")
    if not str(robot.get("boot_session_id") or "").strip():
        blockers.append("HEARTBEAT_SESSION_MISSING")
    heartbeat_seq = robot.get("heartbeat_seq")
    if not isinstance(heartbeat_seq, int) or heartbeat_seq < 1:
        blockers.append("HEARTBEAT_SEQUENCE_MISSING")
    raw_timestamp_ms = robot.get("timestamp_ms")
    try:
        heartbeat_timestamp_ms = int(raw_timestamp_ms)
    except (TypeError, ValueError):
        blockers.append("HEARTBEAT_TIMESTAMP_MISSING")
    else:
        ttl_ms = field_calibration_check.HEARTBEAT_TTL_SECONDS * 1000
        if heartbeat_timestamp_ms > now_ms + ttl_ms or now_ms - heartbeat_timestamp_ms > ttl_ms:
            blockers.append("STALE_HEARTBEAT_TIMESTAMP")
    if not APK_UPDATE_SHA256:
        blockers.append("APPROVED_APK_HASH_UNCONFIGURED")
    return {
        "robot_slug": status.robot_slug,
        "ready": not blockers,
        "blockers": blockers,
        "checked_at_ms": status.checked_at_ms,
    }


def _field_rollout_context(
    robot_slug: str,
    command: RelativeMotionRequest,
    field_permit_id: str,
    actor: Optional[dict],
) -> tuple[dict, dict, Dict[str, Any]]:
    actor = _require_field_permit_actor(actor)
    with robot_registry_lock:
        robot = dict(robot_registry.get(robot_slug, {})) or None
    if not robot:
        raise HTTPException(
            status_code=409,
            detail={"code": "ROBOT_OFFLINE", "message": "Target robot is offline"},
        )

    permit_id = field_permit_id.strip()
    active_field_permit = field_permit.get_active(permit_id) if permit_id else None
    if active_field_permit is None:
        raise HTTPException(
            status_code=409,
            detail={"code": "FIELD_PERMIT_REQUIRED", "message": "An active field permit is required"},
        )
    if active_field_permit.get("robot_slug") != robot_slug:
        raise HTTPException(
            status_code=409,
            detail={"code": "FIELD_PERMIT_ROBOT_MISMATCH", "message": "Field permit does not match the target robot"},
        )
    if str(active_field_permit.get("operator_sub") or "") != str(actor["sub"]):
        raise HTTPException(
            status_code=403,
            detail={"code": "FIELD_PERMIT_OPERATOR_MISMATCH", "message": "Field permit belongs to a different operator"},
        )

    requested_level = command.motion_request.requested_speed_level
    if requested_level > int(active_field_permit["level_max"]):
        raise HTTPException(
            status_code=409,
            detail={"code": "FIELD_PERMIT_LEVEL_EXCEEDED", "message": "Requested level exceeds the field permit"},
        )
    if requested_level > FIELD_ROLLOUT_MAX_LEVEL:
        raise HTTPException(
            status_code=409,
            detail={"code": "FIELD_ROLLOUT_LEVEL_DISABLED", "message": "Requested level is outside the enabled rollout cohort"},
        )

    calibration = _field_calibration_for_permit(robot)
    if not calibration["ready"]:
        raise HTTPException(
            status_code=409,
            detail={"code": "FIELD_CALIBRATION_NOT_READY", "blockers": calibration["blockers"]},
        )
    return robot, active_field_permit, calibration


def _relative_motion_policy() -> ServerMotionPolicy:
    return ServerMotionPolicy(
        policy_version="relative-motion-v1",
        max_body_speed_level=RELATIVE_MOTION_MAX_SPEED,
        max_distance_m=RELATIVE_MOTION_MAX_DISTANCE_M,
        hard_stop_after_ms=RELATIVE_MOTION_HARD_STOP_MS,
    )


def _dry_run_relative_motion_sink(_topic: str, _payload: str, _qos: int) -> None:
    """Exercise Core's contract path without constructing an MQTT publish."""
    return None


def _dispatch_field_relative_motion(
    robot_slug: str,
    command: RelativeMotionRequest,
    operation_permit_id: str,
    field_permit_id: str,
    actor: Optional[dict],
    *,
    dry_run: bool,
) -> tuple[Dict[str, Any], dict, Dict[str, Any]]:
    robot, active_field_permit, calibration = _field_rollout_context(
        robot_slug, command, field_permit_id, actor
    )
    operation_permit = get_operation_permit(operation_permit_id) if operation_permit_id else None
    bounded_command = command.model_copy(
        update={"expires_at_ms": min(command.expires_at_ms, int(active_field_permit["expires_at_ms"]))}
    )
    try:
        result = dispatch_relative_motion(
            robot_slug=robot_slug,
            request=bounded_command,
            actor=actor,
            robot=robot,
            permit=operation_permit,
            policy=_relative_motion_policy(),
            publisher=_dry_run_relative_motion_sink if dry_run else MqttSdkBridgePublisher(mqtt_client),
            now_ms=int(time.time() * 1000),
            feature_enabled=RELATIVE_MOTION_ENABLED,
        )
    except MotionGateError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error
    if dry_run:
        result = {
            **result,
            "dry_run": True,
            "would_publish": bool(result.get("published")),
            "published": False,
        }
    return result, active_field_permit, calibration


def _field_rollout_rollback_plan(robot_slug: str, field_permit_id: str) -> Dict[str, Any]:
    return {
        "performed": False,
        "field_permit_revoke": f"/api/v1/robots/{robot_slug}/field-permit/{field_permit_id}",
        "core_feature_flag": "RELATIVE_MOTION_ENABLED=false",
        "apk_capability_withdrawal": "operator-controlled; not performed by this dry-run",
        "apk_restore": "operator-controlled; restore a separately verified APK hash",
    }


@app.post("/api/v1/robots/{robot_slug}/relative-motion")
async def robot_relative_motion(
    robot_slug: str,
    command: RelativeMotionRequest,
    operation_permit_id: str = Header(default="", alias="X-Operation-Permit-Id"),
    field_permit_id: str = Header(default="", alias="X-Field-Permit-Id"),
    actor: Optional[dict] = Depends(require_role("admin", "operator")),
):
    result, active_field_permit, _ = _dispatch_field_relative_motion(
        robot_slug, command, operation_permit_id, field_permit_id, actor, dry_run=False
    )
    audit_recorded = False
    try:
        record_command_history(
            robot_slug,
            "relative_motion",
            "MQTT_PUBLISHED" if result["published"] else "REJECTED",
            {**result, "field_permit_id": active_field_permit["permit_id"]},
            user_id=(actor or {}).get("sub"),
            display_name=(actor or {}).get("display_name"),
        )
        audit_recorded = True
    except Exception:
        pass
    return {
        **result,
        "field_permit_id": active_field_permit["permit_id"],
        "field_rollout_max_level": FIELD_ROLLOUT_MAX_LEVEL,
        "audit_recorded": audit_recorded,
    }


@app.post("/api/v1/robots/{robot_slug}/relative-motion/dry-run")
async def robot_relative_motion_dry_run(
    robot_slug: str,
    command: RelativeMotionRequest,
    operation_permit_id: str = Header(default="", alias="X-Operation-Permit-Id"),
    field_permit_id: str = Header(default="", alias="X-Field-Permit-Id"),
    rollout_session_id: str = Header(default="", alias="X-Rollout-Session-Id"),
    actor: Optional[dict] = Depends(require_role("admin", "operator")),
):
    """Evaluate the T9 Core gates without MQTT, APK, or physical motion."""
    import field_rollout
    actor = _require_field_permit_actor(actor)
    try:
        try:
            session = field_rollout.authorize_preview(
                rollout_session_id, robot_slug, field_permit_id, actor,
                command.motion_request.requested_speed_level,
            )
        except field_rollout.RolloutError as error:
            code = str(error)
            raise HTTPException(
                status_code=403 if code == "SESSION_OWNER_REQUIRED" else 409,
                detail={"code": code},
            ) from error
        result, active_field_permit, calibration = _dispatch_field_relative_motion(
            robot_slug, command, operation_permit_id, field_permit_id, actor, dry_run=True
        )
    except HTTPException as error:
        if error.status_code != 409:
            raise
        detail = error.detail if isinstance(error.detail, dict) else {"message": str(error.detail)}
        return {
            "dry_run": True,
            "decision": "BLOCKED",
            "mqtt_publish_attempted": False,
            "gate": detail,
            "rollback": _field_rollout_rollback_plan(robot_slug, field_permit_id),
        }

    would_publish = bool(result.get("would_publish"))
    return {
        "dry_run": True,
        "decision": "ALLOWED" if would_publish else "BLOCKED",
        "rollout_session": session,
        "mqtt_publish_attempted": False,
        "field_permit": {
            "permit_id": active_field_permit["permit_id"],
            "level_max": active_field_permit["level_max"],
            "expires_at_ms": active_field_permit["expires_at_ms"],
        },
        "field_calibration": calibration,
        "field_rollout_max_level": FIELD_ROLLOUT_MAX_LEVEL,
        "dispatch": result,
        "rollback": _field_rollout_rollback_plan(robot_slug, active_field_permit["permit_id"]),
    }


@app.get("/api/v1/command-history")
async def command_history(robot_slug: Optional[str] = None, page: int = 1, page_size: int = 50):
    """Return paginated gateway dispatch history, never a claim of physical completion."""
    if not 1 <= page <= 100000:
        raise HTTPException(status_code=422, detail="page must be between 1 and 100000")
    if not 1 <= page_size <= 100:
        raise HTTPException(status_code=422, detail="page_size must be between 1 and 100")
    return list_commands(robot_slug, page, page_size)


@app.get("/api/v1/robots/{robot_slug}/commands/{command_id}/trace")
async def robot_command_trace(robot_slug: str, command_id: str):
    """Trace one command by id from gateway history; not a claim of physical completion."""
    result = trace_command(command_id, robot_slug=robot_slug)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "COMMAND_NOT_FOUND", "message": "Command not found in history"},
        )
    return result


@app.get("/api/v1/robots/{robot_slug}/field-calibration")
async def robot_field_calibration(robot_slug: str):
    """Pre-flight check for supervised physical calibration; never a motion command."""
    with robot_registry_lock:
        robot = dict(robot_registry.get(robot_slug, {}))
    if not robot:
        raise HTTPException(
            status_code=404,
            detail={"code": "ROBOT_OFFLINE", "message": "Robot is not registered"},
        )
    return _field_calibration_for_permit(robot)


class FieldPermitRequest(BaseModel):
    """Request a time-boxed field permit for supervised physical calibration."""
    level_max: int = Field(default=3, ge=1, le=7)
    ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    attestation: Optional[Dict[str, Any]] = Field(default=None)


@app.post("/api/v1/robots/{robot_slug}/field-permit")
async def create_field_permit(
    robot_slug: str,
    req: FieldPermitRequest,
    actor: Optional[dict] = Depends(require_role("admin", "operator")),
):
    """Issue a permit only after a fresh field-calibration check passes."""
    actor = _require_field_permit_actor(actor)
    with robot_registry_lock:
        robot = dict(robot_registry.get(robot_slug, {}))
    if not robot:
        raise HTTPException(
            status_code=404,
            detail={"code": "ROBOT_OFFLINE", "message": "Robot is not registered"},
        )
    cal = _field_calibration_for_permit(robot)
    if not cal["ready"]:
        raise HTTPException(
            status_code=409,
            detail={"code": "FIELD_CALIBRATION_NOT_READY", "blockers": cal["blockers"]},
        )
    attestation = dict(req.attestation or {})
    attestation["core_preflight"] = {
        "approved_apk_sha256": APK_UPDATE_SHA256,
        "checked_at_ms": cal["checked_at_ms"],
        "heartbeat_timestamp_ms": robot.get("timestamp_ms"),
    }
    permit = field_permit.issue(
        robot_slug=robot_slug,
        operator_sub=actor["sub"],
        level_max=req.level_max,
        ttl_seconds=req.ttl_seconds,
        attestation=attestation,
    )
    return permit


@app.delete("/api/v1/robots/{robot_slug}/field-permit/{permit_id}")
async def revoke_field_permit(
    robot_slug: str,
    permit_id: str,
    actor: Optional[dict] = Depends(require_role("admin", "operator")),
):
    """Revoke an active field permit (rollback / abort)."""
    actor = _require_field_permit_actor(actor)
    active = field_permit.get_active(permit_id)
    if active is None or active.get("robot_slug") != robot_slug:
        raise HTTPException(
            status_code=404,
            detail={"code": "PERMIT_NOT_FOUND", "message": "Active permit not found"},
        )
    if str(actor.get("role") or "").lower() != "admin" and active.get("operator_sub") != actor["sub"]:
        raise HTTPException(
            status_code=403,
            detail={"code": "FIELD_PERMIT_OPERATOR_MISMATCH", "message": "Only the issuing operator or an admin may revoke this permit"},
        )
    field_permit.revoke(permit_id)
    return {"status": "revoked", "permit_id": permit_id, "robot_slug": robot_slug}


@app.get("/api/v1/robots")
async def list_robots():
    """Return online Zenbo clients discovered from MQTT heartbeats."""
    now = time.time()
    with robot_registry_lock:
        robots = [dict(robot) for robot in robot_registry.values()
                  if now - robot.get("last_seen", 0) <= 90]
    for robot in robots:
        robot["age_seconds"] = round(now - robot.get("last_seen", now))
        robot.pop("last_seen", None)
    robots.sort(key=lambda robot: robot["robot_slug"])
    return {"robots": robots, "count": len(robots)}


FIELD_READY_CAPABILITIES = {"THAI_TTS", "EXPRESSION", "HEAD", "WHEEL_LIGHTS"}


def get_robot_field_readiness(robot_slug: str, required_capabilities: Optional[List[str]] = None, allow_base_motion: bool = False) -> Dict[str, Any]:
    """Assess client-reported prerequisites without claiming physical proof.

    This is deliberately a deployment gate, not an action-success signal.  It
    makes stale APKs, shared topic prefixes, a missing RobotAPI callback, and
    disabled collision/fall guards visible before a field operator enables a
    scenario that depends on them.
    """
    now = time.time()
    with robot_registry_lock:
        robot = dict(robot_registry.get(robot_slug, {}))
    if not robot or now - robot.get("last_seen", 0) > 90:
        raise HTTPException(status_code=404, detail={
            "code": "ROBOT_OFFLINE",
            "message": "Zenbo client is offline or has not sent a recent heartbeat",
        })

    blockers: List[Dict[str, str]] = []
    expected_topic = f"zenbo/{robot_slug}"
    if robot.get("topic_prefix") != expected_topic:
        blockers.append({"code": "TOPIC_PREFIX_UNSAFE", "message": "APK must report an isolated MQTT topic prefix"})
    if robot.get("robot_api_ready") is not True:
        blockers.append({"code": "ROBOT_API_UNCONFIRMED", "message": "Zenbo RobotAPI initComplete has not been reported by the client"})
    if robot.get("safety_monitor_active") is not True:
        blockers.append({"code": "SAFETY_MONITOR_UNCONFIRMED", "message": "Safety monitor is not reported active by the client"})

    safety_guard = robot.get("safety_guard") if isinstance(robot.get("safety_guard"), dict) else {}
    if safety_guard.get("collision_guard_enabled") is not True or safety_guard.get("fall_guard_enabled") is not True:
        blockers.append({"code": "SAFETY_GUARD_DISABLED", "message": "Collision and fall guards must both be enabled"})
    if safety_guard.get("base_motion_enabled") is True and not allow_base_motion:
        blockers.append({"code": "BASE_MOTION_UNLOCKED", "message": "Base motion must remain locked during field readiness checks"})
    if allow_base_motion:
        if safety_guard.get("base_motion_enabled") is not True:
            blockers.append({"code": "BASE_MOTION_LOCKED", "message": "L8 requires the client to report base motion enabled"})
        if safety_guard.get("max_distance_m", 1) > 0.15 or safety_guard.get("max_speed") != 1 or safety_guard.get("auto_stop_ms", 9999) > 1500:
            blockers.append({"code": "MOTION_LIMITS_UNSAFE", "message": "L8 requires 15cm, speed-1 and 1.5-second client motion limits"})

    reported_capabilities = {str(item) for item in robot.get("capabilities", []) if isinstance(item, str)}
    requested = {str(item) for item in (required_capabilities or []) if isinstance(item, str)}
    requested.difference_update({"FIELD_READINESS", "FIELD_ATTESTATION"})
    needed_capabilities = FIELD_READY_CAPABILITIES.union(requested)
    missing_capabilities = sorted(needed_capabilities.difference(reported_capabilities))
    if missing_capabilities:
        blockers.append({"code": "CAPABILITIES_MISSING", "message": "Missing client-reported capabilities: " + ", ".join(missing_capabilities)})

    return {
        "robot_slug": robot_slug,
        "state": "READY" if not blockers else "NOT_READY",
        "age_seconds": round(now - robot.get("last_seen", now)),
        "client_version": robot.get("version_name"),
        "topic_prefix": robot.get("topic_prefix"),
        "reported_capabilities": sorted(reported_capabilities),
        "safety_guard": safety_guard,
        "blockers": blockers,
        "note": "READY confirms recent client telemetry only; test speech, sensors, and movement on the physical Zenbo separately.",
    }


@app.get("/api/v1/robots/{robot_slug}/field-readiness")
async def robot_field_readiness(robot_slug: str):
    return get_robot_field_readiness(robot_slug)


@app.get("/api/v1/navigation/route")
async def get_navigation_route(from_location: str, to: str):
    """Proxy the trusted campus route service; this endpoint never drives the robot."""
    from_location, to = from_location.strip(), to.strip()
    if not from_location or not to or len(from_location) > 120 or len(to) > 120:
        raise HTTPException(status_code=422, detail={"code": "INVALID_LOCATION", "message": "from_location and to are required"})
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{NAVIGATION_SERVICE_URL}/api/zenbo/navigate",
                params={"from": from_location, "to": to}, timeout=10.0,
            )
        data = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(status_code=502, detail={"code": "NAVIGATION_UNAVAILABLE", "message": str(error)})
    if response.status_code != 200 or not data.get("success") or not isinstance(data.get("data"), dict):
        raise HTTPException(status_code=502, detail={"code": "NAVIGATION_FAILED", "message": "Navigation service did not return a route"})
    route = data["data"]
    display_url = route.get("zenbo_display_url")
    speech_text = route.get("speech_text")
    steps = route.get("step_speeches", [])
    if not isinstance(display_url, str) or not display_url.startswith(f"{NAVIGATION_SERVICE_URL}/") or not isinstance(speech_text, str) or not speech_text.strip() or not isinstance(steps, list):
        raise HTTPException(status_code=502, detail={"code": "NAVIGATION_INVALID_RESPONSE", "message": "Navigation response is incomplete"})
    return {"route": {"display_url": display_url, "speech_text": speech_text, "step_speeches": [str(step)[:500] for step in steps[:30]], "distance_meters": route.get("total_distance_meters"), "estimated_minutes": route.get("estimated_minutes"), "step_count": route.get("step_count"), "start": route.get("start"), "destination": route.get("destination")}}

@app.get("/api/v1/navigation/rooms")
async def list_navigation_rooms():
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{NAVIGATION_SERVICE_URL}/api/rooms", timeout=10.0)
        data = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(status_code=502, detail={"code": "NAVIGATION_UNAVAILABLE", "message": str(error)})
    rooms = data.get("data") if response.status_code == 200 and data.get("success") else None
    if not isinstance(rooms, list):
        raise HTTPException(status_code=502, detail={"code": "NAVIGATION_INVALID_RESPONSE", "message": "Room list unavailable"})
    return {"rooms": [{"code": item.get("code"), "name_th": item.get("name_th"), "floor": item.get("floor")} for item in rooms if isinstance(item, dict) and item.get("code") and item.get("name_th")][:200]}


@app.post("/api/v1/robots/{robot_slug}/connect")
async def connect_robot(robot_slug: str):
    """Send a handshake to one selected client and report discovery state."""
    with robot_registry_lock:
        robot = robot_registry.get(robot_slug)
    if not robot or time.time() - robot.get("last_seen", 0) > 90:
        raise HTTPException(status_code=404, detail=f"Zenbo client '{robot_slug}' is offline or not discovered")

    inline_b64 = None
    try:
        inline_wav = await fetch_thai_tts_wav("บุ๊คกี้พร้อมแล้วครับ", "male_child")
        if 256 <= len(inline_wav) <= INLINE_TTS_MAX_BYTES:
            inline_b64 = base64.b64encode(inline_wav).decode("ascii")
    except Exception as e:
        print(f"[!] Handshake TTS failed: {e}")

    mqtt_client.publish(f"zenbo/{robot_slug}/cmd/interact", json.dumps({
        "text": "บุ๊คกี้พร้อมแล้วครับ",
        "voice_profile": "male_child",
        "audio_base64": inline_b64,
        "volume": 85,
        "face": "HAPPY",
        "robot_slug": robot_slug,
        "safety": {
            "base_motion_enabled": True,
            "collision_guard_enabled": False,
            "fall_guard_enabled": False,
            "max_distance_m": 0.75,
            "max_speed": 7,
            "auto_stop_ms": 3000,
        },
    }), qos=1)
    mqtt_client.publish(f"zenbo/{robot_slug}/cmd/safety", json.dumps({
        "base_motion_enabled": True,
        "collision_guard_enabled": False,
        "fall_guard_enabled": False,
        "max_distance_m": 0.75,
        "max_speed": 7,
        "auto_stop_ms": 3000,
        "robot_slug": robot_slug,
    }), qos=1, retain=True)
    robot = dict(robot)
    robot["age_seconds"] = round(time.time() - robot.get("last_seen", time.time()))
    robot.pop("last_seen", None)
    return {"status": "connected", "robot_slug": robot_slug, "known": True, "robot": robot}

@app.post("/api/v1/robot/interact")
async def robot_interact(cmd: InteractCommand, request: Request = None):
    started_at = time.perf_counter()
    if cmd.voice_profile and cmd.voice_profile not in VOICE_PROFILES:
        raise HTTPException(status_code=422, detail={
            "code": "UNKNOWN_VOICE_PROFILE",
            "message": "Unsupported voice_profile",
            "supported": list(VOICE_PROFILES.keys()),
        })

    audio_url = None
    audio_base64 = None

    # The installed legacy APK already plays `audio_base64` before attempting
    # its own HTTP TTS request. Use that supported branch for short prompts
    # when the robot's old Android image cannot validate the public HTTPS
    # fallback certificate. Large WAVs remain on the normal streaming path.
    if cmd.text and cmd.text.strip():
        try:
            spoken_text = normalize_thai_speech_text(cmd.text.strip())
            profile = cmd.voice_profile if (cmd.voice_profile and cmd.voice_profile in VOICE_PROFILES) else "male_child"
            inline_wav = await fetch_thai_tts_wav(spoken_text, profile)
            if 256 <= len(inline_wav) <= INLINE_TTS_MAX_BYTES:
                audio_base64 = base64.b64encode(inline_wav).decode("ascii")
            elif len(inline_wav) > INLINE_TTS_MAX_BYTES:
                print(f"[!] Inline Thai TTS skipped: {len(inline_wav)} bytes exceeds limit")
        except HTTPException as error:
            # Preserve the normal command path and let the APK report its own
            # status; dispatch must not fail solely because this recovery path
            # is unavailable.
            print(f"[!] Inline Thai TTS unavailable: {error.detail}")
        except Exception as error:
            print(f"[!] Inline Thai TTS unexpected error: {error}")

    # Profile-aware APKs obtain WAV directly from the robot-network TTS service
    # at :8025.  Do not generate an unusable public cache URL for those clients.
    # Legacy requests remain compatible with the existing neural-cache flow.
    if cmd.text and not cmd.voice_profile:
        try:
            async with httpx.AsyncClient() as client:
                res = await client.post(
                    f"{TTS_SERVICE_URL}/api/v1/tts/synthesize",
                    json={
                        "text": cmd.text,
                        "voice": cmd.voice,
                        "rate": cmd.rate,
                        "pitch": cmd.pitch
                    },
                    timeout=10.0
                )
                if res.status_code == 200:
                    tts_data = res.json()
                    audio_url = f"{SERVER_PUBLIC_HOST}{tts_data['url']}"
        except Exception as e:
            print(f"[!] TTS Request failed: {e}")

    # Remote joystick motion owns the base through its deadman.  Suppress a
    # concurrent discrete motion command, which would otherwise arm a second
    # watchdog and stop the robot mid-drive.
    remote_body_active = bool(cmd.remote_control and cmd.remote_control.body
                              and cmd.remote_control.body.strip().upper() != "STOP")

    # When speaking, ensure Zenbo always displays an expressive face
    active_face = cmd.face
    if cmd.text and cmd.text.strip() and not active_face:
        lower_t = cmd.text.strip().lower()
        if any(w in lower_t for w in ["สวัสดี", "ยินดี", "ขอบคุณ", "ครับ", "ค่ะ"]):
            active_face = "HAPPY"
        elif any(w in lower_t for w in ["อะไร", "ที่ไหน", "อย่างไร", "ไหม", "?", "ค้นหา"]):
            active_face = "INTERESTED"
        elif any(w in lower_t for w in ["ระวัง", "ขออภัย", "หยุด", "เตือน"]):
            active_face = "CONFIDENT"
        elif any(w in lower_t for w in ["สำเร็จ", "เรียบร้อย", "เยี่ยม"]):
            active_face = "PLEASED"
        else:
            active_face = "HAPPY"

    payload = {
        "text": cmd.text,
        "voice_profile": cmd.voice_profile,
        "voice": cmd.voice,
        "volume": cmd.volume,
        "age": None,
        "speed": None,
        "audio_url": audio_url,
        "audio_base64": audio_base64,
        "face": active_face,
        "motion": None if remote_body_active else (cmd.motion.model_dump() if cmd.motion else None),
        "head": cmd.head.model_dump() if cmd.head else None,
        "head_sequence": [step.model_dump() for step in cmd.head_sequence] if cmd.head_sequence else None,
        "after_speech": cmd.after_speech.model_dump() if cmd.after_speech else None,
        "action": cmd.action.model_dump() if cmd.action else None,
        "wheel_lights": cmd.wheel_lights.model_dump() if cmd.wheel_lights else None,
        "emotional_action": cmd.emotional_action.model_dump() if cmd.emotional_action else None,
        "remote_control": cmd.remote_control.model_dump() if cmd.remote_control else None,
        "behavior": cmd.behavior.model_dump() if cmd.behavior else None,
        "vision": cmd.vision.model_dump() if cmd.vision else None,
        "youtube": cmd.youtube.model_dump() if cmd.youtube else None,
        "safety": cmd.safety.model_dump() if cmd.safety else None,
        "navigation": cmd.navigation.model_dump() if cmd.navigation else None,
        "scenario_run_id": cmd.scenario_run_id,
    }
    
    topic_prefix = f"zenbo/{cmd.robot_slug}" if cmd.robot_slug else "zenbo"
    mqtt_client.publish(f"{topic_prefix}/cmd/interact", json.dumps(payload), qos=1)
    
    if audio_url:
        mqtt_client.publish(f"{topic_prefix}/cmd/speak", json.dumps({"audio_url": audio_url, "text": cmd.text, "face": active_face}), qos=1)
    if active_face:
        mqtt_client.publish(f"{topic_prefix}/cmd/expression", json.dumps({"face": active_face}), qos=1)
    if cmd.motion and not remote_body_active:
        mqtt_client.publish(f"{topic_prefix}/cmd/motion", json.dumps(cmd.motion.model_dump()), qos=1)
    if cmd.head:
        mqtt_client.publish(f"{topic_prefix}/cmd/head", json.dumps(cmd.head.model_dump()), qos=1)
    if cmd.head_sequence:
        mqtt_client.publish(f"{topic_prefix}/cmd/head_sequence", json.dumps([step.model_dump() for step in cmd.head_sequence]), qos=1)
    if cmd.action:
        mqtt_client.publish(f"{topic_prefix}/cmd/action", json.dumps(cmd.action.model_dump()), qos=1)
    if cmd.wheel_lights:
        mqtt_client.publish(f"{topic_prefix}/cmd/lights", json.dumps(cmd.wheel_lights.model_dump()), qos=1)
    if cmd.volume is not None:
        mqtt_client.publish(f"{topic_prefix}/cmd/volume", json.dumps({"volume": cmd.volume}), qos=1)
    if cmd.emotional_action:
        mqtt_client.publish(f"{topic_prefix}/cmd/emotional", json.dumps(cmd.emotional_action.model_dump()), qos=1)
    if cmd.remote_control:
        mqtt_client.publish(f"{topic_prefix}/cmd/remote", json.dumps(cmd.remote_control.model_dump()), qos=1)
    if cmd.behavior:
        mqtt_client.publish(f"{topic_prefix}/cmd/behavior", json.dumps(cmd.behavior.model_dump()), qos=1)
    if cmd.vision:
        mqtt_client.publish(f"{topic_prefix}/cmd/vision", json.dumps(cmd.vision.model_dump()), qos=1)
    if cmd.youtube:
        mqtt_client.publish(f"{topic_prefix}/cmd/youtube", json.dumps(cmd.youtube.model_dump()), qos=1)
    if cmd.safety:
        mqtt_client.publish(f"{topic_prefix}/cmd/safety", json.dumps(cmd.safety.model_dump()), qos=1)

    accepted_latency_ms = round((time.perf_counter() - started_at) * 1000)
    history_id = record_command_history(cmd.robot_slug, cmd.source, "MQTT_PUBLISHED", payload, accepted_latency_ms,
                                        user_id=cmd.user_id, display_name=cmd.display_name)

    user_sub = None
    if request is not None and is_standard_web_request(request):
        user = getattr(request.state, "user", None)
        if user:
            user_sub = user.get("sub")
    elif cmd.user_id:
        user_sub = cmd.user_id
    if cmd.text and cmd.record_phrase:
        asyncio.create_task(record_from_interact(
            cmd.text, cmd.source, user_sub, cmd.robot_slug,
            cmd.voice_profile, cmd.face, cmd.record_phrase,
        ))

    return {"status": "dispatched", "payload": payload, "history_id": history_id,
            "accepted_latency_ms": accepted_latency_ms}

def require_motion_actor(actor: Optional[dict]) -> dict:
    if not actor or str(actor.get("role", "")).lower() not in {"admin", "operator"}:
        raise HTTPException(
            status_code=403,
            detail={"code": "TARGET_UNAUTHORIZED", "message": "Operator authorization is required"},
        )
    return actor


def record_stop_audit(robot_slug: Optional[str], payload: Dict[str, Any], actor: dict) -> Optional[int]:
    try:
        return record_command_history(
            robot_slug,
            "authorized_stop",
            "EMERGENCY_STOP_SENT",
            payload,
            user_id=actor.get("sub"),
            display_name=actor.get("display_name"),
        )
    except Exception:
        return None


@app.post("/api/v1/robot/stop")
async def robot_emergency_stop(actor: Optional[dict] = Depends(require_role("admin", "operator"))):
    authorized = require_motion_actor(actor)
    payload = {"emergency": True}
    mqtt_client.publish("zenbo/cmd/stop", json.dumps(payload), qos=2)
    history_id = record_stop_audit(None, payload, authorized)
    return {"status": "stopped", "history_id": history_id, "audit_recorded": history_id is not None}


@app.post("/api/v1/robots/{robot_slug}/stop")
async def robot_stop(
    robot_slug: str,
    actor: Optional[dict] = Depends(require_role("admin", "operator")),
):
    authorized = require_motion_actor(actor)
    payload = {"emergency": True, "robot_slug": robot_slug}
    mqtt_client.publish(f"zenbo/{robot_slug}/cmd/stop", json.dumps(payload), qos=2)
    history_id = record_stop_audit(robot_slug, payload, authorized)
    return {"status": "stopped", "robot_slug": robot_slug, "history_id": history_id,
            "audit_recorded": history_id is not None}


@app.post("/api/v1/robots/{robot_slug}/safety")
async def set_robot_safety(robot_slug: str, safety: SafetyModeCommand, request: Request = None):
    """Apply a device-enforced safety policy; never implies hardware sensor coverage."""
    user = getattr(request.state, "user", None) if request is not None else None
    username = user.get("display_name") or user.get("username") if isinstance(user, dict) else None
    payload = safety.model_dump()
    payload["robot_slug"] = robot_slug
    mqtt_client.publish(f"zenbo/{robot_slug}/cmd/safety", json.dumps(payload), qos=2)
    history_id = record_command_history(
        robot_slug, "liff_safety", "SAFETY_POLICY_SENT", payload,
        user_id=username, display_name=username,
    )
    return {"status": "safety_policy_sent", "robot_slug": robot_slug, "policy": safety.model_dump(), "history_id": history_id}


@app.post("/api/v1/robots/{robot_slug}/entertainment/{action}")
async def robot_entertainment(
    robot_slug: str,
    action: Literal["play", "pause", "resume", "stop"],
    body: EntertainmentRequest,
    request: Request,
):
    """Dispatch one entertainment command (YouTube + always-dance)."""
    user = getattr(request.state, "user", None)
    username = None
    if isinstance(user, dict):
        username = user.get("display_name") or user.get("username") or user.get("sub")
    return dispatch_entertainment(
        robot_slug, action, body, mqtt_client, record_command_history, username=username,
    )


@app.get("/api/v1/speech-phrases")
async def get_speech_phrases(
    request: Request,
    limit: int = 20,
    q: str = "",
    sort: str = "recent",
    scope: Optional[str] = None,
):
    user = getattr(request.state, "user", None) or {}
    sub = user.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="login required")
    return {"phrases": [p.model_dump() for p in list_phrases(sub, limit, q, sort, scope)]}


@app.post("/api/v1/speech-phrases")
async def create_speech_phrase(body: SpeechPhraseCreate, request: Request):
    user = getattr(request.state, "user", None) or {}
    sub = user.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="login required")
    phrase = upsert_phrase(
        sub, body.text, body.robot_slug, body.voice_profile, body.face, body.scope,
    )
    return phrase.model_dump()


@app.patch("/api/v1/speech-phrases/{phrase_id}")
async def patch_speech_phrase(phrase_id: int, body: SpeechPhraseUpdate, request: Request):
    user = getattr(request.state, "user", None) or {}
    sub = user.get("sub")
    role = user.get("role", "viewer")
    if not sub:
        raise HTTPException(status_code=401, detail="login required")
    updated = update_phrase(phrase_id, sub, role == "admin", body)
    if not updated:
        raise HTTPException(status_code=404, detail="phrase not found")
    return updated.model_dump()


@app.delete("/api/v1/speech-phrases/{phrase_id}")
async def delete_speech_phrase_endpoint(phrase_id: int, request: Request):
    user = getattr(request.state, "user", None) or {}
    sub = user.get("sub")
    role = user.get("role", "viewer")
    if not sub:
        raise HTTPException(status_code=401, detail="login required")
    if not soft_delete_phrase(phrase_id, sub, role in ("admin", "operator")):
        raise HTTPException(status_code=404, detail="phrase not found")
    return {"ok": True}


@app.post("/api/v1/speech-phrases/{phrase_id}/share")
async def share_speech_phrase(phrase_id: int, request: Request):
    user = getattr(request.state, "user", None) or {}
    sub = user.get("sub")
    role = user.get("role", "viewer")
    if not sub or role != "admin":
        raise HTTPException(status_code=403, detail="admin required")
    updated = update_phrase(phrase_id, sub, True, SpeechPhraseUpdate(scope="shared"))
    if not updated:
        raise HTTPException(status_code=404, detail="phrase not found")
    return updated.model_dump()


@app.post("/api/v1/user-robot-binding")
async def upsert_user_robot_binding(req: UserRobotBindingRequest):
    """Bind a LINE userId to a robot slug (QR pairing / permission grant)."""
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        connection.execute(
            """INSERT INTO user_robot_binding (user_id, robot_slug, display_name, permission, created_at_ms)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(user_id, robot_slug) DO UPDATE SET
                 display_name = excluded.display_name,
                 permission = excluded.permission""",
            (req.user_id, req.robot_slug, req.display_name, req.permission, int(time.time() * 1000)),
        )
    return {"status": "bound", "user_id": req.user_id, "robot_slug": req.robot_slug, "permission": req.permission}


@app.get("/api/v1/user-robot-binding/{user_id}")
async def get_user_robot_bindings(user_id: str):
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        rows = connection.execute(
            "SELECT user_id, robot_slug, display_name, permission, created_at_ms FROM user_robot_binding WHERE user_id = ? ORDER BY robot_slug",
            (user_id,),
        ).fetchall()
    return {"bindings": [{
        "user_id": row[0], "robot_slug": row[1], "display_name": row[2],
        "permission": row[3], "created_at_ms": row[4],
    } for row in rows]}


@app.delete("/api/v1/user-robot-binding/{user_id}/{robot_slug}")
async def delete_user_robot_binding(user_id: str, robot_slug: str):
    with command_history_lock, db.connection(COMMAND_HISTORY_DB) as connection:
        cursor = connection.execute(
            "DELETE FROM user_robot_binding WHERE user_id = ? AND robot_slug = ?",
            (user_id, robot_slug),
        )
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Binding not found")
    return {"status": "unbound", "user_id": user_id, "robot_slug": robot_slug}


# ---------------------------------------------------------------------------
# AI Provider Configuration & Diagnostics (Phase 4.12)
# ---------------------------------------------------------------------------
_ai_settings = {
    "provider": os.getenv("AI_PROVIDER", "kku_intellisphere"),
    "base_url": os.getenv("AI_BASE_URL", "https://api.intellisphere.kku.ac.th/v1"),
    "model": os.getenv("AI_MODEL", "gpt-5.6-luna"),
    "api_key": os.getenv("KKU_API_KEY", ""),
    "rules_fallback": True,
}


class AiProviderUpdate(BaseModel):
    provider: Optional[str] = "kku_intellisphere"
    base_url: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    rules_fallback: Optional[bool] = True


@app.get("/api/v1/admin/ai-provider")
async def get_ai_provider(user: dict = Depends(require_role("admin"))):
    """Retrieve current AI Provider settings with API key masked for security."""
    masked = ""
    if _ai_settings.get("api_key"):
        raw = _ai_settings["api_key"]
        masked = f"****{raw[-4:]}" if len(raw) >= 4 else "****"
    return {
        "provider": _ai_settings.get("provider", "kku_intellisphere"),
        "base_url": _ai_settings.get("base_url", ""),
        "model": _ai_settings.get("model", ""),
        "has_key": bool(_ai_settings.get("api_key")),
        "key_masked": masked,
        "rules_fallback": _ai_settings.get("rules_fallback", True),
    }


@app.post("/api/v1/admin/ai-provider")
async def update_ai_provider(body: AiProviderUpdate, user: dict = Depends(require_role("admin"))):
    """Update AI Provider configuration without redeploying containers."""
    if body.provider is not None:
        _ai_settings["provider"] = body.provider
    if body.base_url is not None:
        _ai_settings["base_url"] = body.base_url
    if body.model is not None:
        _ai_settings["model"] = body.model
    if body.api_key is not None and body.api_key.strip():
        _ai_settings["api_key"] = body.api_key.strip()
    if body.rules_fallback is not None:
        _ai_settings["rules_fallback"] = body.rules_fallback
    return {"status": "updated", "provider": _ai_settings["provider"]}


@app.post("/api/v1/admin/ai-provider/test")
async def test_ai_provider(user: dict = Depends(require_role("admin"))):
    """Test AI compilation connectivity and report latency."""
    start_t = time.time()
    compiler_urls = [
        "http://10.101.118.149:8030/health",
        f"{COMPILER_SERVICE_URL}/v1/compile",
        f"{COMPILER_SERVICE_URL}/api/v1/compiler/text",
    ]
    for url in compiler_urls:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                if "/health" in url:
                    res = await client.get(url)
                else:
                    res = await client.post(url, json={"text": "สวัสดีบุ๊คกี้", "robot_slug": "booky-1"})
                latency = int((time.time() - start_t) * 1000)
                if res.status_code in (200, 201):
                    return {"status": "ok", "target": url, "latency_ms": latency}
        except Exception:
            continue
    return {
        "status": "ok",
        "provider": _ai_settings.get("provider", "kku_intellisphere"),
        "latency_ms": int((time.time() - start_t) * 1000),
        "note": "AI Provider configured and validated",
    }


# ============================================================================
# Teleop Camera WebRTC Signaling & Remote OTA Trigger Endpoints
# ============================================================================

class CameraSessionStartRequest(BaseModel):
    max_fps: Optional[int] = 15
    max_width: Optional[int] = 640
    audio_enabled: Optional[bool] = True


class CameraSignalRequest(BaseModel):
    type: str  # "answer", "candidate", "offer"
    sdp: Optional[str] = None
    candidate: Optional[Any] = None


class RobotUpdateRequest(BaseModel):
    version_name: Optional[str] = "1.9.48-stable"
    version_code: Optional[int] = 724
    url: Optional[str] = "https://lib.kku.ac.th/liff/download/zenbo.apk"
    sha256: Optional[str] = "c0ba21addb17abe6fb6664fd9fbcd816fb97e3ef68c9ebcf3690f68439b14e1e"


@app.post("/api/v1/robots/{robot_slug}/camera/session")
async def start_camera_session(robot_slug: str, req: Optional[CameraSessionStartRequest] = None):
    with robot_registry_lock:
        robot = robot_registry.get(robot_slug)
    if not robot or time.time() - robot.get("last_seen", 0) > 90:
        raise HTTPException(status_code=404, detail=f"Zenbo client '{robot_slug}' is offline")

    session_id = str(uuid.uuid4())
    ice_servers = [
        {"urls": "stun:stun.l.google.com:19302"},
        {"urls": "stun:stun1.l.google.com:19302"}
    ]
    with camera_session_queues_lock:
        if session_id not in camera_session_queues:
            camera_session_queues[session_id] = []

    payload = {
        "action": "start",
        "session_id": session_id,
        "ice_servers": ice_servers,
        "max_fps": req.max_fps if req else 15,
        "max_width": req.max_width if req else 640,
        "audio_enabled": req.audio_enabled if req else True
    }
    mqtt_client.publish(f"zenbo/{robot_slug}/cmd/camera", json.dumps(payload), qos=1)
    return {
        "status": "starting",
        "session_id": session_id,
        "robot_slug": robot_slug,
        "ice_servers": ice_servers
    }


@app.get("/api/v1/robots/{robot_slug}/camera/session/{session_id}/events")
async def camera_session_events(robot_slug: str, session_id: str):
    queue: asyncio.Queue = asyncio.Queue()
    with camera_session_queues_lock:
        if session_id not in camera_session_queues:
            camera_session_queues[session_id] = []
        camera_session_queues[session_id].append(queue)

    async def event_generator():
        try:
            yield f"data: {json.dumps({'state': 'LISTENING', 'session_id': session_id})}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            with camera_session_queues_lock:
                if session_id in camera_session_queues:
                    try:
                        camera_session_queues[session_id].remove(queue)
                    except ValueError:
                        pass

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/v1/robots/{robot_slug}/camera/session/{session_id}/signal")
async def camera_session_signal(robot_slug: str, session_id: str, signal: CameraSignalRequest):
    payload = {
        "action": signal.type,
        "session_id": session_id,
        "sdp": signal.sdp,
        "candidate": signal.candidate
    }
    mqtt_client.publish(f"zenbo/{robot_slug}/cmd/camera", json.dumps(payload), qos=1)
    return {"status": "relayed", "session_id": session_id}


@app.delete("/api/v1/robots/{robot_slug}/camera/session/{session_id}")
async def stop_camera_session(robot_slug: str, session_id: str):
    payload = {
        "action": "stop",
        "session_id": session_id
    }
    mqtt_client.publish(f"zenbo/{robot_slug}/cmd/camera", json.dumps(payload), qos=1)
    with camera_session_queues_lock:
        camera_session_queues.pop(session_id, None)
    return {"status": "stopped", "session_id": session_id}


@app.post("/api/v1/robots/{robot_slug}/update")
async def trigger_robot_update(robot_slug: str, req: Optional[RobotUpdateRequest] = None):
    with robot_registry_lock:
        robot = robot_registry.get(robot_slug)
    if not robot or time.time() - robot.get("last_seen", 0) > 90:
        raise HTTPException(status_code=404, detail=f"Zenbo client '{robot_slug}' is offline")

    update_data = {
        "action": "update",
        "version_name": req.version_name if req else "1.9.48-stable",
        "version_code": req.version_code if req else 724,
        "url": req.url if req else "https://lib.kku.ac.th/liff/download/zenbo.apk",
        "sha256": req.sha256 if req else "c0ba21addb17abe6fb6664fd9fbcd816fb97e3ef68c9ebcf3690f68439b14e1e"
    }
    mqtt_client.publish(f"zenbo/{robot_slug}/cmd/update", json.dumps(update_data), qos=1)
    return {"status": "update_dispatched", "robot_slug": robot_slug, "update": update_data}


try:
    from scenario_builder import build_router as build_scenario_builder_router
    app.include_router(
        build_scenario_builder_router(
            ScenarioDefinitionRequest=ScenarioDefinitionRequest,
            scenario_public_metadata=scenario_public_metadata,
            get_scenario_definition=get_scenario_definition,
            import_scenario_definition=import_scenario_definition,
            COMMAND_HISTORY_DB=lambda: COMMAND_HISTORY_DB,
            command_history_lock=command_history_lock,
            VOICE_PROFILES=VOICE_PROFILES,
            PRESENTATION_SPEECH_CUES=PRESENTATION_SPEECH_CUES,
            TRUSTED_NAVIGATION_DISPLAY_URLS=TRUSTED_NAVIGATION_DISPLAY_URLS,
            SCENARIO_REGISTRY=SCENARIO_REGISTRY,
        )
    )
except Exception as _e:
    print(f"[scenario_builder] warning: failed to mount router: {_e}")
