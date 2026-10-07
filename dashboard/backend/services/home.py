"""Shared US market overview: exchange calendar and Yahoo index quotes."""
from backend.infrastructure.failure_log import failure
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo
import pandas_market_calendars as calendars

INDICES = [('^GSPC', 'S&P 500', '标普 500'), ('^IXIC', 'Nasdaq Composite', '纳斯达克综合指数'),
           ('^DJI', 'Dow Jones Industrial Average', '道琼斯工业指数')]
_lock = threading.Lock()
_cached = None
_expires = 0


@lru_cache(maxsize=4)
def sessions(day):
    schedule = calendars.get_calendar('NYSE').schedule(start_date=day, end_date=day+timedelta(days=30))
    return [{'open': row.market_open.isoformat(), 'close': row.market_close.isoformat()}
            for row in schedule.itertuples()]


def finite(value):
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def quote(index):
    symbol, name, label = index
    result = {'symbol': symbol, 'name': name, 'label': label,
              'source': 'https://finance.yahoo.com/quote/'+symbol.replace('^', '%5E')+'/',
              'price': None, 'previous_close': None, 'change': None, 'change_percent': None,
              'quoted_at': None, 'error': None}
    started = time.monotonic()
    try:
        import yfinance as yf
        from backend.services.securities import LIMIT
        with LIMIT:
            ticker = yf.Ticker(symbol)
            frame = ticker.history(period='5d', interval='1d', auto_adjust=False, timeout=30, raise_errors=True)
            metadata = ticker.get_history_metadata()
        price = finite(metadata.get('regularMarketPrice'))
        previous = finite(metadata.get('previousClose'))
        raw_time = metadata.get('regularMarketTime')
        timestamp = raw_time.timestamp() if isinstance(raw_time, datetime) else finite(raw_time)
        if price is None or timestamp is None:
            raise ValueError('Quote missing')
        if previous is None and len(frame) >= 2:
            quote_day = datetime.fromtimestamp(timestamp, ZoneInfo('America/New_York')).date()
            offset = -2 if frame.index[-1].date() == quote_day else -1
            previous = finite(frame['Close'].iloc[offset])
        result.update(price=price, previous_close=previous,
                      quoted_at=datetime.fromtimestamp(timestamp, timezone.utc).isoformat())
        if previous is not None and previous > 0:
            result.update(change=price-previous, change_percent=(price/previous-1)*100)
    except Exception as exc:
        failure('yahoo', 'home_index', symbol=symbol, error=exc, started=started)
        result['error'] = '行情暂不可用'
    return result


def snapshot():
    global _cached, _expires
    with _lock:
        if _cached is None or time.monotonic() >= _expires:
            with ThreadPoolExecutor(max_workers=3) as pool:
                indices = list(pool.map(quote, INDICES))
            _cached = {'indices': indices, 'retrieved_at': datetime.now(timezone.utc).isoformat()}
            _expires = time.monotonic()+60
        result = dict(_cached)
    result.update(calendar_snapshot())
    return result


def calendar_snapshot():
    result = {}
    now = datetime.now(timezone.utc)
    result['server_time'] = now.isoformat()
    try:
        result['sessions'] = sessions(now.astimezone(ZoneInfo('America/New_York')).date())
        result['calendar_error'] = None
    except Exception as exc:
        failure('nyse_calendar', 'sessions', error=exc)
        result['sessions'] = []
        result['calendar_error'] = '交易日历暂不可用'
    result['calendar_source'] = 'https://www.nyse.com/trade/hours-calendars'
    return result


_index_locks = {index[0]: threading.Lock() for index in INDICES}
_index_cache = {}


def index_snapshot(symbol):
    index = next((item for item in INDICES if item[0] == symbol), None)
    if index is None:
        raise ValueError('未知指数')
    with _index_locks[symbol]:
        cached = _index_cache.get(symbol)
        if cached is None or time.monotonic() >= cached[0]:
            result = {'index': quote(index), 'retrieved_at': datetime.now(timezone.utc).isoformat()}
            _index_cache[symbol] = (time.monotonic()+60, result)
        return dict(_index_cache[symbol][1])
