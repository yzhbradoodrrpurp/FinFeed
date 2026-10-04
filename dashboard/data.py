"""Yahoo Finance personal-use adapter with dated provenance and conservative gaps."""
from copy import deepcopy
import threading
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import yfinance as yf
import yahoo_session
from yahoo_diagnostic import balance_with_diagnostics, provider_error_category
from yahoo_probe import isolated_probe, REVISION as PROBE_REVISION
from alpha import estimate_data, next_four_eps, SOURCE as ALPHA_SOURCE

from metrics import number, prior_quarter_period, trailing_pe, volume_metrics, qoq

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / ".cache"
CACHE.mkdir(exist_ok=True)
# A fresh anonymous cookie store per process avoids reusing a rejected
# cookie/crumb pair from a previous deployment. Do not log these credentials.
YAHOO_CACHE = tempfile.TemporaryDirectory(prefix="finfeed-yahoo-")
yf.set_tz_cache_location(YAHOO_CACHE.name)
yf.config.debug.hide_exceptions = False
yf.config.network.retries = 1
yahoo_session.configure_transport()
# yfinance protects cookie/crumb setup with its own lock. Bound concurrent
# network work; keep a Gunicorn thread available for state/auth requests.
LIMIT = threading.Semaphore(3)
LOCKS = {}
LOCK_GUARD = threading.Lock()
TTL = 60
SCHEMA_VERSION = 7


def epoch(value):
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).timestamp()
        except ValueError:
            return None
    return number(value)


def now():
    return datetime.now(timezone.utc).isoformat()


def empty_metric(reason="数据源未提供", **extra):
    return {"value": None, "reason": reason, **extra}


def field(value, period=None, basis=None, source=None, **extra):
    return {"value": number(value), "period": period, "basis": basis, "source": source,
            "reason": None if number(value) is not None else "数据源未提供", **extra}


def frame_values(frame, labels, currency, source_url):
    output = {}
    if frame is None or frame.empty:
        return output
    today = datetime.now(timezone.utc).date()
    for col in frame.columns:
        period = col.date().isoformat()
        if col.date() > today:
            continue
        for label in labels:
            if label in frame.index:
                value = number(frame.at[label, col])
                if value is not None:
                    output[period] = field(value, period, label, source_url, currency=currency)
                    break
    return output


def growth(series, period):
    if not period or period not in series:
        return empty_metric("缺少该财季数据", period=period)
    old = prior_quarter_period(period, series)
    a = series[period]
    b = series.get(old, {})
    value, reason = qoq(a["value"], b.get("value"))
    return {"value": value, "reason": reason, "period": period, "comparison_period": old,
            "basis": "季度环比 = 本期 / 上一财季 − 1；上一财季必须大于零", "source": a["source"],
            "inputs": {"current": a["value"], "previous_quarter": b.get("value")}}


FINANCIAL_KEYS = ("eps_q0", "eps_q1", "forward_eps_q0", "revenue_q0", "revenue_qoq_q0", "revenue_qoq_q1", "debt_q0", "debt_qoq_q0", "debt_qoq_q1", "fcf_q0", "fcf_qoq_q0", "fcf_qoq_q1", "pe_ntm")


def financial_day(timestamp):
    try:
        return datetime.fromisoformat(timestamp).astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
    except (ValueError, TypeError):
        return None


def financial_due(saved, timestamp):
    return (not saved or saved.get("yahoo_session", {}).get("mode", "anonymous") != yahoo_session.mode()
            or saved.get("yahoo_session", {}).get("proxy_enabled", False) != yahoo_session.proxy_enabled()
            or financial_day(saved.get("financial_checked_at") or saved.get("fetched_at")) != financial_day(timestamp))


def reuse_financial(result, saved):
    for key in FINANCIAL_KEYS:
        if key in saved.get("metrics", {}):
            result["metrics"][key] = deepcopy(saved["metrics"][key])
    for key in ("series", "quarter_0", "quarter_1", "financial_currency", "financial_fetched_at", "trailing_eps", "financial_stale", "financial_errors", "estimates_fetched_at", "reported_shares", "financial_diagnostics", "provider_probe"):
        if key in saved:
            result[key] = deepcopy(saved[key])
    result.setdefault("financial_fetched_at", saved.get("fetched_at"))
    if "trailing_eps" not in result:
        result["trailing_eps"] = saved.get("metrics", {}).get("pe_ltm", {}).get("inputs", {}).get("trailing_eps")


def next_forecast(result, estimate_store=None):
    """Match the next quarter after the latest disclosed quarter, never skip gaps."""
    q0 = result.get("quarter_0")
    if not q0:
        return empty_metric("最近已披露财季未知，无法确定下一财季")
    def adjacent(period):
        try:
            return 65 <= (datetime.fromisoformat(period) - datetime.fromisoformat(q0)).days <= 120
        except (ValueError, TypeError):
            return False
    yahoo = result["metrics"].get("forward_eps_q0", {})
    if yahoo.get("value") is not None and adjacent(yahoo.get("period")):
        forecast = deepcopy(yahoo)
        forecast["basis"] = "Yahoo：紧接最近已披露财季的分析师 EPS 均值；可能为调整后口径"
        return forecast
    if result.get("currency") == "USD" and result.get("financial_currency") == "USD":
        alpha = estimate_data(result["ticker"], result["fetched_at"], store=estimate_store)
        if alpha:
            result["estimates_fetched_at"] = alpha.get("fetched_at")
            result["sources"]["estimates_alpha"] = ALPHA_SOURCE
            candidates = sorted((row for row in (alpha.get("data") or {}).get("estimates", []) if row.get("horizon") == "fiscal quarter" and adjacent(row.get("date"))), key=lambda row: row["date"])
            for row in candidates:
                value = number(row.get("eps_estimate_average"))
                if value is not None:
                    return field(value, row["date"], "Alpha Vantage：紧接最近已披露财季的分析师 EPS 均值；预期不保证为 GAAP", ALPHA_SOURCE, currency="USD", analysts=number(row.get("eps_estimate_analyst_count")), estimate_fetched_at=alpha.get("fetched_at"), estimate_stale=bool(alpha.get("error")))
    reason = "Yahoo 未返回紧接最近已披露财季的预测 EPS"
    if result.get("currency") == "USD" and result.get("financial_currency") == "USD":
        reason += "；" + (alpha.get("error") or "备用来源未覆盖该财季" if alpha else "备用预测来源未配置")
    return empty_metric(reason, source=ALPHA_SOURCE)


def quarterly_pe(result, eps, forecast=False):
    price = result["metrics"].get("price", {}).get("value")
    value = number(eps.get("value"))
    annualized = value * 4 if value is not None else None
    pe, reason = trailing_pe(price, annualized)
    if eps.get("currency") != result.get("currency"):
        pe, reason = None, "报价与季度 EPS 币种不同，未自动换汇"
    if value is None:
        pe, reason = None, eps.get("reason") or "季度 EPS 缺失"
    return field(pe, eps.get("period"), "季度年化 " + ("Forward P/E" if forecast else "P/E") + " = 最近价格 /（单季 EPS × 4）；简单年化，不代表全年盈利预测；实际与预测 EPS 口径可能不同", eps.get("source"),
                 reason=reason, inputs={"price": price, "quarter_eps": value, "annualization_factor": 4, "annualized_eps": annualized}, quote_date=result.get("quote_date"), estimate_stale=eps.get("estimate_stale", False), estimate_fetched_at=eps.get("estimate_fetched_at"))


def revalue(result, estimate_store=None):
    m = result["metrics"]
    shares = result.get("reported_shares", {})
    if m.get("market_cap", {}).get("value") is None and shares.get("value") and m.get("price", {}).get("value"):
        m["market_cap"] = field(m["price"]["value"] * shares["value"], result.get("quote_date"),
                                "估算市值 = 最近价格 × 最近财报期末普通股在外股数；股数并非实时",
                                shares.get("source"), currency=result.get("currency"),
                                inputs={"price": m["price"]["value"], "shares": shares["value"], "shares_period": shares.get("period")})
    m["forward_eps_next"] = next_forecast(result, estimate_store)
    m["pe_quarter"] = quarterly_pe(result, m.get("eps_q0", {}))
    m["pe_forward_quarter"] = quarterly_pe(result, m["forward_eps_next"], forecast=True)
    result["valuation_at"] = result["fetched_at"]
    return result


def fetch_security(symbol, saved=None, estimate_store=None):
    started = now()
    session_status = yahoo_session.initialize()
    item = yf.Ticker(symbol)
    errors = []
    if session_status["error"]:
        errors.append(session_status["error"])
    def load(label, action, default):
        try:
            return action()
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            category = provider_error_category(exc)
            errors.append(f"{label}读取失败：{type(exc).__name__}" + (f" HTTP {status}" if status else "")
                          + (f" ({category})" if category else ""))
            return default
    info_day = financial_day(started)
    if saved and not financial_due(saved, started) and saved.get("info_checked_day") == info_day:
        info = deepcopy(saved.get("security_info") or {})
    else:
        info = load("证券信息", item.get_info, {}) or {}
    security_info = deepcopy(info)
    # 52-week bounds come from chart metadata. Volume needs only 11 daily bars;
    # avoid downloading a whole year on every minute refresh.
    history = load("日线", lambda: item.history(period="1mo", auto_adjust=False, actions=True,
                                              raise_errors=True, timeout=15), None)
    # quoteSummary can return {} after logging HTTP 401 without raising.
    # Chart metadata uses an independent endpoint and still identifies securities.
    info_available = bool(info.get("quoteType"))
    if not info_available:
        errors.append("Yahoo 证券信息接口未返回有效数据；使用日线元数据，部分指标可能缺失")
    metadata = load("交易时段", item.get_history_metadata, {}) or {}
    chart_info = {**metadata, "quoteType": metadata.get("instrumentType")}
    info = {**chart_info, **{key: value for key, value in info.items() if value is not None}}
    # The chart quote is refreshed each minute even when profile data is daily.
    for key in ("regularMarketPrice", "regularMarketTime", "fiftyTwoWeekHigh", "fiftyTwoWeekLow"):
        if metadata.get(key) is not None:
            info[key] = metadata[key]
    if info.get("sharesOutstanding") and info.get("regularMarketPrice"):
        info["marketCap"] = info["sharesOutstanding"] * info["regularMarketPrice"]
    quote_type = info.get("quoteType") or (saved or {}).get("quote_type", "UNKNOWN")
    currency = info.get("currency") or (saved or {}).get("currency")
    fin_currency = info.get("financialCurrency") or (saved or {}).get("financial_currency") or currency
    exchange_tz = info.get("exchangeTimezoneName") or "America/New_York"
    quote_url = f"https://finance.yahoo.com/quote/{quote(symbol, safe='')}/"
    financial_url = quote_url + "financials/"
    balance_url = quote_url + "balance-sheet/"
    cash_url = quote_url + "cash-flow/"
    analysis_url = quote_url + "analysis/"
    result = {"ticker": symbol, "name": info.get("longName") or info.get("shortName") or (saved or {}).get("name") or symbol,
              "security_info": security_info, "info_checked_day": info_day, "yahoo_session": session_status,
              "quote_type": quote_type, "currency": currency, "financial_currency": fin_currency,
              "exchange": info.get("fullExchangeName") or info.get("exchange"),
              "exchange_timezone": exchange_tz, "fetched_at": started, "errors": errors,
              "sources": {"quote": quote_url, "financials": financial_url, "balance": balance_url,
                          "cashflow": cash_url, "estimates": analysis_url,
                          "sec": f"https://www.sec.gov/edgar/search/#/q={quote(symbol)}"},
              "metrics": {}, "series": {}, "schema_version": SCHEMA_VERSION}
    m = result["metrics"]
    price = number(info.get("regularMarketPrice"))
    quote_timestamp = epoch(info.get("regularMarketTime"))
    quote_time = datetime.fromtimestamp(quote_timestamp, timezone.utc) if quote_timestamp else None
    quote_date = quote_time.astimezone(ZoneInfo(exchange_tz)).date().isoformat() if quote_time else None
    if price is None and history is not None and not history.empty:
        price = number(history.iloc[-1]["Close"])
        quote_date = history.index[-1].date().isoformat()
    result["quote_at"] = quote_time.isoformat() if quote_time else None
    result["quote_date"] = quote_date
    result["market_state"] = info.get("marketState")
    result["delay_minutes"] = info.get("exchangeDataDelayedBy")
    result["filing_date"] = None
    m["market_cap"] = field(info.get("marketCap"), quote_date, "Yahoo 公司市值；ETF 不用 AUM 代替", quote_url, currency=currency)
    m["price"] = field(price, quote_date, "常规交易时段最近成交价；不合并盘后价", quote_url, currency=currency)
    m["high_52w"] = field(info.get("fiftyTwoWeekHigh"), quote_date, "Yahoo 52 周价格高点", quote_url, currency=currency)
    m["low_52w"] = field(info.get("fiftyTwoWeekLow"), quote_date, "Yahoo 52 周价格低点", quote_url, currency=currency)
    rows = []
    if history is not None and not history.empty:
        rows = [(idx.date().isoformat(), value) for idx, value in history["Volume"].items()]
    # The daily bar is complete only after the provider's regular-session close.
    complete = False
    session = metadata.get("currentTradingPeriod", {}).get("regular", {})
    session_end = epoch(session.get("end"))
    if quote_date and session_end:
        session_date = datetime.fromtimestamp(session_end, timezone.utc).astimezone(ZoneInfo(exchange_tz)).date().isoformat()
        complete = quote_date < session_date or (quote_date == session_date and time.time() >= session_end)
    result["volume_complete"] = complete
    if quote_date:
        avg, ratio, reason, inputs = volume_metrics(rows, quote_date, complete)
        m["avg_volume_10"] = field(avg, quote_date, "成交股数；不含比较日，取此前 10 个完整交易日均值", quote_url,
                                  inputs=[{"date": d, "volume": v} for d, v in inputs])
        m["relative_volume_10"] = field(ratio, quote_date, "比较日完整成交量 / 此前 10 个完整交易日均量", quote_url)
        m["relative_volume_10"]["reason"] = reason
        m["relative_volume_10"]["inputs"] = {"volume": next((number(v) for d, v in rows if d == quote_date), None), "average": avg}
    else:
        m["avg_volume_10"] = empty_metric("无法取得报价对应交易日")
        m["relative_volume_10"] = empty_metric("无法取得报价对应交易日")
    equity = quote_type == "EQUITY"
    if not equity:
        reason = "该证券不是公司股票，财务与 EPS 指标不适用" if quote_type != "UNKNOWN" else "证券未识别或数据源暂不可用"
        for key in ["eps_q0", "eps_q1", "forward_eps_q0", "pe_ltm", "pe_ntm", "pe_quarter", "pe_forward_quarter", "forward_eps_next", "revenue_q0", "revenue_qoq_q0", "revenue_qoq_q1", "debt_q0", "debt_qoq_q0", "debt_qoq_q1", "fcf_q0", "fcf_qoq_q0", "fcf_qoq_q1"]:
            m[key] = empty_metric(reason)
        if quote_type == "ETF":
            m["market_cap"] = empty_metric("ETF 公司市值不适用；未用资产规模替代")
        return result
    if not info_available and saved:
        for key in ("market_cap", "high_52w", "low_52w"):
            previous = saved.get("metrics", {}).get(key, {})
            if m[key].get("value") is None and previous.get("value") is not None:
                m[key] = deepcopy(previous)
                m[key]["stale"] = True
                m[key]["reason"] = "证券信息更新失败，保留上次成功值"
    if m["market_cap"].get("value") is None:
        # Shares endpoint is independent of quoteSummary; refresh at most daily.
        shares = (saved or {}).get("shares_outstanding")
        shares_period = (saved or {}).get("shares_period")
        if financial_due(saved, started):
            share_frame = load("流通股数", lambda: item.get_shares_full(start=(datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()), None)
            if share_frame is not None and not share_frame.empty:
                shares = number(share_frame.iloc[-1])
                shares_period = share_frame.index[-1].date().isoformat()
        result["shares_outstanding"], result["shares_period"] = shares, shares_period
        if shares and price:
            m["market_cap"] = field(price * shares, quote_date, "市值 = 最近价格 × Yahoo 最近披露在外股数；股数可能滞后", quote_url,
                                    currency=currency, inputs={"price": price, "shares": shares, "shares_period": shares_period})
    if not financial_due(saved, started):
        reuse_financial(result, saved)
        result["financial_checked_at"] = saved.get("financial_checked_at") or saved.get("fetched_at")
        return revalue(result, estimate_store)
    financial_error_start = len(errors)
    result["financial_checked_at"] = started
    result["financial_fetched_at"] = started
    result["trailing_eps"] = number(info.get("trailingEps"))
    income = load("利润表", lambda: item.get_income_stmt(freq="quarterly"), None)
    if symbol == "GOOG":
        result["financial_diagnostics"] = {}
        balance = load("资产负债表", lambda: balance_with_diagnostics(item, result["financial_diagnostics"]), None)
    else:
        balance = load("资产负债表", lambda: item.get_balance_sheet(freq="quarterly"), None)
    cashflow = load("现金流量表", lambda: item.get_cashflow(freq="quarterly"), None)
    for label, frame in (("利润表", income), ("资产负债表", balance), ("现金流量表", cashflow)):
        if frame is None or frame.empty:
            errors.append(f"{label}未返回数据")
    # Use disclosed ordinary shares only for US quote/financial currency pairs;
    # never substitute diluted weighted-average EPS shares for outstanding shares.
    if currency == "USD" and fin_currency == "USD" and info.get("exchangeName") in ("NMS", "NYQ", "NGM", "NCM", "ASE", "PCX"):
        reported_shares = frame_values(balance, ["OrdinarySharesNumber"], None, balance_url)
        if reported_shares:
            result["reported_shares"] = reported_shares[max(reported_shares)]
    eps = frame_values(income, ["DilutedEPS"], fin_currency, financial_url)
    revenue = frame_values(income, ["TotalRevenue"], fin_currency, financial_url)
    debt = frame_values(balance, ["TotalDebt"], fin_currency, balance_url)
    ocf = frame_values(cashflow, ["OperatingCashFlow"], fin_currency, cash_url)
    capex = frame_values(cashflow, ["CapitalExpenditure"], fin_currency, cash_url)
    fcf = {}
    for period in ocf.keys() & capex.keys():
        fcf[period] = field(ocf[period]["value"] - abs(capex[period]["value"]), period,
                            "FCF = 单季经营现金流 − 单季资本支出（支出取正数）；非 GAAP 指标", cash_url,
                            currency=fin_currency, inputs={"operating_cash_flow": ocf[period]["value"], "capital_expenditure": abs(capex[period]["value"])})
    periods = sorted(set(revenue) | set(eps), reverse=True)
    q0 = periods[0] if periods else None
    q1 = periods[1] if len(periods) > 1 else None
    if q0 and q1 and not 65 <= (datetime.fromisoformat(q0) - datetime.fromisoformat(q1)).days <= 120:
        q1 = None
    result["quarter_0"], result["quarter_1"] = q0, q1
    for key, series, period in [("eps_q0", eps, q0), ("eps_q1", eps, q1), ("revenue_q0", revenue, q0), ("debt_q0", debt, q0), ("fcf_q0", fcf, q0)]:
        m[key] = series.get(period, empty_metric("数据源未提供该财季值", period=period))
    for label, series in [("revenue", revenue), ("debt", debt), ("fcf", fcf)]:
        m[f"{label}_qoq_q0"] = growth(series, q0)
        m[f"{label}_qoq_q1"] = growth(series, q1)
    result["series"] = {"eps": eps, "revenue": revenue, "debt": debt, "fcf": fcf}
    # Forecast permission failures must not discard successfully fetched actual
    # statements (including historical quarters needed for growth rates).
    statement_errors = errors[financial_error_start:]
    estimates = load("分析师预期", item.get_earnings_estimate, None)
    if symbol == "GOOG":
        previous_probe = (saved or {}).get("provider_probe", {})
        if previous_probe.get("revision") == PROBE_REVISION:
            result["provider_probe"] = previous_probe
        elif any("invalid_crumb" in error for error in errors):
            result["provider_probe"] = isolated_probe()
    if estimates is not None and not estimates.empty and "0q" in estimates.index:
        row = estimates.loc["0q"]
        # The public estimate DataFrame omits the period end. Version-pinned
        # adapter reads the date from the already-fetched earningsTrend response.
        estimate_period = None
        if hasattr(item, "_analysis"):
            for entry in getattr(item._analysis, "_earnings_trend", None) or []:
                if entry.get("period") == "0q":
                    estimate_period = entry.get("endDate")
        m["forward_eps_q0"] = field(row.get("avg"), estimate_period, "Yahoo 0q 分析师平均 EPS 预期；可能为调整后口径，与 GAAP diluted EPS 不直接作 beat/miss 比较", analysis_url,
                                     currency=fin_currency, analysts=number(row.get("numberOfAnalysts")), estimate_label="供应商当前预测财季 0q")
    else:
        previous_forecast = (saved or {}).get("metrics", {}).get("forward_eps_q0", {})
        if previous_forecast.get("value") is not None:
            m["forward_eps_q0"] = deepcopy(previous_forecast)
            m["forward_eps_q0"]["estimate_stale"] = True
            m["forward_eps_q0"]["estimate_fetched_at"] = previous_forecast.get("estimate_fetched_at") or (saved or {}).get("financial_fetched_at")
        else:
            m["forward_eps_q0"] = empty_metric("免费数据源未返回季度分析师预期", source=analysis_url)
    m["pe_ntm"] = empty_metric("缺少未来连续 4 个财季的同口径 EPS 预期；未用年度 forwardPE 代替", source=analysis_url,
                                basis="NTM P/E = 价格 / 未来连续四个财季 EPS 预期之和")
    financial_errors = errors[financial_error_start:]
    if statement_errors and saved and saved.get("series"):
        reuse_financial(result, saved)
        result["financial_stale"] = True
        result["financial_errors"] = financial_errors
    else:
        result["financial_stale"] = bool(statement_errors)
        result["financial_errors"] = financial_errors
    return revalue(result, estimate_store)


def security(symbol, refresh=False, store=None):
    with LOCK_GUARD:
        lock = LOCKS.setdefault(symbol, threading.Lock())
    with lock:
        if store is None:
            raise ValueError("行情缓存需要私人数据库")
        stored = store.get_cache("quote:" + symbol)
        saved = stored[0] if stored else None
        age = time.time() - stored[1] if stored else float("inf")
        if saved and saved.get("schema_version") != SCHEMA_VERSION:
            saved = None
            age = float("inf")
        # Market requests refresh each minute; same-minute tabs share the cache.
        if saved and not financial_due(saved, now()) and (age < 5 or (age < TTL and not refresh)):
            return {**saved, "cached": True, "cache_age_seconds": round(age)}
        try:
            with LIMIT:
                result = fetch_security(symbol, saved, estimate_store=store)
            if result["metrics"]["price"]["value"] is None and saved:
                return {**saved, "cached": True, "stale": True, "refresh_error": "行情读取失败，保留上次快照", "cache_age_seconds": round(age)}
            store.set_cache("quote:" + symbol, result)
            return {**result, "cached": False}
        except Exception as exc:
            if saved:
                return {**saved, "cached": True, "stale": True, "refresh_error": type(exc).__name__, "cache_age_seconds": round(age)}
            return {"ticker": symbol, "name": symbol, "fetched_at": now(), "metrics": {}, "errors": [f"数据暂不可用：{type(exc).__name__}"], "sources": {}}
