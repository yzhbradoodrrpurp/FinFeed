"""Cloud entry point: owner-only WebAuthn and persistent private state."""
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
from data import security
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

    def finish_login(connection, response) -> None:
        old = request.cookies.get(session_cookie, "")
        database.execute(connection, "DELETE FROM sessions WHERE id=?", (digest(old),))
        set_cookie(response, session_cookie, database.new_session(connection), 43200)
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
        return jsonify(cloud=True, authenticated=bool(logged_in()), setupRequired=setup,
                       bootstrapAvailable=bool(bootstrap), passkeySupported=True)

    @app.post("/api/auth/register/options")
    def register_options():
        body = json_body()
        with database.transaction() as connection:
            owner = database.owner(connection)
            credentials = database.credentials(connection)
            if credentials:
                session = require_owner(recent=True, connection=connection)
                mode, binding = "add", session["id"]
            else:
                token = body.get("setupCode")
                if not bootstrap or not isinstance(token, str) or not secrets.compare_digest(token.encode(), bootstrap.encode()):
                    abort(403, description="首次绑定码不正确")
                mode, binding = "initial", None
            if len(credentials) >= 10:
                abort(400, description="最多绑定 10 把 Passkey")
            options = generate_registration_options(
                rp_id=parsed.hostname, rp_name="FinFeed", user_name="FinFeed Owner",
                user_display_name="FinFeed 私人账户", user_id=base64url_to_bytes(owner["user_handle"]),
                authenticator_selection=AuthenticatorSelectionCriteria(
                    resident_key=ResidentKeyRequirement.REQUIRED,
                    user_verification=UserVerificationRequirement.REQUIRED),
                exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(row["id"])) for row in credentials],
            )
            label = body.get("label", "我的 Passkey")
            if not isinstance(label, str) or not 1 <= len(label.strip()) <= 60:
                abort(400, description="Passkey 名称需为 1–60 个字符")
            token = database.flow(connection, {"kind": "register", "mode": mode, "binding": binding,
                                               "challenge": bytes_to_base64url(options.challenge), "label": label.strip()})
        response = jsonify(json.loads(options_to_json(options)))
        set_cookie(response, flow_cookie, token, 300)
        return response

    @app.post("/api/auth/register/verify")
    def register_verify():
        body = json_body()
        flow = database.consume_flow(request.cookies.get(flow_cookie, ""))
        if not flow or flow.get("kind") != "register":
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
            credentials = database.credentials(connection)
            if flow["mode"] == "initial":
                if credentials:
                    abort(403, description="首次绑定已完成，请先登录")
            else:
                session = require_owner(recent=True, connection=connection)
                if session["id"] != flow["binding"]:
                    abort(403, description="登录状态已改变，请重新开始")
            if len(credentials) >= 10:
                abort(400, description="最多绑定 10 把 Passkey")
            database.execute(connection, "INSERT INTO credentials VALUES (?,?,?,?,?)", (
                bytes_to_base64url(verification.credential_id),
                bytes_to_base64url(verification.credential_public_key), verification.sign_count,
                flow["label"], time.time()))
            response = jsonify(ok=True)
            finish_login(connection, response)
        return response

    @app.post("/api/auth/login/options")
    def login_options():
        json_body()
        with database.transaction() as connection:
            if not database.credentials(connection):
                abort(400, description="请先绑定第一把 Passkey")
            # Discoverable credential: no public list of credential identifiers.
            options = generate_authentication_options(rp_id=parsed.hostname,
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
            owner = database.owner(connection)
            credential_id = body.get("id")
            credential = database.execute(connection, "SELECT * FROM credentials WHERE id=?", (credential_id if isinstance(credential_id, str) else "",)).fetchone()
            if not credential:
                abort(401, description="Passkey 登录验证失败")
            try:
                handle = body.get("response", {}).get("userHandle")
                if handle is not None and base64url_to_bytes(handle) != base64url_to_bytes(owner["user_handle"]):
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
            finish_login(connection, response)
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
            rows = database.credentials(connection)
        return jsonify(passkeys=[{"label": row["label"], "created": row["created"]} for row in rows])

    @app.get("/api/state")
    def state_read():
        return jsonify(state=database.read_state())

    @app.put("/api/state")
    def state_write():
        try:
            return jsonify(state=database.update_state(json_body()))
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
