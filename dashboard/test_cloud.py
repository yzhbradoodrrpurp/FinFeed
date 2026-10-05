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
    def test_macro_requires_login_and_returns_public_card(self):
        self.assertEqual(self.client.get('/api/macro/jobs').status_code, 401)
        self.enroll()
        with patch('macro.snapshot', return_value={'id': 'jobs', 'metrics': [], 'errors': []}):
            self.assertEqual(self.client.get('/api/macro/jobs').json['id'], 'jobs')
        self.assertEqual(self.client.get('/api/macro/unknown').status_code, 404)

    def frontend_setup(self):
        self.frontend = "https://finfeed.vercel.app"
        self.app = create_app({"TESTING": True, "PUBLIC_ORIGIN": ORIGIN,
            "FRONTEND_ORIGIN": self.frontend, "BOOTSTRAP_TOKEN": "a" * 43}, self.store)
        self.client = self.app.test_client()
        self.enroll()

    def frontend_ticket(self):
        import base64, hashlib
        verifier = "v" * 43
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        result = self.post("/api/auth/frontend-ticket", {"challenge": challenge, "state": "s" * 43})
        self.assertEqual(result.status_code, 200)
        from urllib.parse import urlsplit, parse_qs
        target = urlsplit(result.json["redirect"])
        self.assertEqual(target.scheme + "://" + target.netloc, self.frontend)
        return parse_qs(target.fragment)["ticket"][0], verifier

    def test_frontend_handoff_pkce_session_and_replay(self):
        self.frontend_setup()
        ticket, verifier = self.frontend_ticket()
        frontend = self.app.test_client()
        headers = {**HEADERS, "Origin": self.frontend}
        self.assertEqual(frontend.post("/api/auth/login/options", json={}, headers=headers).status_code, 400)
        self.assertEqual(frontend.post("/api/auth/frontend-exchange", json={"ticket": ticket, "verifier": verifier}, headers={**HEADERS, "Origin": "https://evil.example"}).status_code, 403)
        response = frontend.post("/api/auth/frontend-exchange", json={"ticket": ticket, "verifier": verifier}, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertIn("HttpOnly", response.headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", response.headers["Set-Cookie"])
        self.assertEqual(frontend.get("/api/state").status_code, 200)
        self.assertEqual(frontend.put("/api/state", json={"watchlist": ["AAPL"], "positions": []}, headers=headers).status_code, 200)
        self.assertEqual(frontend.post("/api/auth/frontend-exchange", json={"ticket": ticket, "verifier": verifier}, headers=headers).status_code, 401)

    def test_frontend_wrong_verifier_and_revoked_parent_cannot_login(self):
        self.frontend_setup()
        ticket, verifier = self.frontend_ticket()
        headers = {**HEADERS, "Origin": self.frontend}
        frontend = self.app.test_client()
        self.assertEqual(frontend.post("/api/auth/frontend-exchange", json={"ticket": ticket, "verifier": "x" * 43}, headers=headers).status_code, 401)
        ticket, verifier = self.frontend_ticket()
        self.post("/api/auth/logout")
        self.assertEqual(frontend.post("/api/auth/frontend-exchange", json={"ticket": ticket, "verifier": verifier}, headers=headers).status_code, 401)

    def test_frontend_login_still_uses_existing_passkey_domain(self):
        self.frontend_setup()
        self.assertEqual(self.client.get("/login").status_code, 302)
        response = self.client.get("/login?frontend=1")
        self.assertEqual(response.status_code, 200)
        response.close()
        response = self.post("/api/auth/login/options")
        self.assertEqual(response.json["rpId"], "localhost")

    def test_frontend_enrollment_binds_existing_account_and_scopes_credentials(self):
        self.frontend_setup()
        before = self.client.get("/api/state").json
        headers = {**HEADERS, "Origin": self.frontend}
        response = self.client.post("/api/auth/register/options", json={}, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["rp"]["id"], "finfeed.vercel.app")
        self.assertEqual(response.json["excludeCredentials"], [])
        with patch("cloud.verify_registration_response", return_value=SimpleNamespace(
                credential_id=b"frontend-key", credential_public_key=b"publickey", sign_count=0)) as verify:
            response = self.client.post("/api/auth/register/verify", json={}, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(verify.call_args.kwargs["expected_origin"], self.frontend)
        self.assertEqual(self.client.get("/api/state").json["account"], before["account"])
        self.assertTrue(self.client.get("/api/auth/status").json["frontendPasskeyBound"])
        from webauthn.helpers import bytes_to_base64url
        front_id = bytes_to_base64url(b"frontend-key")
        front = self.client.post("/api/auth/login/options", json={}, headers=headers).json
        self.assertEqual([key["id"] for key in front["allowCredentials"]], [front_id])
        with patch("cloud.verify_authentication_response", return_value=SimpleNamespace(new_sign_count=1)) as verify:
            result = self.client.post("/api/auth/login/verify", json={"id": front_id, "response": {}}, headers=headers)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(verify.call_args.kwargs["expected_rp_id"], "finfeed.vercel.app")
        legacy = self.post("/api/auth/login/options").json
        self.assertNotIn(front_id, [key["id"] for key in legacy["allowCredentials"]])

    def test_cross_origin_flow_and_legacy_credential_rejected(self):
        self.frontend_setup()
        headers = {**HEADERS, "Origin": self.frontend}
        self.client.post("/api/auth/register/options", json={}, headers=headers)
        with patch("cloud.verify_registration_response") as verify:
            self.assertEqual(self.post("/api/auth/register/verify").status_code, 403)
            verify.assert_not_called()
        self.post("/api/auth/login/options")
        with patch("cloud.verify_authentication_response") as verify:
            self.assertEqual(self.client.post("/api/auth/login/verify", json={}, headers=headers).status_code, 403)
            verify.assert_not_called()
        self.post("/api/auth/logout")
        self.assertEqual(self.client.post("/api/auth/register/options", json={}, headers=headers).status_code, 401)

    def test_frontend_ticket_expiry_and_deleted_account(self):
        self.frontend_setup()
        ticket, verifier = self.frontend_ticket()
        with self.store.transaction() as connection:
            self.store.execute(connection, "UPDATE flows SET expires=0 WHERE id=?", (digest(ticket),))
        frontend = self.app.test_client()
        headers = {**HEADERS, "Origin": self.frontend}
        self.assertEqual(frontend.post("/api/auth/frontend-exchange", json={"ticket": ticket, "verifier": verifier}, headers=headers).status_code, 401)
        ticket, verifier = self.frontend_ticket()
        with self.store.transaction() as connection:
            user_id = self.store.owner(connection)["user_handle"]
            self.store.execute(connection, "INSERT INTO disabled_accounts VALUES (?,?)", (user_id, time.time()))
        self.assertEqual(frontend.post("/api/auth/frontend-exchange", json={"ticket": ticket, "verifier": verifier}, headers=headers).status_code, 401)

    def test_initial_state_returns_only_tracked_current_snapshots_without_provider(self):
        from data import SCHEMA_VERSION
        self.store.update_state({"initialize": True, "watchlist": ["AAPL", "OLD"], "positions": [{"ticker": "VOO", "quantity": 1, "averageCost": 10, "currency": "USD"}]})
        for symbol, version in (("AAPL", SCHEMA_VERSION), ("VOO", SCHEMA_VERSION), ("OLD", 0), ("OTHER", SCHEMA_VERSION)):
            self.store.set_cache("quote:" + symbol, {"ticker": symbol, "schema_version": version, "metrics": {"price": {"value": 100}}})
        self.assertEqual(self.client.get("/api/state").status_code, 401)
        self.enroll()
        with patch("cloud.security") as provider:
            response = self.client.get("/api/state")
            provider.assert_not_called()
        self.assertEqual(set(response.json["quotes"]), {"AAPL", "VOO"})
        self.assertTrue(response.json["quotes"]["AAPL"]["cached"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")

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
            backup = json.loads(reopened.execute(connection, "SELECT state FROM account_history").fetchone()["state"])
        self.assertEqual(backup, original)
        with self.assertRaises(ValueError):
            reopened.update_state(original, require_empty=True)
        invalid = self.client.put("/api/state", json={"positions": [{**position, "quantity": -1}]}, headers=HEADERS)
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(reopened.read_state(), state)

    def signup(self, client, credential=b"other-key", name="Other"):
        with self.store.transaction() as connection:
            self.store.execute(connection, "INSERT INTO invitations VALUES (?,?,?,NULL)", (digest("test-invite"), time.time(), time.time()+300))
        response = client.post("/api/auth/register/options", json={"newAccount": True, "name": name, "inviteCode": "test-invite"}, headers=HEADERS)
        self.assertEqual(response.status_code, 200)
        with patch("cloud.verify_registration_response", return_value=SimpleNamespace(
                credential_id=credential, credential_public_key=b"key", sign_count=0)):
            response = client.post("/api/auth/register/verify", json={}, headers=HEADERS)
        self.assertEqual(response.status_code, 200)
        return client.get("/api/auth/status").json["user"]["id"]

    def test_accounts_isolate_writes_and_allow_authenticated_cross_reads(self):
        self.enroll()
        owner = self.client.get("/api/auth/status").json["user"]["id"]
        original = {"watchlist": ["AAPL"], "positions": [{"ticker": "AAPL", "quantity": 2, "averageCost": 100, "currency": "USD"}]}
        self.client.put("/api/state", json=original, headers=HEADERS)
        other = self.app.test_client()
        other_id = self.signup(other)
        self.assertEqual(other.get("/api/state").json["state"], {"watchlist": [], "positions": []})
        other.put("/api/state", json={"watchlist": ["NVDA"]}, headers=HEADERS)
        shared = other.get("/api/state?user="+owner)
        self.assertTrue(shared.json["readOnly"])
        self.assertEqual(shared.json["state"], original)
        self.assertEqual(other.put("/api/state?user="+owner, json={"watchlist": ["MU"]}, headers=HEADERS).status_code, 403)
        self.assertEqual(other.put("/api/state", json={"user_id": owner, "watchlist": ["MU"]}, headers=HEADERS).status_code, 400)
        self.assertEqual(self.client.get("/api/state").json["state"], original)
        self.assertEqual(self.client.get("/api/state?user="+other_id).json["state"]["watchlist"], ["NVDA"])
        self.assertEqual(len(other.get("/api/auth/passkeys").json["passkeys"]), 1)
        self.assertEqual(len(other.get("/api/accounts").json["accounts"]), 2)
        self.assertEqual(self.app.test_client().get("/api/accounts").status_code, 401)
        self.assertEqual(self.app.test_client().get("/api/state?user="+owner).status_code, 401)
        reopened = Store(sqlite_path=self.path)
        self.assertEqual(reopened.read_state(owner), original)
        self.assertEqual(reopened.read_state(other_id)["watchlist"], ["NVDA"])

    def test_new_account_login_resolves_credential_owner_and_checks_handle(self):
        other = self.app.test_client()
        user_id = self.signup(other)
        other.post("/api/auth/logout", json={}, headers=HEADERS)
        other.post("/api/auth/login/options", json={}, headers=HEADERS)
        from webauthn.helpers import bytes_to_base64url
        with patch("cloud.verify_authentication_response", return_value=SimpleNamespace(new_sign_count=1)):
            response = other.post("/api/auth/login/verify", json={"id": bytes_to_base64url(b"other-key"), "response": {"userHandle": user_id}}, headers=HEADERS)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(other.get("/api/auth/status").json["user"]["id"], user_id)
        other.post("/api/auth/logout", json={}, headers=HEADERS)
        other.post("/api/auth/login/options", json={}, headers=HEADERS)
        self.assertEqual(other.post("/api/auth/login/verify", json={"id": bytes_to_base64url(b"other-key"), "response": {"userHandle": bytes_to_base64url(b"wrong")}}, headers=HEADERS).status_code, 401)

    def test_legacy_migration_preserves_credentials_sessions_state_and_history(self):
        import sqlite3
        path = str(Path(self.directory.name) / "legacy.db")
        with sqlite3.connect(path) as connection:
            connection.executescript("CREATE TABLE owner (id INTEGER PRIMARY KEY, user_handle TEXT, state TEXT, revision INTEGER); CREATE TABLE credentials (id TEXT PRIMARY KEY, public_key TEXT, sign_count BIGINT, label TEXT, created DOUBLE PRECISION); CREATE TABLE sessions (id TEXT PRIMARY KEY,created DOUBLE PRECISION,expires DOUBLE PRECISION); CREATE TABLE state_history (revision INTEGER PRIMARY KEY,state TEXT,created DOUBLE PRECISION);")
            state = json.dumps({"watchlist": ["GOOG"], "positions": []})
            connection.execute("INSERT INTO owner VALUES (1,'legacy-handle',?,2)", (state,))
            connection.execute("INSERT INTO credentials VALUES ('key','public',0,'Mac',1)")
            connection.execute("INSERT INTO sessions VALUES (?,1,?)", (digest('token'), time.time()+300))
            connection.execute("INSERT INTO state_history VALUES (1,?,1)", (state,))
        migrated = Store(sqlite_path=path)
        self.assertEqual(migrated.read_state()['watchlist'], ['GOOG'])
        with migrated.transaction() as connection:
            self.assertEqual(migrated.session(connection, 'token')['user_id'], 'legacy-handle')
            self.assertEqual(migrated.credentials(connection)[0]['user_id'], 'legacy-handle')
            self.assertEqual(migrated.execute(connection, "SELECT user_id FROM account_history").fetchone()['user_id'], 'legacy-handle')
        migrated.update_state({'watchlist':['AAPL']})
        self.assertEqual(Store(sqlite_path=path).read_state()['watchlist'], ['AAPL'])

    def test_invitation_required_single_use_and_all_users_can_issue(self):
        self.enroll()
        owner = self.client.get("/api/auth/status").json["user"]["id"]
        self.assertTrue(self.client.get("/api/auth/status").json["canInvite"])
        invite = self.post("/api/invitations").json["code"]
        other = self.app.test_client()
        for code in (None, "wrong"):
            response = other.post("/api/auth/register/options", json={"newAccount": True, "name": "Friend", "inviteCode": code}, headers=HEADERS)
            self.assertEqual(response.status_code, 403)
        body = {"newAccount": True, "name": "Friend", "inviteCode": invite}
        self.assertEqual(other.post("/api/auth/register/options", json=body, headers=HEADERS).status_code, 200)
        competing = self.app.test_client()
        self.assertEqual(competing.post("/api/auth/register/options", json=body, headers=HEADERS).status_code, 200)
        with patch("cloud.verify_registration_response", return_value=SimpleNamespace(credential_id=b"friend", credential_public_key=b"public", sign_count=0)):
            self.assertEqual(other.post("/api/auth/register/verify", json={}, headers=HEADERS).status_code, 200)
        with patch("cloud.verify_registration_response", return_value=SimpleNamespace(credential_id=b"competing", credential_public_key=b"public", sign_count=0)):
            self.assertEqual(competing.post("/api/auth/register/verify", json={}, headers=HEADERS).status_code, 403)
        self.assertEqual(competing.post("/api/auth/register/options", json=body, headers=HEADERS).status_code, 403)
        self.assertTrue(other.get("/api/auth/status").json["canInvite"])
        self.assertEqual(other.post("/api/invitations", json={}, headers=HEADERS).status_code, 200)
        self.assertEqual(other.get("/api/admin/accounts").status_code, 403)
        self.assertEqual(self.app.test_client().post("/api/invitations", json={}, headers=HEADERS).status_code, 401)
        self.assertIn(self.client.patch("/api/account", json={"name":"Changed"}, headers=HEADERS).status_code, (404,405))
        self.assertEqual(self.client.get("/api/auth/status").json["user"]["name"], "Liam")
        with self.store.transaction() as connection:
            row=self.store.execute(connection, "SELECT * FROM invitations WHERE id=?", (digest(invite),)).fetchone()
            self.assertIsNotNone(row['used_by'])
            self.assertNotEqual(row['id'], invite)
        expired = self.post("/api/invitations").json["code"]
        with self.store.transaction() as connection:
            self.store.execute(connection, "UPDATE invitations SET expires=0 WHERE id=?", (digest(expired),))
        self.assertEqual(competing.post("/api/auth/register/options", json={**body,"inviteCode":expired}, headers=HEADERS).status_code,403)

    def test_admin_only_account_and_passkey_deletion_revokes_access_and_is_recoverable(self):
        from webauthn.helpers import bytes_to_base64url
        self.enroll()
        self.assertTrue(self.client.get('/api/auth/status').json['isAdmin'])
        other=self.app.test_client()
        other_id=self.signup(other)
        key=bytes_to_base64url(b'other-key')
        other.put('/api/state',json={'watchlist':['AAPL']},headers=HEADERS)
        self.assertFalse(other.get('/api/auth/status').json['isAdmin'])
        self.assertEqual(other.get('/api/admin/accounts').status_code,403)
        for path in ('/api/admin/accounts/'+other_id, '/api/admin/passkeys/'+key):
            self.assertEqual(other.delete(path,json={},headers=HEADERS).status_code,403)
        self.assertEqual(other.post('/api/admin/accounts/'+other_id+'/restore',json={},headers=HEADERS).status_code,403)
        self.assertEqual(other.post('/api/admin/passkeys/'+key+'/restore',json={},headers=HEADERS).status_code,403)
        admin_id=self.client.get('/api/auth/status').json['user']['id']
        self.assertEqual(self.client.delete('/api/admin/accounts/'+admin_id,json={},headers=HEADERS).status_code,400)
        self.assertEqual(self.client.delete('/api/admin/passkeys/'+bytes_to_base64url(b'credential'),json={},headers=HEADERS).status_code,400)
        self.assertEqual(self.client.delete('/api/admin/passkeys/'+key,json={},headers=HEADERS).status_code,200)
        self.assertEqual(other.get('/api/state').status_code,401)
        other.post('/api/auth/login/options',json={},headers=HEADERS)
        with patch('cloud.verify_authentication_response') as verify:
            self.assertEqual(other.post('/api/auth/login/verify',json={'id':key,'response':{}},headers=HEADERS).status_code,401)
            verify.assert_not_called()
        self.assertEqual(self.client.post('/api/admin/passkeys/'+key+'/restore',json={},headers=HEADERS).status_code,200)
        self.assertEqual(self.client.delete('/api/admin/accounts/'+other_id,json={},headers=HEADERS).status_code,200)
        options = other.post('/api/auth/login/options',json={},headers=HEADERS).json
        self.assertNotIn(key, {k['id'] for k in options['allowCredentials']})
        self.assertIn(bytes_to_base64url(b'credential'), {k['id'] for k in options['allowCredentials']})
        self.assertEqual(self.client.get('/api/state?user='+other_id).status_code,404)
        self.assertNotIn(other_id,{a['id'] for a in self.client.get('/api/accounts').json['accounts']})
        listed=self.client.get('/api/admin/accounts').json['accounts']
        removed = next(a for a in listed if a['id']==other_id)
        self.assertTrue(removed['disabled'])
        self.assertTrue(all(k['revoked'] for k in removed['passkeys']))
        self.assertEqual(self.client.post('/api/admin/accounts/'+other_id+'/restore',json={},headers=HEADERS).status_code,200)
        self.assertEqual(self.client.get('/api/state?user='+other_id).json['state']['watchlist'],['AAPL'])

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
