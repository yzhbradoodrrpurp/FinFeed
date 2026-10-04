"""Bounded provider diagnostics: public financial values only, no URLs/cookies."""
from datetime import datetime, timezone, timedelta
from urllib.parse import parse_qs, urlsplit

import yfinance as yf
from yfinance import _http
from importlib.metadata import version


def provider_error_category(exc):
    """Return only known public error categories, never arbitrary response text."""
    try:
        body = exc.response.json()
        error = (body.get("finance") or body.get("quoteSummary") or {}).get("error") or {}
        description = str(error.get("description", "")).lower()
    except Exception:
        return None
    for phrase, category in (("invalid crumb", "invalid_crumb"),
                             ("invalid cookie", "invalid_cookie"),
                             ("unable to access", "access_denied"),
                             ("too many requests", "rate_limited")):
        if phrase in description:
            return category
    return "unauthorized" if error.get("code") == "Unauthorized" else None


def debt_rows(payload):
    return [
        {"period": entry.get("asOfDate"), "value": (entry.get("reportedValue") or {}).get("raw")}
        for block in payload for entry in block.get("quarterlyTotalDebt", [])
    ]


def balance_with_diagnostics(item, output):
    """Observe the pinned adapter before reshaping; one narrow control request.

    This only runs on GOOG's daily financial refresh. Never store request URLs,
    provider error text, crumbs, or headers in the diagnostic result.
    """
    financials = item._fundamentals.financials
    original = financials._fetch_fundamentals_payload
    output.update(version=yf.__version__, checked_at=datetime.now(timezone.utc).isoformat(), batches=[],
                  http_backend="curl_cffi" if _http.HAS_CURL_CFFI else "requests",
                  http_version=version("curl_cffi" if _http.HAS_CURL_CFFI else "requests"))

    def observe(url):
        params = parse_qs(urlsplit(url).query)
        batch = {"type_count": len(params.get("type", [""])[0].split(",")),
                 "period1": params.get("period1", [None])[0],
                 "period2": params.get("period2", [None])[0]}
        output["batches"].append(batch)
        payload = original(url)
        batch.update(result_count=len(payload), debt=debt_rows(payload))
        return payload

    financials._fetch_fundamentals_payload = observe
    try:
        frame = item.get_balance_sheet(freq="quarterly")
    finally:
        financials._fetch_fundamentals_payload = original
    output["parsed_debt"] = []
    if "TotalDebt" in frame.index:
        output["parsed_debt"] = [{"period": col.date().isoformat(), "value": float(value)}
                                 for col, value in frame.loc["TotalDebt"].dropna().items()]
    # Same provider/session and UTC time window, but a single requested field.
    end = (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    start = datetime(2016, 12, 31, tzinfo=timezone.utc)
    url = (f"https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{item.ticker}"
           f"?symbol={item.ticker}&type=quarterlyTotalDebt&period1={int(start.timestamp())}&period2={int(end.timestamp())}")
    try:
        output["narrow_debt"] = debt_rows(original(url))
    except Exception as exc:
        output["narrow_error"] = type(exc).__name__
    return frame
