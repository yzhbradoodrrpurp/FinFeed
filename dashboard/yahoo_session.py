"""Optional yfinance login session; credentials stay in the server environment."""
import os
import threading

import yfinance as yf

_lock = threading.Lock()
_status = None


def mode():
    # Anonymous sessions get their own cookie/crumb on this host. Importing a
    # browser login is optional and must not silently change provider access.
    return "login" if os.environ.get("YAHOO_SESSION_MODE", "anonymous").lower() == "login" else "anonymous"


def initialize():
    """Install once per worker, without leaking cookies or exception messages.

    Called under the provider request semaphore. A failed login check does not
    block chart/fundamental requests, and is not retried every minute.
    """
    global _status
    with _lock:
        if _status is not None:
            return dict(_status)
        cookie_t = os.environ.get("YAHOO_COOKIE_T")
        cookie_y = os.environ.get("YAHOO_COOKIE_Y")
        _status = {"mode": mode(), "verified": False, "error": None}
        if mode() == "anonymous":
            return dict(_status)
        if not cookie_t or not cookie_y:
            _status["error"] = "Yahoo 登录配置不完整，需要同时设置 T 和 Y Cookie"
        elif cookie_t and cookie_y:
            try:
                _status["verified"] = bool(yf.Auth().set_login_cookies(cookie_t, cookie_y))
                if not _status["verified"]:
                    _status["error"] = "Yahoo 登录状态未确认，Cookie 可能过期或验证接口不可达"
            except Exception:
                # Provider exceptions can contain authenticated request URLs.
                _status["error"] = "Yahoo 登录验证失败，保留可用行情并明确标注缺失"
        return dict(_status)
