"""One bounded anonymous-session probe, isolated from the worker singleton."""
from failure_log import failure
import time
import json
import os
import subprocess
import sys
from pathlib import Path

REVISION = 1


def isolated_probe():
    env = {key: value for key, value in os.environ.items()
           if key not in {"YAHOO_COOKIE_T", "YAHOO_COOKIE_Y", "DATABASE_URL", "ALPHAVANTAGE_API_KEY"}}
    started = time.monotonic()
    try:
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child"],
                                env=env, capture_output=True, text=True, timeout=75)
        if result.returncode != 0:
            failure('yahoo', 'isolated_probe', reason='probe process failed', started=started, return_code=result.returncode)
            return {"revision": REVISION, "error": "probe_process_failed"}
        output = json.loads(result.stdout)
        for operation, entry in output.items():
            if isinstance(entry, dict) and (entry.get('error') or entry.get('ok') is False):
                failure('yahoo', operation, reason=entry.get('error') or 'probe failed',
                        provider_status=entry.get('status'), category=entry.get('category'))
        return output
    except (subprocess.TimeoutExpired, ValueError) as exc:
        failure("yahoo", "isolated_probe", error=exc, started=started)
        return {"revision": REVISION, "error": "probe_timeout_or_invalid_result"}


def main():
    import tempfile
    import yfinance as yf
    from yahoo_diagnostic import provider_error_category
    from yahoo_session import configure_transport, proxy_enabled
    from datetime import datetime, timezone
    with tempfile.TemporaryDirectory(prefix="finfeed-probe-") as cache:
        yf.set_tz_cache_location(cache)
        yf.config.debug.hide_exceptions = False
        yf.config.network.retries = 0
        configure_transport()
        item = yf.Ticker("GOOG")
        provider = item._data
        out = {"revision": REVISION, "checked_at": datetime.now(timezone.utc).isoformat(),
               "proxy_enabled": proxy_enabled(),
               "proxy_env_present": any(os.environ.get(k) for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"))}
        params = {"modules": "earningsTrend", "corsDomain": "finance.yahoo.com", "formatted": "false", "symbol": "GOOG"}

        def request(host):
            try:
                payload = provider.get_raw_json(f"https://{host}.finance.yahoo.com/v10/finance/quoteSummary/GOOG", params=params, timeout=30)
                entries = payload["quoteSummary"]["result"][0]["earningsTrend"]["trend"]
                return {"ok": True, "quarters": [{"period": x.get("period"), "endDate": x.get("endDate"),
                    "eps": (x.get("earningsEstimate") or {}).get("avg")} for x in entries if x.get("period") in ("0q", "+1q")]}
            except Exception as exc:
                return {"ok": False, "error": type(exc).__name__, "status": getattr(getattr(exc, "response", None), "status_code", None), "category": provider_error_category(exc)}

        out["query2_isolated"] = request("query2")
        crumb = provider._crumb
        out["crumb_present"] = bool(crumb)
        out["crumb_looks_like_error"] = bool(crumb and (str(crumb).lstrip().startswith(("{", "<")) or "Too Many Requests" in str(crumb)))
        if out["query2_isolated"].get("error") != "YFRateLimitError":
            out["query1_isolated"] = request("query1")
        # Refresh against the same host as the failing query. No foreign cookie
        # or crumb is imported, and no credentials are returned by this probe.
        if not out["query2_isolated"].get("ok") and out["query2_isolated"].get("status") == 401:
            try:
                response = provider._session.get("https://query2.finance.yahoo.com/v1/test/getcrumb", timeout=30)
                text = response.text.strip()
                valid = response.status_code == 200 and 0 < len(text) < 128 and not any(c.isspace() for c in text) and not text.startswith(("{", "<"))
                out["same_host_crumb"] = {"status": response.status_code, "valid_shape": valid}
                if valid:
                    provider._crumb = text
                    out["query2_same_host_crumb"] = request("query2")
            except Exception as exc:
                out["same_host_crumb"] = {"error": type(exc).__name__}
        print(json.dumps(out))


if __name__ == "__main__":
    main()
