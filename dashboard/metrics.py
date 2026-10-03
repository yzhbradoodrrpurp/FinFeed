"""Pure calculations; unknown values are never silently replaced with zero."""
import math
from datetime import date, timedelta


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def yoy(current, previous):
    current, previous = number(current), number(previous)
    if current is None or previous is None:
        return None, "缺少本期或上年同期数据"
    if previous <= 0:
        return None, "上年同期为零或负值，百分比增长不具可比性"
    return current / previous - 1, None


def prior_year_period(period, periods):
    target = date.fromisoformat(period) - timedelta(days=365)
    candidates = [p for p in periods if abs((date.fromisoformat(p) - target).days) <= 15]
    return min(candidates, key=lambda p: abs((date.fromisoformat(p) - target).days)) if candidates else None


def trailing_pe(price, eps):
    price, eps = number(price), number(eps)
    if price is None or eps is None:
        return None, "缺少价格或最近十二个月 EPS"
    if eps <= 0:
        return None, "最近十二个月 EPS 为零或负值，P/E 不适用"
    return price / eps, None


def volume_metrics(rows, quote_date, complete):
    """rows: chronological (ISO date, volume). Exclude the quote date itself."""
    previous = [(d, number(v)) for d, v in rows if d < quote_date]
    previous = [(d, v) for d, v in previous if v is not None][-10:]
    if len(previous) != 10:
        return None, None, "不足 10 个此前完整交易日", []
    avg = sum(v for _, v in previous) / 10
    current = next((number(v) for d, v in rows if d == quote_date), None)
    if not complete:
        return avg, None, "交易日尚未结束，完整日量比待收盘", previous
    if current is None or avg <= 0:
        return avg, None, "缺少当日成交量或此前均量为零", previous
    return avg, current / avg, None, previous
