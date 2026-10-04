"""Cloud entry point: multi-account WebAuthn and persistent private state."""
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from urllib.parse import urlsplit

from flask import Flask, abort, g, jsonify, redirect, request, send_from_directory
import psycopg
from webauthn import (
    base64url_to_bytes, generate_authentication_options, generate_registration_options,
    options_to_json, verify_authentication_response, verify_registration_response,
)
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor,
    ResidentKeyRequirement, UserVerificationRequirement,
)

from cloud_store import Store, digest
from data import security, SCHEMA_VERSION
from state import SYMBOL

ROOT = Path(__file__).resolve().parent


def create_app(config: dict | None = None, store: Store | None = None) -> Flask:
    """Build the cloud service, failing closed if its origin/database are missing."""
    app = Flask(__name__, static_folder=None)
    app.config.update(
        PUBLIC_ORIGIN=os.environ.get("PUBLIC_ORIGIN") or os.environ.get("RENDER_EXTERNAL_URL", ""),
        BOOTSTRAP_TOKEN=os.environ.get("FINFEED_BOOTSTRAP_TOKEN", ""),
        DATABASE_URL=os.environ.get("DATABASE_URL", ""),
        MAX_CONTENT_LENGTH=65536,
    )
    app.config.update(config or {})
    origin = app.config["PUBLIC_ORIGIN"].rstrip("/")
    parsed = urlsplit(origin)
    local_test = app.testing and parsed.hostname == "localhost" and parsed.scheme == "http"
    if not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username or (parsed.scheme != "https" and not local_test):
        raise ValueError("PUBLIC_ORIGIN 必须是网站的 HTTPS origin（不含路径）")
    bootstrap = app.config["BOOTSTRAP_TOKEN"]
    if bootstrap and len(bootstrap) < 32:
        raise ValueError("首次绑定码至少需要 32 个字符，请在部署平台生成高强度随机值")
    database = store or Store(app.config["DATABASE_URL"])
    app.extensions["finfeed_store"] = database
    secure = not local_test
    session_cookie = "__Host-finfeed_session" if secure else "finfeed_test_session"
    flow_cookie = "__Host-finfeed_flow" if secure else "finfeed_test_flow"
    attempts: dict[str, list[float]] = {}
    attempt_lock = threading.Lock()

    def json_body() -> dict:
        body = request.get_json()
        if not isinstance(body, dict):
            abort(400, description="无效请求")
        return body

    def set_cookie(response, name: str, token: str, max_age: int) -> None:
        response.set_cookie(name, token, secure=secure, httponly=True,
                            samesite="Strict", path="/", max_age=max_age)

    def logged_in() -> dict | None:
        if not hasattr(g, "owner_session"):
            with database.transaction() as connection:
                g.owner_session = database.session(connection, request.cookies.get(session_cookie, ""))
        return g.owner_session

    def require_owner(*, recent: bool = False, connection=None) -> dict:
        session = database.session(connection, request.cookies.get(session_cookie, "")) if connection else logged_in()
        if not session:
            abort(401, description="请先使用 Passkey 登录")
        if recent and time.time() - session["created"] > 300:
            abort(403, description="添加 Passkey 前请退出并重新验证登录")
        return session

    def finish_login(connection, response, user_id) -> None:
        old = request.cookies.get(session_cookie, "")
        database.execute(connection, "DELETE FROM sessions WHERE id=?", (digest(old),))
        set_cookie(response, session_cookie, database.new_session(connection, user_id), 43200)
        response.delete_cookie(flow_cookie, secure=secure, httponly=True, samesite="Strict", path="/")

    @app.before_request
    def guard() -> None:
        if request.path != "/api/health" and request.host != parsed.netloc:
            abort(403, description="网站域名不匹配")
        if request.method in {"POST", "PUT", "DELETE", "PATCH"}:
            # Exact origin + non-simple JSON/header prevents cross-site writes/login CSRF.
            if request.headers.get("Origin") != origin or request.headers.get("X-FinFeed-Client") != "1" or request.mimetype != "application/json":
                abort(403, description="仅允许网站内发起的操作")
        if request.path.startswith("/api/auth/") and request.method == "POST":
            now = time.time()
            key = request.remote_addr or "unknown"
            with attempt_lock:
                for address in list(attempts):
                    attempts[address] = [stamp for stamp in attempts[address] if now - stamp < 60]
                    if not attempts[address]:
                        del attempts[address]
                stamps = attempts.setdefault(key, [])
                if len(stamps) >= 30 or sum(map(len, attempts.values())) >= 120:
                    abort(429, description="验证请求过多，请一分钟后重试")
                stamps.append(now)
        if request.path.startswith("/api/") and request.path != "/api/health" and not request.path.startswith("/api/auth/"):
            require_owner()

    @app.after_request
    def response_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.errorhandler(400)
    @app.errorhandler(401)
    @app.errorhandler(403)
    @app.errorhandler(405)
    @app.errorhandler(404)
    @app.errorhandler(413)
    @app.errorhandler(415)
    @app.errorhandler(429)
    def http_error(error):
        return jsonify(error=error.description), error.code

    @app.errorhandler(psycopg.Error)
    @app.errorhandler(sqlite3.Error)
    def database_error(error):
        # Driver messages can contain connection details. Never log their text.
        app.logger.warning("Database operation failed: %s", type(error).__name__)
        return jsonify(error="数据库暂不可用，请稍后重试"), 503

    @app.get("/api/health")
    def health():
        return jsonify(ok=True, service="FinFeed")

    @app.get("/api/auth/status")
    def auth_status():
        with database.transaction() as connection:
            setup = not database.credentials(connection)
        session = logged_in()
        with database.transaction() as connection:
            account = database.account(connection, session["user_id"]) if session else None
            database_owner_id = database.owner(connection)["user_handle"]
        return jsonify(user={"id": account["id"], "name": account["name"]} if account else None, registrationOpen=False, invitationRequired=True, isAdmin=bool(session and session["user_id"] == database_owner_id), canInvite=bool(session and session["user_id"] == database_owner_id), cloud=True, authenticated=bool(session), setupRequired=setup,
                       bootstrapAvailable=bool(bootstrap), passkeySupported=True)

    @app.post("/api/auth/register/options")
    def register_options():
        body = json_body()
        with database.transaction() as connection:
            owner = database.owner(connection)
            invite_id = None
            if body.get("newAccount"):
                if database.session(connection, request.cookies.get(session_cookie, "")):
                    abort(400, description="请退出当前账户后注册新账户")
                code = body.get("inviteCode")
                if not isinstance(code, str) or not 1 <= len(code.strip()) <= 100:
                    abort(403, description="请填写有效邀请码")
                invite_id = digest(code.strip())
                invitation = database.execute(connection, "SELECT * FROM invitations WHERE id=?", (invite_id,)).fetchone()
                if not invitation or invitation["used_by"] or invitation["expires"] <= time.time():
                    abort(403, description="邀请码无效、已使用或已过期")
                name = body.get("name", "")
                if not isinstance(name, str) or not 1 <= len(name.strip()) <= 40:
                    abort(400, description="账户名称需为 1–40 个字符")
                user_id = secrets.token_urlsafe(32)
                name = name.strip()
                mode, binding, credentials = "new", None, []
            elif database.credentials(connection):
                session = require_owner(recent=True, connection=connection)
                user_id = session["user_id"]
                name = database.account(connection, user_id)["name"]
                credentials = database.credentials(connection, user_id)
                mode, binding = "add", session["id"]
            else:
                token = body.get("setupCode")
                if not bootstrap or not isinstance(token, str) or not secrets.compare_digest(token.encode(), bootstrap.encode()):
                    abort(403, description="首次绑定码不正确")
                user_id, name = owner["user_handle"], "Liam"
                credentials = []
                mode, binding = "initial", None
            if len(credentials) >= 10:
                abort(400, description="最多绑定 10 把 Passkey")
            options = generate_registration_options(
                rp_id=parsed.hostname, rp_name="FinFeed", user_name=name,
                user_display_name=name, user_id=base64url_to_bytes(user_id),
                authenticator_selection=AuthenticatorSelectionCriteria(
                    resident_key=ResidentKeyRequirement.REQUIRED,
                    user_verification=UserVerificationRequirement.REQUIRED),
                exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(row["id"])) for row in credentials],
            )
            label = body.get("label", "我的 Passkey")
            if not isinstance(label, str) or not 1 <= len(label.strip()) <= 60:
                abort(400, description="Passkey 名称需为 1–60 个字符")
            token = database.flow(connection, {"kind": "register", "mode": mode, "binding": binding,
                                               "challenge": bytes_to_base64url(options.challenge), "label": label.strip(), "user_id": user_id, "name": name, "invite_id": invite_id})
        response = jsonify(json.loads(options_to_json(options)))
        set_cookie(response, flow_cookie, token, 300)
        return response

    @app.post("/api/auth/register/verify")
    def register_verify():
        body = json_body()
        flow = database.consume_flow(request.cookies.get(flow_cookie, ""))
        if not flow or flow.get("kind") != "register" or not flow.get("user_id"):
            abort(400, description="绑定请求已过期，请重新开始")
        try:
            verification = verify_registration_response(
                credential=body, expected_challenge=base64url_to_bytes(flow["challenge"]),
                expected_rp_id=parsed.hostname, expected_origin=origin, require_user_verification=True,
            )
        except (WebAuthnException, ValueError, TypeError, KeyError):
            abort(400, description="Passkey 绑定验证失败，请重新开始")
        with database.transaction() as connection:
            database.owner(connection)
            user_id = flow["user_id"]
            credentials = database.credentials(connection, user_id)
            if flow["mode"] == "initial":
                if database.credentials(connection):
                    abort(403, description="首次绑定已完成，请先登录")
            elif flow["mode"] == "new":
                invitation = database.execute(connection, "SELECT * FROM invitations WHERE id=?", (flow.get("invite_id"),)).fetchone()
                if not invitation or invitation["used_by"] or invitation["expires"] <= time.time():
                    abort(403, description="邀请码无效、已使用或已过期")
                database.execute(connection, "UPDATE invitations SET used_by=? WHERE id=?", (user_id, flow["invite_id"]))
                database.execute(connection, "INSERT INTO accounts (id,name,state,revision,created) VALUES (?,?,?,0,?)",
                                 (user_id, flow["name"], json.dumps({"watchlist": [], "positions": []}), time.time()))
            else:
                session = require_owner(recent=True, connection=connection)
                if session["id"] != flow["binding"] or session["user_id"] != user_id:
                    abort(403, description="登录状态已改变，请重新开始")
            if len(credentials) >= 10:
                abort(400, description="最多绑定 10 把 Passkey")
            if database.execute(connection, "SELECT id FROM credentials WHERE id=?", (bytes_to_base64url(verification.credential_id),)).fetchone():
                abort(400, description="这把 Passkey 已绑定，请使用它登录")
            database.execute(connection, "INSERT INTO credentials (id,public_key,sign_count,label,created,user_id) VALUES (?,?,?,?,?,?)", (
                bytes_to_base64url(verification.credential_id),
                bytes_to_base64url(verification.credential_public_key), verification.sign_count,
                flow["label"], time.time(), user_id))
            response = jsonify(ok=True)
            finish_login(connection, response, user_id)
        return response

    @app.post("/api/auth/login/options")
    def login_options():
        json_body()
        with database.transaction() as connection:
            credentials = database.credentials(connection)
            if not credentials:
                abort(400, description="请先绑定第一把 Passkey")
            # Limit the authenticator picker to credentials of active accounts.
            options = generate_authentication_options(rp_id=parsed.hostname,
                        allow_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(key["id"])) for key in credentials],
                        user_verification=UserVerificationRequirement.REQUIRED)
            token = database.flow(connection, {"kind": "login", "challenge": bytes_to_base64url(options.challenge)})
        response = jsonify(json.loads(options_to_json(options)))
        set_cookie(response, flow_cookie, token, 300)
        return response

    @app.post("/api/auth/login/verify")
    def login_verify():
        body = json_body()
        flow = database.consume_flow(request.cookies.get(flow_cookie, ""))
        if not flow or flow.get("kind") != "login":
            abort(400, description="登录请求已过期，请重新开始")
        with database.transaction() as connection:
            database.owner(connection)
            credential_id = body.get("id")
            credential = database.execute(connection, "SELECT * FROM credentials WHERE id=?", (credential_id if isinstance(credential_id, str) else "",)).fetchone()
            if not credential or database.execute(connection, "SELECT id FROM revoked_passkeys WHERE id=?", (credential_id,)).fetchone() or database.execute(connection, "SELECT id FROM disabled_accounts WHERE id=?", (credential["user_id"],)).fetchone():
                abort(401, description="Passkey 登录验证失败")
            account = database.account(connection, credential["user_id"])
            try:
                handle = body.get("response", {}).get("userHandle")
                if handle is not None and base64url_to_bytes(handle) != base64url_to_bytes(account["id"]):
                    abort(401, description="Passkey 登录验证失败")
                verification = verify_authentication_response(
                    credential=body, expected_challenge=base64url_to_bytes(flow["challenge"]),
                    expected_rp_id=parsed.hostname, expected_origin=origin,
                    credential_public_key=base64url_to_bytes(credential["public_key"]),
                    credential_current_sign_count=credential["sign_count"], require_user_verification=True,
                )
            except (WebAuthnException, ValueError, TypeError, KeyError, AttributeError):
                abort(401, description="Passkey 登录验证失败")
            database.execute(connection, "UPDATE credentials SET sign_count=? WHERE id=?", (verification.new_sign_count, credential["id"]))
            response = jsonify(ok=True)
            finish_login(connection, response, credential["user_id"])
        return response

    @app.post("/api/auth/logout")
    def logout():
        json_body()
        with database.transaction() as connection:
            database.execute(connection, "DELETE FROM sessions WHERE id=?", (digest(request.cookies.get(session_cookie, "")),))
        response = jsonify(ok=True)
        response.delete_cookie(session_cookie, secure=secure, httponly=True, samesite="Strict", path="/")
        response.delete_cookie(flow_cookie, secure=secure, httponly=True, samesite="Strict", path="/")
        return response

    @app.get("/api/auth/passkeys")
    def passkeys():
        require_owner()
        with database.transaction() as connection:
            rows = database.credentials(connection, logged_in()["user_id"])
        return jsonify(passkeys=[{"label": row["label"], "created": row["created"]} for row in rows])

    @app.get("/api/accounts")
    def accounts_read():
        return jsonify(accounts=database.accounts(), currentUser=logged_in()["user_id"])

    @app.post("/api/invitations")
    def invitation_create():
        body = json_body()
        if body:
            abort(400, description="无效邀请码请求")
        session = require_owner()
        with database.transaction() as connection:
            if session["user_id"] != database.owner(connection)["user_handle"]:
                abort(403, description="只有网站管理账户可以创建邀请码")
            issued = database.execute(connection, "SELECT COUNT(*) AS total FROM invitations WHERE used_by IS NULL AND expires>?", (time.time(),)).fetchone()["total"]
            if issued >= 20:
                abort(400, description="最多保留 20 个未使用的邀请码，请使用或等待现有码过期")
            code = secrets.token_urlsafe(24)
            expires = time.time() + 7 * 86400
            database.execute(connection, "INSERT INTO invitations (id,created,expires) VALUES (?,?,?)", (digest(code), time.time(), expires))
        return jsonify(code=code, expires=expires)

    def require_admin(connection):
        session = require_owner(connection=connection)
        if session["user_id"] != database.owner(connection)["user_handle"]:
            abort(403, description="仅管理员可以执行此操作")
        return session

    @app.get("/api/admin/accounts")
    def admin_accounts():
        with database.transaction() as connection:
            session = require_admin(connection)
            rows = database.execute(connection, "SELECT a.id,a.name,EXISTS(SELECT 1 FROM disabled_accounts d WHERE d.id=a.id) AS disabled FROM accounts a ORDER BY a.created").fetchall()
            users=[]
            for row in rows:
                keys=database.execute(connection, "SELECT c.id,c.label,c.created,EXISTS(SELECT 1 FROM revoked_passkeys r WHERE r.id=c.id) AS revoked FROM credentials c WHERE c.user_id=? ORDER BY c.created", (row["id"],)).fetchall()
                if not keys:
                    continue
                users.append({**dict(row), "admin": row["id"] == session["user_id"], "passkeys": [dict(k) for k in keys]})
        return jsonify(accounts=users)

    @app.delete("/api/admin/accounts/<user_id>")
    def admin_disable_account(user_id):
        json_body()
        with database.transaction() as connection:
            session = require_admin(connection)
            if user_id == session["user_id"]:
                abort(400, description="不能删除管理员账户")
            if not database.execute(connection, "SELECT id FROM accounts WHERE id=?", (user_id,)).fetchone():
                abort(404, description="账户不存在")
            database.execute(connection, "INSERT INTO disabled_accounts VALUES (?,?) ON CONFLICT(id) DO NOTHING", (user_id,time.time()))
            database.execute(connection, "DELETE FROM sessions WHERE user_id=?", (user_id,))
        return jsonify(ok=True)

    @app.post("/api/admin/accounts/<user_id>/restore")
    def admin_restore_account(user_id):
        json_body()
        with database.transaction() as connection:
            require_admin(connection)
            database.execute(connection, "DELETE FROM disabled_accounts WHERE id=?", (user_id,))
        return jsonify(ok=True)

    @app.delete("/api/admin/passkeys/<credential_id>")
    def admin_revoke_passkey(credential_id):
        json_body()
        with database.transaction() as connection:
            session = require_admin(connection)
            key=database.execute(connection, "SELECT * FROM credentials WHERE id=?", (credential_id,)).fetchone()
            if not key:
                abort(404, description="Passkey 不存在")
            if key["user_id"] == session["user_id"] and len(database.credentials(connection,session["user_id"])) <= 1:
                abort(400, description="不能删除管理员最后一把 Passkey")
            database.execute(connection, "INSERT INTO revoked_passkeys VALUES (?,?) ON CONFLICT(id) DO NOTHING", (credential_id,time.time()))
            database.execute(connection, "DELETE FROM sessions WHERE user_id=?", (key["user_id"],))
        return jsonify(ok=True)

    @app.post("/api/admin/passkeys/<credential_id>/restore")
    def admin_restore_passkey(credential_id):
        json_body()
        with database.transaction() as connection:
            require_admin(connection)
            database.execute(connection, "DELETE FROM revoked_passkeys WHERE id=?", (credential_id,))
        return jsonify(ok=True)

    @app.get("/api/state")
    def state_read():
        viewer_id = logged_in()["user_id"]
        user_id = request.args.get("user") or viewer_id
        try:
            state = database.read_state(user_id)
            with database.transaction() as connection:
                account = database.account(connection, user_id)
        except ValueError:
            abort(404, description="账户不存在")
        symbols = list(dict.fromkeys(state["watchlist"] + [p["ticker"] for p in state["positions"]])) if state else []
        snapshots = database.get_cached_quotes(symbols)
        return jsonify(account={"id": account["id"], "name": account["name"]}, readOnly=user_id != viewer_id, state=state, quotes={symbol: record for symbol, record in snapshots.items()
                                           if record.get("schema_version") == SCHEMA_VERSION})

    @app.put("/api/state")
    def state_write():
        if request.args.get("user") and request.args["user"] != logged_in()["user_id"]:
            abort(403, description="不能修改其他账户的记录")
        try:
            return jsonify(state=database.update_state(json_body(), user_id=logged_in()["user_id"]))
        except ValueError as error:
            return jsonify(error=str(error)), 400

    @app.get("/api/security/<symbol>")
    def quote(symbol: str):
        symbol = symbol.upper()
        if not SYMBOL.fullmatch(symbol):
            abort(400, description="无效 ticker")
        return jsonify(security(symbol, request.args.get("refresh") == "1", store=database))

    @app.get("/")
    @app.get("/index.html")
    def dashboard():
        if not logged_in():
            return redirect("/login")
        return send_from_directory(ROOT / "public", "index.html")

    @app.get("/login")
    def login_page():
        if logged_in():
            return redirect("/")
        return send_from_directory(ROOT / "public", "login.html")

    @app.get("/<path:filename>")
    def static_file(filename: str):
        if filename not in {"style.css", "app.js", "positions.js", "auth-client.js", "login.js"}:
            abort(404)
        return send_from_directory(ROOT / "public", filename)

    return app
