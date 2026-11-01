"""Three calendar years of regular-session OHLCV; scheduled durable snapshots."""
from datetime import datetime, timezone
import re
import threading
import time
from zoneinfo import ZoneInfo

from backend.domain.metrics import number
from backend.providers.longbridge import contexts

KEY = 'candles:3y:v1:'
TTL = 3600
_call_lock = threading.Lock()
_last_call = 0.0


def _call(action):
    global _last_call
    with _call_lock:
        wait = 1.1 - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()
        return action()


def valid(value):
    return bool(value.get('bars')) or value.get('unsupported') is True


def normalize(rows, start, end, zone):
    """Reject corrupt batches instead of replacing a complete successful chart."""
    result = {}
    for row in rows:
        stamp = row.timestamp
        # Like the existing Longbridge adapter, naive SDK datetimes use
        # the process local timezone; astimezone resolves it before dating bars.
        day = stamp.astimezone(zone).date().isoformat()
        if not start.isoformat() <= day <= end.isoformat():
            continue
        prices = {name: number(getattr(row, name)) for name in ('open', 'high', 'low', 'close')}
        volume = number(row.volume)
        if (any(v is None or v <= 0 for v in prices.values()) or volume is None or volume < 0
                or prices['high'] < max(prices['open'], prices['close'], prices['low'])
                or prices['low'] > min(prices['open'], prices['close'])):
            raise ValueError('Invalid OHLCV observation')
        bar = dict(time=day, **prices, volume=volume)
        if day in result and result[day] != bar:
            raise ValueError('Conflicting daily candlesticks')
        result[day] = bar
    if not result:
        raise ValueError('Provider returned no daily history')
    return [result[day] for day in sorted(result)]


def public_snapshot(value):
    """Exclude retired adjustment blocks from older persisted snapshots."""
    return {key: item for key, item in value.items() if key != 'unadjusted'}


def snapshot(symbol):
    from longbridge.openapi import Period, AdjustType, TradeSessions
    zone = ZoneInfo('America/New_York')
    end = datetime.now(zone).date()
    start = end.replace(year=end.year-3, day=min(end.day, 28)) if end.month == 2 and end.day == 29 else end.replace(year=end.year-3)
    value = dict(ticker=symbol, provider='longbridge', period='day', session='regular',
                 timezone=str(zone), start=start.isoformat(), end=end.isoformat(),
                 source='https://open.longbridge.com/docs/quote/pull/history-candlestick',
                 retrieved_at=datetime.now(timezone.utc).isoformat(), errors=[])
    # Match the application's existing US adapter; never guess another market.
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9.-]{0,19}', symbol) or symbol.endswith('-USD') or ('.' in symbol and symbol.rsplit('.', 1)[1] not in ('A', 'B')):
        return dict(value, unsupported=True, note='该标的尚未接入长桥日 K 线', bars=[])
    qctx, _ = contexts()
    static = _call(lambda: qctx.static_info([symbol+'.US']))
    if len(static) != 1 or static[0].symbol != symbol+'.US':
        raise ValueError('Candlestick security identity mismatch')
    value.update(name=static[0].name_en, currency=static[0].currency)
    rows = _call(lambda: qctx.history_candlesticks_by_date(
        symbol+'.US', Period.Day, AdjustType.ForwardAdjust, start, end, TradeSessions.Intraday))
    value['bars'] = normalize(rows, start, end, zone)
    value.update(adjustment='ForwardAdjust', latest_session_may_be_incomplete=True)
    return value
