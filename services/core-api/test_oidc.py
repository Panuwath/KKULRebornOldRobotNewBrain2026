"""Unit tests for the KKU libsso OIDC module.

These tests exercise the cookie cryptography, domain/role decisions, and JWKS
ID-token verification.  They intentionally avoid network calls by mocking
httpx and by stubbing the DB helpers in ``oidc.py``.
"""

import base64
import os
import sys
import time
import unittest
from unittest.mock import patch


class FakeDB:
    """Minimal stub DB so ``oidc.py`` can be imported before db.py exists."""

    def execute(self, sql, params=None):
        pass

    def fetchone(self, sql, params=None):
        return None

    def fetchall(self, sql, params=None):
        return []


class OidcModuleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ensure deterministic, test-only env values before importing oidc.
        os.environ["OIDC_ISSUER"] = "https://libsso.kku.ac.th"
        os.environ["OIDC_CLIENT_ID"] = "zenbo-core-test"
        os.environ["OIDC_CLIENT_SECRET"] = "test-client-secret-must-be-at-least-32-chars-ok"
        os.environ["OIDC_REDIRECT_URI"] = "https://lib.kku.ac.th/liff/callback"
        os.environ["OIDC_AUTHORIZE_URL"] = "https://libsso.kku.ac.th/oauth2/authorize"
        os.environ["OIDC_TOKEN_URL"] = "https://libsso.kku.ac.th/oauth2/token"
        os.environ["OIDC_USERINFO_URL"] = "https://libsso.kku.ac.th/oauth2/userinfo"
        os.environ["OIDC_JWKS_URL"] = "https://libsso.kku.ac.th/oauth2/jwks"
        os.environ["OIDC_SIGNING_ALG"] = "RS256"
        os.environ["APP_SECRET_KEY"] = "a" * 32
        os.environ["ZENBO_WEB_ALLOWED_EMAIL_DOMAINS"] = "kku.ac.th,kkumail.com"
        os.environ["ZENBO_WEB_ADMIN_EMAILS"] = "admin@kku.ac.th"
        os.environ["ZENBO_WEB_DEFAULT_ROLE"] = "viewer"
        os.environ["WEB_AUTH_SESSION_TTL_SECONDS"] = "28800"
        os.environ["WEB_AUTH_COOKIE"] = "zenbo_web_session"
        os.environ["ZENBO_WEB_AUTH_ENABLED"] = "true"
        os.environ["ZENBO_WEB_AUTH_HOST"] = "lib.kku.ac.th"

        # Save original db module and insert a stub DB adapter so oidc.py
        # can be imported without a real database during this test class.
        import importlib

        cls._original_db = sys.modules.get("db")
        sys.modules["db"] = FakeDB()

        sys.path.insert(0, os.path.dirname(__file__))
        import oidc

        # Reload with the test environment in case oidc was imported earlier.
        importlib.reload(oidc)
        cls.oidc = oidc

        def _restore_db_module():
            if cls._original_db is None:
                sys.modules.pop("db", None)
            else:
                sys.modules["db"] = cls._original_db

        cls.addClassCleanup(_restore_db_module)

    def setUp(self):
        # Stub the persistence helpers so the tests never need a real database.
        self.addCleanup(self._restore_db_helpers)
        self._orig_ensure = self.oidc.ensure_web_user
        self._orig_create_session = self.oidc.create_web_auth_session
        self.oidc.ensure_web_user = lambda *a, **kw: None
        self.oidc.create_web_auth_session = lambda *a, **kw: "test-session-token"

    def _restore_db_helpers(self):
        self.oidc.ensure_web_user = self._orig_ensure
        self.oidc.create_web_auth_session = self._orig_create_session

    # -------------------------------------------------------------------------
    # Cookie tests
    # -------------------------------------------------------------------------

    def test_tx_cookie_roundtrip(self):
        state, nonce, cookie = self.oidc.build_tx_cookie("/liff/control/")
        self.assertTrue(state)
        self.assertTrue(nonce)
        self.assertTrue(cookie)

        parsed = self.oidc.parse_tx_cookie(cookie)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["state"], state)
        self.assertEqual(parsed["nonce"], nonce)
        self.assertEqual(parsed["next"], "/liff/control/")

    def test_tx_cookie_invalid_value_returns_none(self):
        self.assertIsNone(self.oidc.parse_tx_cookie("not-a-cookie"))
        self.assertIsNone(self.oidc.parse_tx_cookie(""))
        self.assertIsNone(self.oidc.parse_tx_cookie(None))

    def test_tx_cookie_expires_after_ten_minutes(self):
        state, nonce, _ = self.oidc.build_tx_cookie("/liff/")
        payload = self.oidc.json.dumps(
            {"state": state, "nonce": nonce, "next": "/liff/", "iat": int(time.time()) - 900}
        ).encode("utf-8")
        # cryptography provides encrypt_at_time to set an older embedded timestamp.
        expired_cookie = self.oidc._FERNET.encrypt_at_time(payload, int(time.time()) - 900).decode("ascii")
        self.assertIsNone(self.oidc.parse_tx_cookie(expired_cookie))

    def test_login_url_rejects_invalid_next(self):
        url = self.oidc.login_url(next_path="https://evil.com/liff/")
        self.assertIn("%2Fliff%2F", url)
        self.assertNotIn("evil.com", url)

    # -------------------------------------------------------------------------
    # Domain / role helpers
    # -------------------------------------------------------------------------

    def test_allowed_domain_list_blocks_unknown_domains(self):
        self.assertTrue(self.oidc._allowed_email("user@kku.ac.th"))
        self.assertTrue(self.oidc._allowed_email("user@kkumail.com"))
        self.assertFalse(self.oidc._allowed_email("user@gmail.com"))

    def test_admin_emails_receive_admin_role(self):
        self.assertEqual(self.oidc._resolve_role("admin@kku.ac.th"), "admin")
        self.assertEqual(self.oidc._resolve_role("operator@kku.ac.th"), "viewer")

    # -------------------------------------------------------------------------
    # JWKS / ID token verification
    # -------------------------------------------------------------------------

    def _generate_rsa_keypair(self):
        try:
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.hazmat.primitives.serialization import (
                Encoding,
                NoEncryption,
                PrivateFormat,
            )
        except ImportError as exc:  # pragma: no cover
            raise unittest.SkipTest("cryptography is not installed") from exc

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private_pem = private_key.private_bytes(
            Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()
        )
        public_numbers = private_key.public_key().public_numbers()
        e_b64 = base64.urlsafe_b64encode(
            public_numbers.e.to_bytes((public_numbers.e.bit_length() + 7) // 8, "big")
        ).decode("ascii").rstrip("=")
        n_b64 = base64.urlsafe_b64encode(
            public_numbers.n.to_bytes((public_numbers.n.bit_length() + 7) // 8, "big")
        ).decode("ascii").rstrip("=")
        return private_pem, {"kty": "RSA", "kid": "test-key-1", "use": "sig", "n": n_b64, "e": e_b64}

    def test_verify_id_token_with_local_jwks(self):
        private_pem, jwk = self._generate_rsa_keypair()
        self.oidc._fetch_jwks = lambda: {"keys": [jwk]}

        now = int(time.time())
        claims = {
            "iss": self.oidc.ISSUER,
            "aud": self.oidc.CLIENT_ID,
            "sub": "user-123",
            "email": "user@kku.ac.th",
            "email_verified": True,
            "nonce": "test-nonce",
            "iat": now,
            "exp": now + 3600,
        }
        raw_token = self.oidc.jwt.encode(
            claims, private_pem, algorithm="RS256", headers={"kid": jwk["kid"]}
        )
        verified = self.oidc.verify_id_token(raw_token, "test-nonce")
        self.assertEqual(verified["sub"], "user-123")

    def test_verify_id_token_rejects_bad_nonce(self):
        private_pem, jwk = self._generate_rsa_keypair()
        self.oidc._fetch_jwks = lambda: {"keys": [jwk]}

        now = int(time.time())
        raw_token = self.oidc.jwt.encode(
            {
                "iss": self.oidc.ISSUER,
                "aud": self.oidc.CLIENT_ID,
                "sub": "user-123",
                "nonce": "expected-nonce",
                "iat": now,
                "exp": now + 3600,
            },
            private_pem,
            algorithm="RS256",
            headers={"kid": jwk["kid"]},
        )
        with self.assertRaises(self.oidc.jwt.InvalidTokenError):
            self.oidc.verify_id_token(raw_token, "wrong-nonce")

    # -------------------------------------------------------------------------
    # End-to-end authenticate flow
    # -------------------------------------------------------------------------

    def _make_token_response(self, id_token):
        return {
            "access_token": "test-access-token",
            "token_type": "Bearer",
            "id_token": id_token,
        }

    def _mock_httpx(self, token_response, userinfo_response):
        class FakeResponse:
            def __init__(self, payload):
                self._payload = payload

            def raise_for_status(self):
                pass

            def json(self):
                return self._payload

        class FakeClient:
            def __init__(inner_self, *args, **kwargs):
                pass

            def __enter__(inner_self):
                return inner_self

            def __exit__(inner_self, *args, **kwargs):
                return False

            def post(inner_self, url, **kwargs):
                return FakeResponse(token_response)

            def get(inner_self, url, **kwargs):
                return FakeResponse(userinfo_response)

        return patch("httpx.Client", FakeClient)

    def _build_id_token(self, email, nonce, kid, private_pem, name=None, verified=True):
        now = int(time.time())
        claims = {
            "iss": self.oidc.ISSUER,
            "aud": self.oidc.CLIENT_ID,
            "sub": "user-123",
            "email": email,
            "email_verified": verified,
            "nonce": nonce,
            "iat": now,
            "exp": now + 3600,
        }
        if name:
            claims["name"] = name
        return self.oidc.jwt.encode(
            claims, private_pem, algorithm="RS256", headers={"kid": kid}
        )

    def test_authenticate_allows_allowed_domain_and_assigns_default_role(self):
        private_pem, jwk = self._generate_rsa_keypair()
        self.oidc._fetch_jwks = lambda: {"keys": [jwk]}

        state, nonce, cookie = self.oidc.build_tx_cookie("/liff/control/")
        tx = self.oidc.parse_tx_cookie(cookie)
        id_token = self._build_id_token(
            "operator@kku.ac.th", tx["nonce"], jwk["kid"], private_pem, name="Op User"
        )
        userinfo = {"sub": "user-123", "name": "Op User", "email": "operator@kku.ac.th"}

        with self._mock_httpx(self._make_token_response(id_token), userinfo):
            error, user = self.oidc.authenticate("auth-code-123", state, cookie)

        self.assertIsNone(error)
        self.assertEqual(user["email"], "operator@kku.ac.th")
        self.assertEqual(user["display_name"], "Op User")
        self.assertEqual(user["role"], "viewer")
        self.assertEqual(user["provider"], "libsso")

    def test_authenticate_assigns_admin_role_for_admin_email(self):
        private_pem, jwk = self._generate_rsa_keypair()
        self.oidc._fetch_jwks = lambda: {"keys": [jwk]}

        state, nonce, cookie = self.oidc.build_tx_cookie("/liff/")
        tx = self.oidc.parse_tx_cookie(cookie)
        id_token = self._build_id_token(
            "admin@kku.ac.th", tx["nonce"], jwk["kid"], private_pem
        )

        with self._mock_httpx(self._make_token_response(id_token), {"email": "admin@kku.ac.th"}):
            error, user = self.oidc.authenticate("auth-code", state, cookie)

        self.assertIsNone(error)
        self.assertEqual(user["role"], "admin")

    def test_authenticate_rejects_disallowed_domain(self):
        private_pem, jwk = self._generate_rsa_keypair()
        self.oidc._fetch_jwks = lambda: {"keys": [jwk]}

        state, nonce, cookie = self.oidc.build_tx_cookie("/liff/")
        tx = self.oidc.parse_tx_cookie(cookie)
        id_token = self._build_id_token(
            "attacker@gmail.com", tx["nonce"], jwk["kid"], private_pem
        )

        with self._mock_httpx(self._make_token_response(id_token), {"email": "attacker@gmail.com"}):
            error, user = self.oidc.authenticate("auth-code", state, cookie)

        self.assertEqual(error, "domain_not_allowed")
        self.assertIsNone(user)

    def test_authenticate_rejects_invalid_state(self):
        state, nonce, cookie = self.oidc.build_tx_cookie("/liff/")
        error, user = self.oidc.authenticate("auth-code", "wrong-state", cookie)
        self.assertEqual(error, "invalid_state")
        self.assertIsNone(user)


if __name__ == "__main__":
    unittest.main()
