"""Pure calculations; unknown values are never silently replaced with zero."""
import math
from datetime import date


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def qoq(current, previous):
    current, previous = number(current), number(previous)
    if current is None or previous is None:
        return None, "缺少本期或上一财季数据"
    if previous == 0:
        return None, "上一财季为零，百分比变化无法计算"
    return (current - previous) / abs(previous), None


def prior_quarter_period(period, periods):
    current = date.fromisoformat(period)
    previous = sorted((p for p in periods if p < period), reverse=True)
    if not previous:
        return None
    candidate = previous[0]
    # Reject gaps: a missing quarter must not turn a six-month change into QoQ.
    days = (current - date.fromisoformat(candidate)).days
    return candidate if 65 <= days <= 120 else None


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


def change_status(current, previous):
    current, previous = number(current), number(previous)
    if current is None or previous is None:
        return None
    if previous == 0:
        return "由零转正" if current > 0 else "由零转负" if current < 0 else "持平"
    if current == 0:
        return "归零" if previous < 0 else None
    if previous < 0:
        return "转正" if current > 0 else "负值收窄" if current > previous else "负值扩大" if current < previous else "持平"
    return "转负" if current < 0 else None
