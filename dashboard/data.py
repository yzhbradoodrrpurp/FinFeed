"""Yahoo Finance personal-use adapter with dated provenance and conservative gaps."""
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import yfinance as yf

from metrics import number, prior_quarter_period, trailing_pe, volume_metrics, qoq

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / ".cache"
CACHE.mkdir(exist_ok=True)
yf.set_tz_cache_location(str(CACHE / "yfinance"))
LIMIT = threading.Semaphore(2)
LOCKS = {}
LOCK_GUARD = threading.Lock()
TTL = 900
SCHEMA_VERSION = 3


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


def fetch_security(symbol):
    started = now()
    item = yf.Ticker(symbol)
    errors = []
    def load(label, action, default):
        try:
            return action()
        except Exception as exc:
            errors.append(f"{label}读取失败：{type(exc).__name__}")
            return default
    info = load("证券信息", item.get_info, {}) or {}
    history = load("日线", lambda: item.history(period="1y", auto_adjust=False, actions=True,
                                              raise_errors=True, timeout=15), None)
    quote_type = info.get("quoteType", "UNKNOWN")
    currency = info.get("currency")
    fin_currency = info.get("financialCurrency") or currency
    exchange_tz = info.get("exchangeTimezoneName") or "America/New_York"
    quote_url = f"https://finance.yahoo.com/quote/{quote(symbol, safe='')}/"
    financial_url = quote_url + "financials/"
    balance_url = quote_url + "balance-sheet/"
    cash_url = quote_url + "cash-flow/"
    analysis_url = quote_url + "analysis/"
    result = {"ticker": symbol, "name": info.get("longName") or info.get("shortName") or symbol,
              "quote_type": quote_type, "currency": currency, "financial_currency": fin_currency,
              "exchange": info.get("fullExchangeName") or info.get("exchange"),
              "exchange_timezone": exchange_tz, "fetched_at": started, "errors": errors,
              "sources": {"quote": quote_url, "financials": financial_url, "balance": balance_url,
                          "cashflow": cash_url, "estimates": analysis_url,
                          "sec": f"https://www.sec.gov/edgar/search/#/q={quote(symbol)}"},
              "metrics": {}, "series": {}, "schema_version": SCHEMA_VERSION}
    m = result["metrics"]
    price = number(info.get("regularMarketPrice"))
    quote_timestamp = number(info.get("regularMarketTime"))
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
    metadata = load("交易时段", item.get_history_metadata, {}) or {}
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
        for key in ["eps_q0", "eps_q1", "forward_eps_q0", "pe_ltm", "pe_ntm", "revenue_q0", "revenue_qoq_q0", "revenue_qoq_q1", "debt_q0", "debt_qoq_q0", "debt_qoq_q1", "fcf_q0", "fcf_qoq_q0", "fcf_qoq_q1"]:
            m[key] = empty_metric(reason)
        if quote_type == "ETF":
            m["market_cap"] = empty_metric("ETF 公司市值不适用；未用资产规模替代")
        return result
    income = load("利润表", lambda: item.get_income_stmt(freq="quarterly"), None)
    balance = load("资产负债表", lambda: item.get_balance_sheet(freq="quarterly"), None)
    cashflow = load("现金流量表", lambda: item.get_cashflow(freq="quarterly"), None)
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
    # Provider TTM EPS avoids blindly adding EPS across stock-split bases.
    pe, reason = trailing_pe(price, info.get("trailingEps"))
    m["pe_ltm"] = field(pe, quote_date, "最近价格 / Yahoo trailingEps；供应商 TTM EPS，不保证等于本表四季 GAAP EPS 之和", quote_url,
                        inputs={"price": price, "trailing_eps": number(info.get("trailingEps"))})
    m["pe_ltm"]["reason"] = reason
    if currency != fin_currency:
        m["pe_ltm"] = empty_metric("报价与 EPS 币种不同，需要同日期汇率转换后才能计算", source=quote_url,
                                    inputs={"price_currency": currency, "eps_currency": fin_currency})
    estimates = load("分析师预期", item.get_earnings_estimate, None)
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
        m["forward_eps_q0"] = empty_metric("免费数据源未返回季度分析师预期", source=analysis_url)
    m["pe_ntm"] = empty_metric("缺少未来连续 4 个财季的同口径 EPS 预期；未用年度 forwardPE 代替", source=analysis_url,
                                basis="NTM P/E = 价格 / 未来连续四个财季 EPS 预期之和")
    return result


def security(symbol, refresh=False):
    with LOCK_GUARD:
        lock = LOCKS.setdefault(symbol, threading.Lock())
    with lock:
        path = CACHE / f"{symbol}.json"
        saved = None
        if path.exists():
            try:
                saved = json.loads(path.read_text())
            except (ValueError, OSError):
                pass
        age = time.time() - path.stat().st_mtime if saved else float("inf")
        if saved and saved.get("schema_version") != SCHEMA_VERSION:
            saved = None
            age = float("inf")
        # Explicit minute refreshes bypass the 15-minute passive cache. A short
        # debounce coalesces duplicate requests from tabs or rapid manual clicks.
        if saved and (age < 5 or (age < TTL and not refresh)):
            return {**saved, "cached": True, "cache_age_seconds": round(age)}
        try:
            with LIMIT:
                result = fetch_security(symbol)
            if result["metrics"]["price"]["value"] is None and saved:
                return {**saved, "cached": True, "stale": True, "refresh_error": "行情读取失败，保留上次快照", "cache_age_seconds": round(age)}
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False))
            tmp.replace(path)
            return {**result, "cached": False}
        except Exception as exc:
            if saved:
                return {**saved, "cached": True, "stale": True, "refresh_error": type(exc).__name__, "cache_age_seconds": round(age)}
            return {"ticker": symbol, "name": symbol, "fetched_at": now(), "metrics": {}, "errors": [f"数据暂不可用：{type(exc).__name__}"], "sources": {}}
