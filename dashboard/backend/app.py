"""Cloud entry point: multi-account WebAuthn and persistent private state."""
from backend.infrastructure.failure_log import failure
import json
import base64
import hashlib
import re
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from urllib.parse import urlsplit, urlencode

from flask import Flask, abort, g, jsonify, redirect, request, send_from_directory
import psycopg
from psycopg_pool import PoolTimeout
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

from backend.storage.store import Store, digest
from backend.services.securities import security, SCHEMA_VERSION
from backend.domain.state_validation import SYMBOL, validate

from backend.paths import DASHBOARD_ROOT as ROOT
STATIC_ASSETS = json.loads((ROOT / "frontend/manifest.json").read_text())


def create_app(config: dict | None = None, store: Store | None = None) -> Flask:
    """Build the cloud service, failing closed if its origin/database are missing."""
    app = Flask(__name__, static_folder=None)
    # Flask's default traceback includes the raw exception message, which can
    # carry authenticated provider URLs. Use our sanitized event instead.
    app.log_exception = lambda info: failure('backend', 'unhandled_exception', error=info[1],
                                             request_id=getattr(g, 'request_id', ''))
    app.config.update(
        PUBLIC_ORIGIN=os.environ.get("PUBLIC_ORIGIN") or os.environ.get("RENDER_EXTERNAL_URL", ""),
        FRONTEND_ORIGIN=os.environ.get("FRONTEND_ORIGIN", ""),
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
    frontend = app.config["FRONTEND_ORIGIN"].rstrip("/")
    if frontend:
        target = urlsplit(frontend)
        if target.scheme != "https" or not target.hostname or target.path or target.query or target.fragment or target.username or target.password or frontend == origin:
            raise ValueError("FRONTEND_ORIGIN 必须为独立前端的 HTTPS origin")
    if bootstrap and len(bootstrap) < 32:
        raise ValueError("首次绑定码至少需要 32 个字符，请在部署平台生成高强度随机值")
    database = store or Store(app.config["DATABASE_URL"])
    if not local_test:
        database.enable_snapshot_writer()
    from backend.infrastructure.refresh_jobs import RefreshJobs
    refresh_jobs = RefreshJobs(database)
    app.extensions["finfeed_store"] = database
    from backend.storage.notifications import NotificationStore, DEFAULTS as NOTIFICATION_DEFAULTS
    from backend.infrastructure.mailer import Mailer, EMAIL, format_email
    from backend.services.notifications import NotificationWorker
    notifications = NotificationStore(database)
    mailer = Mailer({**os.environ, **app.config})
    notification_worker = NotificationWorker(notifications, mailer, database)
    app.extensions['finfeed_notifications'] = notifications
    app.extensions['finfeed_notification_worker'] = notification_worker
    tick_token = app.config.get('FINFEED_NOTIFICATION_CRON_TOKEN') or os.environ.get('FINFEED_NOTIFICATION_CRON_TOKEN','')

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
                g.owner_session = database.session(connection, request.cookies.get(session_cookie, ""), news=request.path.startswith("/api/news"))
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
        response.headers["X-FinFeed-Session-Max-Age"] = "43200"
        response.delete_cookie(flow_cookie, secure=secure, httponly=True, samesite="Strict", path="/")

    def ceremony_origin():
        return frontend if frontend and request.headers.get("Origin") == frontend else origin

    def check_ceremony(flow):
        if flow.get("origin", origin) != ceremony_origin():
            abort(403, description="验证域名已改变，请重新开始")

    @app.before_request
    def guard() -> None:
        g.request_started = time.monotonic()
        g.request_id = request.headers.get("X-FinFeed-Request-ID", "")
        if not re.fullmatch(r"[a-f0-9]{16}", g.request_id):
            g.request_id = secrets.token_hex(8)
        if request.path != "/api/health" and request.host != parsed.netloc:
            abort(403, description="网站域名不匹配")
        if request.path == '/api/notifications/tick':
            if request.method != 'POST':abort(405)
            provided = request.headers.get('Authorization','')
            if len(tick_token)<32 or not secrets.compare_digest(provided, 'Bearer '+tick_token):
                abort(403, description='无效后台调度凭据')
            if request.mimetype != 'application/json':abort(415)
            return None
        if request.method in {"POST", "PUT", "DELETE", "PATCH"}:
            # Exact origin + non-simple JSON/header prevents cross-site writes/login CSRF.
            allowed = {origin}
            if frontend:
                allowed.add(frontend)
            if request.headers.get("Origin") not in allowed or request.headers.get("X-FinFeed-Client") != "1" or request.mimetype != "application/json":
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
        if response.status_code >= 400:
            payload = response.get_json(silent=True) if response.is_json else None
            failure('backend', request.url_rule.rule if request.url_rule else 'unmatched_route',
                    reason=payload.get('error', 'HTTP request failed') if isinstance(payload, dict) else 'HTTP request failed', http_method=request.method,
                    response_status=response.status_code, request_id=getattr(g, 'request_id', ''),
                    started=getattr(g, 'request_started', None))
        response.headers['X-Request-ID'] = getattr(g, 'request_id', '')
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.errorhandler(PoolTimeout)
    @app.errorhandler(psycopg.OperationalError)
    def database_unavailable(error):
        failure('database', 'request_unavailable', error=error,
                request_id=getattr(g, 'request_id', ''),
                pools={name: pool.get_stats() for name in ('pool', 'cache_pool')
                       if (pool := getattr(database, name, None)) is not None})
        response = jsonify(error="数据库连接暂时不可用，正在重试，请稍后再试")
        response.status_code = 503
        response.headers['Retry-After'] = '15'
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
        failure('backend', request.url_rule.rule if request.url_rule else 'unmatched_route',
                reason=error.description, error=error, request_id=getattr(g, 'request_id', ''))
        return jsonify(error=error.description), error.code

    @app.errorhandler(psycopg.Error)
    @app.errorhandler(sqlite3.Error)
    def database_error(error):
        # Driver messages can contain connection details. Never log their text.
        failure('database', 'request', reason='Database operation failed', error=error, request_id=getattr(g, 'request_id', ''))
        return jsonify(error="数据库暂不可用，请稍后重试"), 503

    @app.errorhandler(500)
    def internal_error(error):
        original = getattr(error, 'original_exception', None) or error
        failure('backend', 'unhandled_exception', error=original,
                request_id=getattr(g, 'request_id', ''))
        return jsonify(error='服务暂不可用，请稍后重试'), 500

    @app.post('/api/auth/client-failure')
    def client_failure():
        # Best-effort browser report: enums/numbers only, no response bodies or credentials.
        body = json_body()
        path = body.get('path', '')
        if not isinstance(path, str) or not path.startswith('/api/') or len(path) > 200 or '?' in path or '#' in path:
            abort(400, description='无效日志路径')
        category = body.get('category')
        if category not in {'network_error', 'http_error', 'invalid_response'}:
            abort(400, description='无效错误类别')
        try:
            endpoint, _ = app.url_map.bind(parsed.netloc).match(path, method=body.get('method', 'GET'))
            operation = next(rule.rule for rule in app.url_map.iter_rules(endpoint))
        except Exception:
            operation = 'unmatched_route'
        status = body.get('status')
        elapsed = body.get('elapsed_ms')
        failure('browser', operation, reason=category,
                response_status=status if type(status) is int and 400 <= status <= 599 else None,
                client_elapsed_ms=elapsed if type(elapsed) is int and 0 <= elapsed <= 3600000 else None,
                failed_request_id=body.get('request_id') if re.fullmatch(r'[a-f0-9]{16}', str(body.get('request_id', ''))) else None)
        return jsonify(ok=True)

    @app.get("/api/health")
    def health():
        return jsonify(ok=True, service="FinFeed")

    @app.get('/api/notifications')
    def notification_settings():
        session = require_owner()
        return jsonify(**notifications.settings(session['user_id']), configured=mailer.ready,
                       scheduler_configured=len(tick_token)>=32,
                       deliveries=notifications.delivery_status(session['user_id']))

    @app.post('/api/notifications/email')
    def notification_email():
        session=require_owner();body=json_body();email=body.get('email','')
        if not isinstance(email,str) or len(email)>254 or not EMAIL.fullmatch(email):
            abort(400,description='请输入有效邮箱地址')
        if not mailer.ready:return jsonify(error='邮件服务尚未配置，请先配置服务器发信渠道'),503
        try:
            with database.transaction() as connection:
                username=database.account(connection,session['user_id'],lock=False)['name']
            code=notifications.begin_verification(session['user_id'],email)
        except ValueError as exc:abort(429,description=str(exc))
        try:
            mailer.send(email,'FinFeed · 邮箱绑定验证码',
                format_email(username,'邮箱绑定验证码：'+code+'\n有效期：10 分钟。\n\n请勿向他人透露此验证码。如非您本人操作，请忽略本邮件。',verification=True),
                'verify-'+secrets.token_hex(24))
        except Exception as exc:
            failure('email','verification_send',error=exc)
            return jsonify(error='验证码发送暂时失败，请一分钟后重试'),503
        return jsonify(ok=True)

    @app.post('/api/notifications/verify')
    def notification_verify():
        session=require_owner();code=json_body().get('code','')
        if not isinstance(code,str) or not re.fullmatch(r'[0-9]{6}',code):abort(400,description='请输入六位验证码')
        if not notifications.verify(session['user_id'],code):abort(400,description='验证码错误、过期或尝试次数过多')
        return jsonify(**notifications.settings(session['user_id']))

    @app.put('/api/notifications')
    def notification_save():
        session=require_owner();prefs=json_body()
        if set(prefs)!=set(NOTIFICATION_DEFAULTS) or any(type(prefs[k]) is not bool for k in NOTIFICATION_DEFAULTS if k!='treasury_threshold'):
            abort(400,description='无效提醒设置')
        threshold=prefs['treasury_threshold']
        if isinstance(threshold,bool) or not isinstance(threshold,(float,int)) or not .1<=threshold<=20:
            abort(400,description='预警线须为 0.1% 至 20%')
        try:data=notifications.save(session['user_id'],prefs)
        except ValueError as exc:abort(400,description=str(exc))
        notification_worker.trigger()
        return jsonify(**data)

    @app.delete('/api/notifications/email')
    def notification_unbind():
        notifications.unbind(require_owner()['user_id'])
        return jsonify(ok=True)

    @app.post('/api/notifications/tick')
    def notification_tick():
        if not mailer.ready:return jsonify(error='邮件服务尚未配置'),503
        notification_worker.trigger()
        return jsonify(accepted=True),202

    @app.get("/api/ready")
    def readiness():
        # Authenticated diagnostics; liveness stays independent of DB recovery.
        with database.transaction() as connection:
            connection.execute("SELECT 1")
        return jsonify(ok=True, refresh_queues={key: lane.qsize() for key, lane in refresh_jobs.queues.items()})

    @app.post("/api/auth/frontend-ticket")
    def frontend_ticket():
        if not frontend:
            abort(404)
        session = require_owner(recent=True)
        body = json_body()
        challenge, state = body.get("challenge", ""), body.get("state", "")
        if not isinstance(challenge, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", challenge) or not isinstance(state, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", state):
            abort(400, description="无效前端登录请求")
        with database.transaction() as connection:
            token = database.flow(connection, {"kind": "frontend", "challenge": challenge,
                "state": state, "user_id": session["user_id"], "origin": frontend,
                "session_id": digest(request.cookies.get(session_cookie, ""))})
        return jsonify(redirect=frontend + "/auth/callback#" + urlencode({"ticket": token, "state": state}))

    @app.post("/api/auth/frontend-exchange")
    def frontend_exchange():
        if not frontend or request.headers.get("Origin") != frontend:
            abort(403)
        body = json_body()
        verifier = body.get("verifier", "")
        ticket = body.get("ticket", "")
        if not isinstance(verifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", verifier) or not isinstance(ticket, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", ticket):
            abort(400)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        flow = database.consume_flow(ticket)
        if not flow or flow.get("kind") != "frontend" or flow.get("origin") != frontend or not secrets.compare_digest(flow.get("challenge", ""), challenge):
            abort(401, description="登录链接无效或已过期，请重新登录")
        with database.transaction() as connection:
            active = database.execute(connection, "SELECT id FROM sessions WHERE id=? AND user_id=? AND expires>?", (flow["session_id"], flow["user_id"], time.time())).fetchone()
            if not active:
                abort(401)
            try:
                database.account(connection, flow["user_id"])
            except ValueError:
                abort(401)
            response = jsonify(ok=True)
            finish_login(connection, response, flow["user_id"])
        return response

    @app.get("/api/auth/status")
    def auth_status():
        with database.transaction() as connection:
            setup = not database.credentials(connection)
            session = database.session(connection, request.cookies.get(session_cookie, ""))
            account = database.account(connection, session["user_id"], lock=False) if session else None
            database_owner_id = database.owner(connection, lock=False)["user_handle"]
            bound = bool(account and frontend and any(key.get("rp_id") == urlsplit(frontend).hostname for key in database.credentials(connection, account["id"])))
        return jsonify(user={"id": account["id"], "name": account["name"]} if account else None, registrationOpen=False, invitationRequired=True, isAdmin=bool(session and session["user_id"] == database_owner_id), canInvite=bool(session), cloud=True, authenticated=bool(session), setupRequired=setup,
                       bootstrapAvailable=bool(bootstrap), passkeySupported=True, frontendPasskeyBound=bound,
                       sessionExpiresIn=max(0, session["expires"] - time.time()) if session else 0)

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
                rp_id=urlsplit(ceremony_origin()).hostname, rp_name="FinFeed", user_name=name,
                user_display_name=name, user_id=base64url_to_bytes(user_id),
                authenticator_selection=AuthenticatorSelectionCriteria(
                    resident_key=ResidentKeyRequirement.REQUIRED,
                    user_verification=UserVerificationRequirement.REQUIRED),
                exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(row["id"])) for row in credentials if (row.get("rp_id") or parsed.hostname) == urlsplit(ceremony_origin()).hostname],
            )
            label = body.get("label", "我的 Passkey")
            if not isinstance(label, str) or not 1 <= len(label.strip()) <= 60:
                abort(400, description="Passkey 名称需为 1–60 个字符")
            token = database.flow(connection, {"kind": "register", "origin": ceremony_origin(), "mode": mode, "binding": binding,
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
        check_ceremony(flow)
        try:
            verification = verify_registration_response(
                credential=body, expected_challenge=base64url_to_bytes(flow["challenge"]),
                expected_rp_id=urlsplit(flow.get("origin", origin)).hostname, expected_origin=flow.get("origin", origin), require_user_verification=True,
            )
        except (WebAuthnException, ValueError, TypeError, KeyError) as exc:
            failure("webauthn", "registration_verify", error=exc, reason="Passkey registration validation failed", request_id=g.request_id)
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
            database.execute(connection, "INSERT INTO credentials (id,public_key,sign_count,label,created,user_id,rp_id) VALUES (?,?,?,?,?,?,?)", (
                bytes_to_base64url(verification.credential_id),
                bytes_to_base64url(verification.credential_public_key), verification.sign_count,
                flow["label"], time.time(), user_id, urlsplit(flow.get("origin", origin)).hostname))
            response = jsonify(ok=True)
            finish_login(connection, response, user_id)
        return response

    @app.post("/api/auth/login/options")
    def login_options():
        json_body()
        with database.transaction() as connection:
            credentials = [key for key in database.credentials(connection) if (key.get("rp_id") or parsed.hostname) == urlsplit(ceremony_origin()).hostname]
            if not credentials:
                abort(400, description="此网址还没有可用的 Passkey，请先通过原网址登录并绑定")
            # Limit the authenticator picker to credentials of active accounts.
            options = generate_authentication_options(rp_id=urlsplit(ceremony_origin()).hostname,
                        allow_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(key["id"])) for key in credentials],
                        user_verification=UserVerificationRequirement.REQUIRED)
            token = database.flow(connection, {"kind": "login", "origin": ceremony_origin(), "challenge": bytes_to_base64url(options.challenge)})
        response = jsonify(json.loads(options_to_json(options)))
        set_cookie(response, flow_cookie, token, 300)
        return response

    @app.post("/api/auth/login/verify")
    def login_verify():
        body = json_body()
        flow = database.consume_flow(request.cookies.get(flow_cookie, ""))
        if not flow or flow.get("kind") != "login":
            abort(400, description="登录请求已过期，请重新开始")
        check_ceremony(flow)
        with database.transaction() as connection:
            database.owner(connection)
            credential_id = body.get("id")
            credential = database.execute(connection, "SELECT * FROM credentials WHERE id=?", (credential_id if isinstance(credential_id, str) else "",)).fetchone()
            if not credential or database.execute(connection, "SELECT id FROM revoked_passkeys WHERE id=?", (credential_id,)).fetchone() or database.execute(connection, "SELECT id FROM disabled_accounts WHERE id=?", (credential["user_id"],)).fetchone():
                abort(401, description="Passkey 登录验证失败")
            if (credential["rp_id"] or parsed.hostname) != urlsplit(flow.get("origin", origin)).hostname:
                abort(401, description="Passkey 不属于此网址")
            account = database.account(connection, credential["user_id"])
            try:
                handle = body.get("response", {}).get("userHandle")
                if handle is not None and base64url_to_bytes(handle) != base64url_to_bytes(account["id"]):
                    abort(401, description="Passkey 登录验证失败")
                verification = verify_authentication_response(
                    credential=body, expected_challenge=base64url_to_bytes(flow["challenge"]),
                    expected_rp_id=urlsplit(flow.get("origin", origin)).hostname, expected_origin=flow.get("origin", origin),
                    credential_public_key=base64url_to_bytes(credential["public_key"]),
                    credential_current_sign_count=credential["sign_count"], require_user_verification=True,
                )
            except (WebAuthnException, ValueError, TypeError, KeyError, AttributeError) as exc:
                failure("webauthn", "login_verify", error=exc, reason="Passkey authentication validation failed", request_id=g.request_id)
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
        require_owner()
        with database.transaction() as connection:
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
            keys = database.execute(connection, "SELECT id FROM credentials WHERE user_id=?", (user_id,)).fetchall()
            for key in keys:
                database.execute(connection, "INSERT INTO revoked_passkeys VALUES (?,?) ON CONFLICT(id) DO NOTHING", (key["id"],time.time()))
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

    @app.get("/api/preferences")
    def preferences_read():
        from backend.domain.state_validation import display_preferences
        user_id = require_owner()["user_id"]
        with database.transaction() as connection:
            account = database.account(connection, user_id, lock=False)
            state = json.loads(account["state"]) if account["state"] else None
        return jsonify(preferences=display_preferences(state))

    @app.put("/api/preferences")
    def preferences_write():
        from backend.domain.state_validation import display_preferences, validate_preferences
        user_id = require_owner()["user_id"]
        if request.args.get("user") and request.args["user"] != user_id:
            abort(403, description="不能修改其他账户的展示设置")
        try:
            preferences = validate_preferences(json_body())
            state = database.update_state({"uiPreferences": preferences}, user_id=user_id)
            return jsonify(preferences=display_preferences(state))
        except ValueError as error:
            return jsonify(error=str(error)), 400

    @app.get("/api/state")
    def state_read():
        viewer_id = logged_in()["user_id"]
        user_id = request.args.get("user") or viewer_id
        try:
            with database.transaction() as connection:
                account = database.account(connection, user_id, lock=False)
                state = validate(json.loads(account["state"])) if account["state"] else None
        except ValueError:
            abort(404, description="账户不存在")
        symbols = list(dict.fromkeys(state["watchlist"] + [p["ticker"] for p in state["positions"]])) if state else []
        try:
            snapshots = database.get_cached_quotes(symbols)
        except (PoolTimeout, psycopg.OperationalError) as error:
            failure('database', 'quote_bootstrap_cache', error=error)
            snapshots = {}
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

    @app.get("/api/home")
    def home_data():
        from backend.services.home import calendar_snapshot, index_snapshot
        symbol = request.args.get("symbol")
        if symbol:
            try:
                if symbol not in {'^GSPC', '^IXIC', '^DJI'}:
                    raise ValueError('未知指数')
                return refresh_jobs.response('home:' + symbol, lambda publish: index_snapshot(symbol),
                    60, lambda value: value.get('index', {}).get('price') is not None,
                    stream=request.args.get('stream') == '1')
            except ValueError as error:
                return jsonify(error=str(error)), 400
        return jsonify(calendar_snapshot())

    @app.get("/api/home/sectors/<symbol>")
    def home_sector(symbol):
        from backend.services.home import SECTORS
        from backend.services.sectors import snapshot as sector_snapshot
        if symbol not in {item[0] for item in SECTORS}:
            return jsonify(error='未知板块 ETF'), 400
        return refresh_jobs.response('sector:3y:' + symbol, lambda publish: sector_snapshot(symbol, database, publish),
            60, lambda value: value.get('sector', {}).get('price') is not None
                and not value.get('sector', {}).get('error'),
            stream=request.args.get('stream') == '1', force=request.args.get('refresh') == '1')

    @app.get("/api/macro/<kind>")
    def macro_data(kind):
        if kind == "fed":
            from backend.providers.polymarket import snapshot as fed_snapshot
            return jsonify(fed_snapshot())
        from backend.services.macro import snapshot
        refresh = request.args.get('refresh') == '1'
        if kind not in {"jobs", "pce", "dxy", "treasury"}:
            abort(404)
        return refresh_jobs.response('macro:' + kind, lambda publish: snapshot(kind, force=refresh),
            3600, lambda value: any(metric.get('latest') for metric in value.get('metrics', [])),
            stream=request.args.get('stream') == '1', force=request.args.get('refresh') == '1')

    @app.get("/api/whales/<kind>")
    def whale_data(kind):
        from backend.services.whales import FUNDS, snapshot
        if kind not in FUNDS:
            abort(404)
        return refresh_jobs.response('whales:v5:' + kind, lambda publish: snapshot(kind, on_update=publish),
            3600, lambda value: value.get('totals_verified') is True and bool(value.get('holdings')) and value.get('previous_status') != 'failed',
            stream=request.args.get('stream') == '1', force=request.args.get('refresh') == '1')

    def own_news_symbols():
        raw = require_owner().get('news_state')
        state = validate(json.loads(raw)) if raw else None
        return state["watchlist"] if state else []

    @app.get("/api/news")
    def news_list():
        symbols = own_news_symbols()
        try:
            snapshots = database.get_cached_news(symbols) if request.args.get('cached') == '1' else {}
        except (PoolTimeout, psycopg.OperationalError) as error:
            failure('database', 'news_bootstrap_cache', error=error)
            snapshots = {}
        return jsonify(tickers=symbols, snapshots=snapshots)

    @app.get("/api/news/<symbol>/<kind>")
    def news_data(symbol, kind):
        symbol = symbol.upper()
        if kind not in {"sec", "calls"} or not SYMBOL.fullmatch(symbol):
            abort(404)
        if symbol not in own_news_symbols():
            abort(403, description="仅支持自己的观察列表")
        from backend.services.news import snapshot
        return refresh_jobs.response('news:v1:' + kind + ':' + symbol,
            lambda publish: snapshot(symbol, kind), 3600,
            lambda value: isinstance(value.get('items'), list) and not value.get('errors'),
            stream=request.args.get('stream') == '1', force=request.args.get('refresh') == '1')

    @app.get("/api/security/<symbol>")
    def quote(symbol: str):
        symbol = symbol.upper()
        if not SYMBOL.fullmatch(symbol):
            abort(400, description="无效 ticker")
        refresh = request.args.get("refresh") == "1"
        return refresh_jobs.response('security:' + symbol,
            lambda publish: security(symbol, refresh, store=database, on_update=publish),
            60, lambda value: value.get('metrics', {}).get('price', {}).get('value') is not None,
            persist=False, stream=request.args.get('stream') == '1', force=request.args.get('refresh') == '1')

    @app.get("/")
    @app.get("/index.html")
    def dashboard():
        if not logged_in():
            return redirect("/login")
        return send_from_directory(ROOT / "frontend", STATIC_ASSETS["index.html"])

    @app.get("/login")
    def login_page():
        if logged_in() and request.args.get("frontend") != "1":
            return redirect("/")
        return send_from_directory(ROOT / "frontend", STATIC_ASSETS["login.html"])

    @app.get("/<path:filename>")
    def static_file(filename: str):
        if filename not in {"style.css", "app.js", "positions.js", "auth-client.js", "login.js", "cache.js", "home.js", "macro.js", "whales.js", "dropdowns.js", "motion.js", "whale-analysis.js", "ticker-search.js", "symbol-directory.json", "news.js", "notifications.js", "preferences.js", "watchlist-order.js"}:
            abort(404)
        return send_from_directory(ROOT / "frontend", STATIC_ASSETS[filename])

    return app
