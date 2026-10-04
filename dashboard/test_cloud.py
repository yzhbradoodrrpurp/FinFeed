"""Authorization, enrollment ownership, replay and durable state boundaries."""
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cloud import create_app
from cloud_store import Store, digest

ORIGIN = "http://localhost"
HEADERS = {"Origin": ORIGIN, "X-FinFeed-Client": "1"}


class CloudCases(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = str(Path(self.directory.name) / "cloud.db")
        self.store = Store(sqlite_path=self.path)
        self.app = create_app({"TESTING": True, "PUBLIC_ORIGIN": ORIGIN,
                               "BOOTSTRAP_TOKEN": "a" * 43}, self.store)
        self.client = self.app.test_client()

    def post(self, url, body=None):
        return self.client.post(url, json=body or {}, headers=HEADERS)

    def enroll(self):
        response = self.post("/api/auth/register/options", {"setupCode": "a" * 43})
        self.assertEqual(response.status_code, 200)
        with patch("cloud.verify_registration_response", return_value=SimpleNamespace(
                credential_id=b"credential", credential_public_key=b"publickey", sign_count=0)) as verify:
            response = self.post("/api/auth/register/verify", {"id": "credential"})
        self.assertTrue(verify.call_args.kwargs["require_user_verification"])
        self.assertEqual(verify.call_args.kwargs["expected_origin"], ORIGIN)
        self.assertEqual(verify.call_args.kwargs["expected_rp_id"], "localhost")
        self.assertEqual(response.status_code, 200)
        return response

    def test_no_private_reads_or_writes_before_login(self):
        self.assertEqual(self.client.get("/").status_code, 302)
        self.assertEqual(self.client.get("/index.html").status_code, 302)
        for path in ("/api/state", "/api/security/AAPL", "/api/auth/passkeys"):
            self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.put("/api/state", json={"watchlist": ["AAPL"]}, headers=HEADERS).status_code, 401)
        self.assertEqual(self.client.get("/.local/state.json").status_code, 404)
        self.assertEqual(self.client.get("/login.html").status_code, 404)

    def test_setup_code_required_and_cannot_register_second_owner(self):
        self.assertEqual(self.post("/api/auth/register/options", {"setupCode": "wrong"}).status_code, 403)
        self.assertEqual(self.post("/api/auth/register/options", {"setupCode": "错误绑定码"}).status_code, 403)
        self.enroll()
        self.post("/api/auth/logout")
        self.assertEqual(self.post("/api/auth/register/options", {"setupCode": "a" * 43}).status_code, 401)

    def test_origin_content_type_and_host_checks(self):
        self.assertEqual(self.client.post("/api/auth/login/options", json={}).status_code, 403)
        headers = {**HEADERS, "Origin": "https://attacker.example"}
        self.assertEqual(self.client.post("/api/auth/login/options", json={}, headers=headers).status_code, 403)
        self.assertEqual(self.client.get("/api/auth/status", base_url="http://attacker.example").status_code, 403)
        self.assertEqual(self.client.post("/api/auth/login/options", data="{}", headers=HEADERS).status_code, 403)

    def test_consumed_and_expired_challenges_are_rejected(self):
        self.enroll()
        with patch("cloud.verify_registration_response") as verify:
            self.assertEqual(self.post("/api/auth/register/verify", {"id": "credential"}).status_code, 400)
            verify.assert_not_called()
        self.post("/api/auth/login/options")
        with self.store.transaction() as connection:
            self.store.execute(connection, "UPDATE flows SET expires=0")
        self.assertEqual(self.post("/api/auth/login/verify", {"id": "credential"}).status_code, 400)

    def test_unknown_or_forged_passkey_cannot_login(self):
        self.enroll()
        self.post("/api/auth/logout")
        self.post("/api/auth/login/options")
        self.assertEqual(self.post("/api/auth/login/verify", {"id": "unknown"}).status_code, 401)
        self.post("/api/auth/login/options")
        self.assertEqual(self.post("/api/auth/login/verify", {"id": "Y3JlZGVudGlhbA", "response": {}}).status_code, 401)
        self.assertEqual(self.client.get("/api/state").status_code, 401)

    def test_logout_revokes_session_and_private_data_is_not_cached(self):
        self.enroll()
        session = self.client.get_cookie("finfeed_test_session").value
        response = self.client.get("/api/state")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertTrue(self.client.get_cookie("finfeed_test_session").http_only)
        with self.store.transaction() as connection:
            self.assertEqual(self.store.session(connection, session)["id"], digest(session))
        self.post("/api/auth/logout")
        self.client.set_cookie("finfeed_test_session", session)
        self.assertEqual(self.client.get("/api/state").status_code, 401)

    def test_successful_login_and_fresh_login_needed_for_extra_passkey(self):
        self.enroll()
        self.post("/api/auth/logout")
        self.post("/api/auth/login/options")
        with patch("cloud.verify_authentication_response", return_value=SimpleNamespace(new_sign_count=1)) as verify:
            response = self.post("/api/auth/login/verify", {"id": "Y3JlZGVudGlhbA", "response": {}})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(verify.call_args.kwargs["require_user_verification"])
        self.assertEqual(self.client.get("/api/state").status_code, 200)
        with self.store.transaction() as connection:
            self.store.execute(connection, "UPDATE sessions SET created=?", (time.time()-301,))
        self.assertEqual(self.post("/api/auth/register/options").status_code, 403)

    def test_pending_initial_enrollment_cannot_replace_registered_owner(self):
        second = self.app.test_client()
        second.post("/api/auth/register/options", json={"setupCode": "a"*43}, headers=HEADERS)
        self.enroll()
        with patch("cloud.verify_registration_response", return_value=SimpleNamespace(
                credential_id=b"second", credential_public_key=b"key", sign_count=0)):
            response = second.post("/api/auth/register/verify", json={"id": "second"}, headers=HEADERS)
        self.assertEqual(response.status_code, 403)

    def test_state_survives_restart_partial_patch_keeps_positions_and_backup(self):
        self.enroll()
        position = {"ticker": "AAPL", "quantity": 2, "averageCost": 100, "currency": "USD"}
        original = {"watchlist": ["VOO", "AAPL"], "positions": [position]}
        self.assertEqual(self.client.put("/api/state", json=original, headers=HEADERS).status_code, 200)
        state = self.client.put("/api/state", json={"watchlist": ["AAPL", "VOO"]}, headers=HEADERS).json["state"]
        self.assertEqual(state["positions"], [position])
        reopened = Store(sqlite_path=self.path)
        self.assertEqual(reopened.read_state(), state)
        with reopened.transaction() as connection:
            backup = json.loads(reopened.execute(connection, "SELECT state FROM state_history").fetchone()["state"])
        self.assertEqual(backup, original)
        with self.assertRaises(ValueError):
            reopened.update_state(original, require_empty=True)
        invalid = self.client.put("/api/state", json={"positions": [{**position, "quantity": -1}]}, headers=HEADERS)
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(reopened.read_state(), state)

    def test_daily_cache_survives_restart(self):
        self.store.set_cache("quote:QA", {"financial_checked_at": "2026-10-04"})
        cached = Store(sqlite_path=self.path).get_cache("quote:QA")
        self.assertEqual(cached[0]["financial_checked_at"], "2026-10-04")

    def test_prod_requires_https_and_strong_bootstrap_code(self):
        with self.assertRaises(ValueError):
            create_app({"PUBLIC_ORIGIN": "http://example.com"}, self.store)
        with self.assertRaises(ValueError):
            create_app({"PUBLIC_ORIGIN": "https://example.com", "BOOTSTRAP_TOKEN": "short"}, self.store)
        app = create_app({"PUBLIC_ORIGIN": "https://example.com", "BOOTSTRAP_TOKEN": "a"*43}, self.store)
        response = app.test_client().post("/api/auth/register/options", json={"setupCode": "a"*43},
                  base_url="https://example.com", headers={**HEADERS, "Origin": "https://example.com"})
        self.assertIn("__Host-finfeed_flow=", response.headers["Set-Cookie"])
        self.assertIn("Secure", response.headers["Set-Cookie"])


if __name__ == "__main__":
    unittest.main()
