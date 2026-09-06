"""KKU libsso OIDC integration for the Zenbo Core API.

This module is intentionally import-safe: missing OIDC configuration degrades
gracefully with a warning.  It depends on the small DB adapter in ``db.py`` for
persistence helpers.

Integration snippets for ``main.py`` are included at the bottom of this file as
a comment block.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sys
import time
from typing import Any, Optional, Tuple
from urllib.parse import urlencode, urlparse

import httpx
try:
    import jwt
except ImportError:
    jwt = None

try:
    from cryptography.fernet import Fernet
except ImportError:
    Fernet = None

from fastapi import HTTPException, Request

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

ISSUER = os.getenv("OIDC_ISSUER", "https://libsso.kku.ac.th").rstrip("/")
DISCOVERY_URL = os.getenv("OIDC_DISCOVERY_URL", f"{ISSUER}/.well-known/openid-configuration")
CLIENT_ID = os.getenv("OIDC_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("OIDC_CLIENT_SECRET", "").strip()
REDIRECT_URI = os.getenv("OIDC_REDIRECT_URI", "").strip()
SCOPES = os.getenv("OIDC_SCOPES", "openid email profile").strip()
SIGNING_ALG = os.getenv("OIDC_SIGNING_ALG", "RS256").strip().upper() or "RS256"
TOKEN_AUTH_METHOD = os.getenv("OIDC_TOKEN_AUTH", "client_secret_post").strip()
AUTHORIZE_URL = os.getenv("OIDC_AUTHORIZE_URL", f"{ISSUER}/oauth2/authorize").rstrip("/")
TOKEN_URL = os.getenv("OIDC_TOKEN_URL", f"{ISSUER}/oauth2/token").rstrip("/")
USERINFO_URL = os.getenv("OIDC_USERINFO_URL", f"{ISSUER}/oauth2/userinfo").rstrip("/")
JWKS_URL = os.getenv("OIDC_JWKS_URL", f"{ISSUER}/oauth2/jwks").rstrip("/")

APP_SECRET_KEY = os.getenv("APP_SECRET_KEY", "").strip()
ALLOWED_DOMAINS = {
    d.strip().lower()
    for d in os.getenv("ZENBO_WEB_ALLOWED_EMAIL_DOMAINS", "").split(",")
    if d.strip()
}
ADMIN_EMAILS = {
    e.strip().lower()
    for e in os.getenv("ZENBO_WEB_ADMIN_EMAILS", "").split(",")
    if e.strip()
}
DEFAULT_ROLE = os.getenv("ZENBO_WEB_DEFAULT_ROLE", "viewer").strip().lower() or "viewer"
SESSION_TTL_SECONDS = max(
    300,
    min(
        int(os.getenv("WEB_AUTH_SESSION_TTL_SECONDS") or os.getenv("ZENBO_WEB_SESSION_TTL_SECONDS", "28800")),
        86400,
    ),
)
SESSION_COOKIE = os.getenv("WEB_AUTH_COOKIE", "zenbo_web_session")
WEB_AUTH_HOST = os.getenv("ZENBO_WEB_AUTH_HOST", "lib.kku.ac.th").strip().lower()
WEB_AUTH_ENABLED = os.getenv("ZENBO_WEB_AUTH_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}

REQUIRED_OIDC_VARS = [
    ISSUER,
    CLIENT_ID,
    CLIENT_SECRET,
    REDIRECT_URI,
    AUTHORIZE_URL,
    TOKEN_URL,
    USERINFO_URL,
]
OIDC_CONFIGURED = all(REQUIRED_OIDC_VARS)

if not OIDC_CONFIGURED:
    sys.stderr.write(
        "[oidc] WARNING: OIDC is not fully configured. "
        "Set OIDC_ISSUER, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET, OIDC_REDIRECT_URI, "
        "OIDC_AUTHORIZE_URL, OIDC_TOKEN_URL and OIDC_USERINFO_URL.\n"
    )

# -----------------------------------------------------------------------------
# Cryptography helpers
# -----------------------------------------------------------------------------

_TX_MAX_AGE = 600  # 10 minutes, state/nonce transaction cookie lifetime


def _derive_key_material(secret: str) -> bytes:
    """Return 32 bytes suitable for a Fernet key derived from a plain secret."""
    return hashlib.sha256(secret.encode("utf-8")).digest()


def _coerce_fernet_key(raw: str) -> bytes:
    """Accept either a raw 32-byte secret or a 32-byte base64url-encoded key."""
    data = raw.encode("utf-8")
    if len(data) == 32:
        return base64.urlsafe_b64encode(data)
    try:
        decoded = base64.urlsafe_b64decode(data + b"=" * (-len(data) % 4))
        if len(decoded) == 32:
            return base64.urlsafe_b64encode(decoded)
    except Exception:
        pass
    # Treat arbitrary string as a raw secret and hash it to 32 bytes.
    return base64.urlsafe_b64encode(_derive_key_material(raw))


def _load_fernet_key() -> bytes:
    if APP_SECRET_KEY:
        return _coerce_fernet_key(APP_SECRET_KEY)
    if CLIENT_SECRET:
        sys.stderr.write(
            "[oidc] WARNING: APP_SECRET_KEY is not set; deriving transient cookie key from OIDC_CLIENT_SECRET.\n"
        )
        return base64.urlsafe_b64encode(_derive_key_material(CLIENT_SECRET))
    sys.stderr.write(
        "[oidc] WARNING: Neither APP_SECRET_KEY nor OIDC_CLIENT_SECRET is set; "
        "using a random transient cookie key.  OIDC state cookies will not survive restarts.\n"
    )
    if Fernet is not None:
        return Fernet.generate_key()
    return b""


try:
    if Fernet is not None:
        _FERNET = Fernet(_load_fernet_key())
    else:
        _FERNET = None
except Exception as exc:  # pragma: no cover - defensive fallback
    sys.stderr.write(f"[oidc] WARNING: Failed to initialise Fernet key: {exc}.  State cookies disabled.\n")
    _FERNET = None


# -----------------------------------------------------------------------------
# Transaction cookie (state / nonce)
# -----------------------------------------------------------------------------

def build_tx_cookie(next_path: str) -> Tuple[str, str, str]:
    """Return (state, nonce, cookie_value) for the OIDC transaction."""
    if _FERNET is None:
        raise RuntimeError("OIDC transaction cookie is not configured")
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    payload = {
        "state": state,
        "nonce": nonce,
        "next": _sanitize_next(next_path),
        "iat": int(time.time()),
    }
    cookie_value = _FERNET.encrypt(json.dumps(payload).encode("utf-8")).decode("ascii")
    return state, nonce, cookie_value


def parse_tx_cookie(cookie_value: Optional[str]) -> Optional[dict]:
    """Verify and decrypt the OIDC transaction cookie."""
    if not cookie_value or _FERNET is None:
        return None
    try:
        raw = _FERNET.decrypt(cookie_value.encode("ascii"), ttl=_TX_MAX_AGE)
        payload = json.loads(raw.decode("utf-8"))
        if not all(k in payload for k in ("state", "nonce", "next", "iat")):
            return None
        return payload
    except Exception:
        return None


def _sanitize_next(value: str) -> str:
    """Only allow internal /liff/ destinations to prevent open redirect."""
    if not value or not value.startswith("/liff/"):
        return "/liff/"
    # Reject anything with a host or back-path traversal.
    parsed = urlparse(value)
    if parsed.netloc or ".." in value or "//" in value:
        return "/liff/"
    return value


# -----------------------------------------------------------------------------
# OIDC protocol helpers
# -----------------------------------------------------------------------------

def _authorize_url_params(state: str, nonce: str) -> dict:
    return {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
        "nonce": nonce,
    }


def login_url(next_path: str = "/liff/", state: Optional[str] = None, nonce: Optional[str] = None) -> str:
    """Build the libsso authorization URL.

    If state and nonce are provided they are used directly (e.g. after building
    the transaction cookie).  Otherwise a fresh state/nonce pair is generated.
    """
    if not OIDC_CONFIGURED:
        raise RuntimeError("OIDC is not configured")
    if not state or not nonce:
        state, nonce, _ = build_tx_cookie(next_path)
    params = _authorize_url_params(state, nonce)
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code(code: str) -> dict:
    """Exchange an authorization code for tokens using client_secret_post."""
    if TOKEN_AUTH_METHOD != "client_secret_post":
        raise RuntimeError(f"Unsupported OIDC token auth method: {TOKEN_AUTH_METHOD}")
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }
    with httpx.Client(timeout=10.0) as client:
        response = client.post(TOKEN_URL, data=payload)
        response.raise_for_status()
        return response.json()


def _fetch_jwks() -> dict:
    with httpx.Client(timeout=10.0) as client:
        response = client.get(JWKS_URL)
        response.raise_for_status()
        return response.json()


def verify_id_token(raw_token: str, expected_nonce: str) -> dict:
    """Verify an ID token and return its claims."""
    header = jwt.get_unverified_header(raw_token)
    alg = header.get("alg", SIGNING_ALG)
    kid = header.get("kid")

    common_options = {
        "verify_exp": True,
        "verify_iat": True,
        "verify_aud": True,
        "verify_iss": True,
        "require": ["exp", "iat", "nonce"],
    }

    if alg == "RS256":
        jwks = _fetch_jwks()
        matching_key = None
        for key in jwks.get("keys", []):
            if kid is None or key.get("kid") == kid:
                matching_key = key
                break
        if matching_key is None:
            raise jwt.InvalidTokenError("No matching signing key found in JWKS")
        signing_key = jwt.PyJWK(matching_key)
        claims = jwt.decode(
            raw_token,
            signing_key,
            algorithms=["RS256"],
            audience=CLIENT_ID,
            issuer=ISSUER,
            options=common_options,
        )
    elif alg == "HS256":
        claims = jwt.decode(
            raw_token,
            CLIENT_SECRET.encode("utf-8"),
            algorithms=["HS256"],
            audience=CLIENT_ID,
            issuer=ISSUER,
            options=common_options,
        )
    else:
        raise jwt.InvalidTokenError(f"Unsupported signing algorithm: {alg}")

    if claims.get("nonce") != expected_nonce:
        raise jwt.InvalidTokenError("Nonce mismatch")
    return claims


def fetch_userinfo(access_token: str) -> dict:
    """Fetch userinfo from the OIDC provider."""
    headers = {"Authorization": f"Bearer {access_token}"}
    with httpx.Client(timeout=10.0) as client:
        response = client.get(USERINFO_URL, headers=headers)
        response.raise_for_status()
        return response.json()


# -----------------------------------------------------------------------------
# Domain / role helpers
# -----------------------------------------------------------------------------

def _email_domain(email: str) -> str:
    return (email.split("@")[-1]).lower().strip()


def _allowed_email(email: str) -> bool:
    if not ALLOWED_DOMAINS:
        return True
    return _email_domain(email) in ALLOWED_DOMAINS


def _resolve_role(email: str) -> str:
    if email.lower() in ADMIN_EMAILS:
        return "admin"
    if DEFAULT_ROLE in {"viewer", "operator", "admin"}:
        return DEFAULT_ROLE
    return "viewer"


def _is_email_verified(value) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


# -----------------------------------------------------------------------------
# DB adapter integration
# -----------------------------------------------------------------------------

try:
    import db  # type: ignore
except Exception:  # pragma: no cover - graceful import degradation
    db = None  # type: ignore


def _ensure_db():
    if db is None:
        raise RuntimeError("db adapter is not available")


def init_oidc_tables() -> None:
    """Create tables required by OIDC web sessions if they do not exist."""
    _ensure_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS web_users (
            sub TEXT PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'viewer',
            provider TEXT NOT NULL DEFAULT 'libsso',
            created_at_ms INTEGER NOT NULL,
            last_login_ms INTEGER NOT NULL
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS web_auth_sessions (
            token_hash TEXT PRIMARY KEY,
            sub TEXT NOT NULL,
            display_name TEXT NOT NULL,
            role TEXT NOT NULL,
            provider TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL,
            expires_at_ms INTEGER NOT NULL
        )
        """
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_web_auth_sessions_expires ON web_auth_sessions(expires_at_ms)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_web_auth_sessions_sub ON web_auth_sessions(sub)"
    )


def _row_value(row: Any, key: str, index: int = 0) -> Any:
    """Normalise a DB row that may be a dict, sqlite3.Row, or tuple."""
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(key)
    keys = getattr(row, "keys", None)
    if keys is not None:
        return dict(row).get(key)
    return row[index] if len(row) > index else None


def ensure_web_user(
    sub: str,
    email: str,
    display_name: str,
    role: str,
    *,
    force_role: bool = False,
) -> None:
    """Upsert a web user, preserving an existing role unless upgrading to admin."""
    _ensure_db()
    now_ms = int(time.time() * 1000)
    existing = db.fetchone("SELECT role FROM web_users WHERE sub = :sub", {"sub": sub})
    existing_role = _row_value(existing, "role", 0) if existing else None
    if force_role or role == "admin" or not existing_role:
        final_role = role
    else:
        final_role = existing_role

    db.execute(
        """
        INSERT INTO web_users (sub, email, display_name, role, provider, created_at_ms, last_login_ms)
        VALUES (:sub, :email, :display_name, :role, :provider, :created_at_ms, :last_login_ms)
        ON CONFLICT(sub) DO UPDATE SET
            email = excluded.email,
            display_name = excluded.display_name,
            role = :final_role,
            last_login_ms = excluded.last_login_ms
        """,
        {
            "sub": sub,
            "email": email,
            "display_name": display_name,
            "role": final_role,
            "final_role": final_role,
            "provider": "libsso",
            "created_at_ms": now_ms,
            "last_login_ms": now_ms,
        },
    )


def create_web_auth_session(
    sub: str,
    display_name: str,
    role: str,
    provider: str,
    ttl_seconds: int,
) -> str:
    """Create a server-side session and return its opaque token."""
    _ensure_db()
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now_ms = int(time.time() * 1000)
    expires_at_ms = now_ms + max(300, ttl_seconds) * 1000
    username = sub
    db.execute(
        """
        INSERT INTO web_auth_sessions (token_hash, username, sub, display_name, role, provider, created_at_ms, expires_at_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (token_hash, username, sub, display_name, role, provider, now_ms, expires_at_ms),
    )
    return token


def get_web_auth_session(token_hash: str) -> Optional[dict]:
    """Return a valid session or None, pruning expired rows."""
    _ensure_db()
    now_ms = int(time.time() * 1000)
    db.execute("DELETE FROM web_auth_sessions WHERE expires_at_ms < ?", (now_ms,))
    row = db.fetchone(
        """
        SELECT token_hash, sub, username, display_name, role, provider, created_at_ms, expires_at_ms
        FROM web_auth_sessions
        WHERE token_hash = ? AND expires_at_ms >= ?
        """,
        (token_hash, now_ms),
    )
    if row is None:
        return None
    if not row.get("role") and row.get("username"):
        row["role"] = "admin"
        row["display_name"] = row.get("display_name") or row["username"]
        row["sub"] = row.get("sub") or row["username"]
        row["provider"] = row.get("provider") or "password"
    return row


def delete_web_auth_session(token_hash: str) -> None:
    _ensure_db()
    db.execute("DELETE FROM web_auth_sessions WHERE token_hash = ?", (token_hash,))


# -----------------------------------------------------------------------------
# Authentication orchestration
# -----------------------------------------------------------------------------

def authenticate(
    code: str,
    state: str,
    tx_cookie: Optional[str],
) -> Tuple[Optional[str], Optional[dict]]:
    """Validate the OIDC callback and return (error_code, user_dict)."""
    payload = parse_tx_cookie(tx_cookie)
    if payload is None or payload.get("state") != state:
        return "invalid_state", None

    try:
        token_response = exchange_code(code)
    except Exception:
        return "token_error", None

    id_token = token_response.get("id_token")
    if not id_token:
        return "token_error", None

    try:
        id_claims = verify_id_token(id_token, payload["nonce"])
    except Exception:
        return "invalid_id_token", None

    try:
        userinfo = fetch_userinfo(token_response.get("access_token", ""))
    except Exception:
        # Prefer userinfo but fall back to ID token claims when userinfo is unavailable.
        userinfo = id_claims

    email = (userinfo.get("email") or id_claims.get("email") or "").strip().lower()
    if not email:
        return "email_missing", None

    verified_userinfo = _is_email_verified(userinfo.get("email_verified"))
    verified_id = _is_email_verified(id_claims.get("email_verified"))
    if not verified_userinfo and not verified_id:
        return "email_not_verified", None

    if not _allowed_email(email):
        return "domain_not_allowed", None

    sub = id_claims.get("sub") or userinfo.get("sub")
    if not sub:
        return "invalid_id_token", None

    display_name = userinfo.get("name") or id_claims.get("name") or email.split("@")[0]
    role = _resolve_role(email)
    ensure_web_user(sub, email, display_name, role)

    return None, {
        "sub": sub,
        "email": email,
        "display_name": display_name,
        "role": role,
        "provider": "libsso",
    }


# -----------------------------------------------------------------------------
# FastAPI helpers
# -----------------------------------------------------------------------------

def is_standard_web_request(request: Request) -> bool:
    """True when the request targets the standard web controller host."""
    if not WEB_AUTH_ENABLED:
        return False
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    return host.split(":", 1)[0].lower() == WEB_AUTH_HOST


def require_role(*roles: str):
    """Dependency factory that checks request.state.user.role.

    On non-standard-web requests (e.g. LINE LIFF on another host) the dependency
    returns None so existing LIFF endpoints keep working.
    """
    allowed = {r.strip().lower() for r in roles}

    async def _dependency(request: Request):
        if not is_standard_web_request(request):
            return None
        user = getattr(request.state, "user", None)
        if not user or user.get("role", "viewer").lower() not in allowed:
            raise HTTPException(status_code=403, detail="insufficient role")
        return user

    return _dependency


def set_session_cookie(response, token: str, ttl_seconds: int) -> None:
    """Set the web auth session cookie."""
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max(300, ttl_seconds),
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


def delete_session_cookie(response) -> None:
    """Remove the web auth session cookie."""
    response.delete_cookie(SESSION_COOKIE, path="/")


# -----------------------------------------------------------------------------
# Integration snippets for main.py
# -----------------------------------------------------------------------------
"""
1. Add dependencies to ``services/core-api/requirements.txt`` if they are not
   already present:

    PyJWT[crypto]>=2.10.0
    cryptography>=44.0.0

2. Import the OIDC helpers near the top of ``main.py``:

    from fastapi import Depends
    from oidc import (
        SESSION_COOKIE,
        SESSION_TTL_SECONDS,
        authenticate,
        build_tx_cookie,
        create_web_auth_session,
        delete_session_cookie,
        delete_web_auth_session,
        get_web_auth_session,
        init_oidc_tables,
        is_standard_web_request,
        login_url,
        parse_tx_cookie,
        require_role,
        set_session_cookie,
    )

3. Initialise the OIDC tables once at startup, for example right after
   ``init_command_history()``:

    init_oidc_tables()

4. Replace the existing ``standard_web_auth`` middleware with a version that
   resolves users from the OIDC session store.  This makes ``request.state.user``
   available to dependencies and keeps the same public-path logic:

    @app.middleware("http")
    async def standard_web_auth(request: Request, call_next):
        if not is_standard_web_request(request):
            return await call_next(request)

        path = request.url.path
        is_controller = path == "/liff" or path.startswith("/liff/")
        is_api = path.startswith("/liff-api/") or path.startswith("/api/")
        public = (
            path == "/liff/login"
            or path.startswith("/liff/login/")
            or path == "/liff/callback"
            or path.startswith("/liff-api/api/v1/web-auth/")
            or path.startswith("/api/v1/web-auth/")
        )

        user = None
        token = request.cookies.get(SESSION_COOKIE, "")
        if token:
            token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
            user = get_web_auth_session(token_hash)
        request.state.user = user

        if (is_controller or is_api) and not public and not user:
            if is_api:
                return JSONResponse({"detail": "login required"}, status_code=401)
            destination = path + (("?" + request.url.query) if request.url.query else "")
            return RedirectResponse(
                "/liff/login/?next=" + quote(destination, safe="/%?=&"), status_code=303
            )
        return await call_next(request)

5. Register the OIDC routes BEFORE ``app.mount("/liff", ...)`` so that the
   callback route is matched before the static-file mount:

    @app.get("/api/v1/web-auth/oidc/login")
    async def oidc_login(request: Request, next: str = "/liff/"):
        if not is_standard_web_request(request):
            raise HTTPException(status_code=404, detail="OIDC login not configured for this host")
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
        cookie = request.cookies.get("zenbo_oidc_tx", "")
        error, user = authenticate(code, state, cookie)
        response = RedirectResponse(
            "/liff/login/?error=" + error if error else "/liff/", status_code=303
        )
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

    @app.get("/api/v1/web-auth/me")
    async def web_auth_me(user: dict = Depends(require_role("viewer", "operator", "admin"))):
        return {"user": user}

    @app.post("/api/v1/web-auth/logout")
    async def web_auth_logout(request: Request):
        token = request.cookies.get(SESSION_COOKIE, "")
        if token:
            delete_web_auth_session(hashlib.sha256(token.encode("utf-8")).hexdigest())
        response = JSONResponse({"ok": True})
        delete_session_cookie(response)
        return response

6. Mount ``/liff`` static files AFTER the callback route is registered:

    if os.path.exists(LIFF_DIR):
        app.mount("/liff", NoStoreStaticFiles(directory=LIFF_DIR, html=True), name="liff")

7. Notes on existing handlers:
   - ``/api/v1/web-auth/login`` (username/password admin fallback) can stay.
   - Replace the existing ``/api/v1/web-auth/logout`` handler with the OIDC-aware
     version above so the same cookie is cleared from the OIDC session store.
   - Keep the existing ``/liff-api/`` alias middleware before the static mount.
"""
