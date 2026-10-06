"""Read-only public Polymarket event prices; shared cache across accounts."""
import json
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from curl_cffi import requests

SLUG = 'fed-decision-in-october-20260617190323537'
SOURCE = 'https://polymarket.com/zh/event/' + SLUG
LABELS = {'No change': '维持不变', '25 bps increase': '加息 25 bp',
          '50+ bps increase': '加息 50 bp 及以上', '25 bps decrease': '降息 25 bp',
          '50+ bps decrease': '降息 50 bp 及以上'}
_lock = threading.Lock()
_value = None
_expires = 0
_history = {}


def get(url, **params):
    response = requests.get(url, params=params, impersonate='chrome', timeout=30)
    response.raise_for_status()
    return response.json()


def valid_price(value):
    value = float(value)
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('Invalid probability')
    return value


def history(token, start, end):
    cached = _history.get(token)
    if cached and time.monotonic() < cached[0]:
        return cached[1]
    # The API limits explicit time ranges. Fetch non-overlapping fortnight windows.
    windows = [(left, min(left + 14*86400, end)) for left in range(start, end, 14*86400)]
    def window(bounds):
        data = get('https://clob.polymarket.com/prices-history', market=token,
                   startTs=bounds[0], endTs=bounds[1], fidelity=360)
        return [{'t': int(row['t']), 'p': valid_price(row['p'])} for row in data['history']]
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = [row for chunk in pool.map(window, windows) for row in chunk]
    rows = sorted({row['t']: row for row in rows}.values(), key=lambda row: row['t'])
    _history[token] = (time.monotonic()+3600, rows)
    return rows


def load():
    event = get('https://gamma-api.polymarket.com/events/slug/' + SLUG)
    now = datetime.now(timezone.utc)
    start = int(datetime.fromisoformat(event['startDate'].replace('Z', '+00:00')).timestamp())
    def market(m):
        outcomes = json.loads(m['outcomes'])
        yes = outcomes.index('Yes')
        token = json.loads(m['clobTokenIds'])[yes]
        result = {'label': LABELS.get(m.get('groupItemTitle'), m['question']),
                  'price': valid_price(json.loads(m['outcomePrices'])[yes]),
                  'history': [], 'history_error': False}
        try:
            result['history'] = history(token, start, int(now.timestamp()))
        except Exception:
            result['history_error'] = True
        return result
    markets = sorted(event['markets'], key=lambda m: list(LABELS).index(m['groupItemTitle']) if m.get('groupItemTitle') in LABELS else 99)
    with ThreadPoolExecutor(max_workers=5) as pool:
        series = list(pool.map(market, markets))
    return {'title': event['title'], 'source': SOURCE, 'retrieved_at': now.isoformat(),
            'closed': event.get('closed', False), 'volume': event.get('volume'),
            'liquidity': event.get('liquidity'), 'rules': markets[0].get('description', ''),
            'series': series, 'errors': []}


def snapshot():
    global _value, _expires
    with _lock:
        if _value is not None and time.monotonic() < _expires:
            return _value
        try:
            _value = load()
        except Exception:
            _value = {'series': [], 'source': SOURCE, 'retrieved_at': datetime.now(timezone.utc).isoformat(),
                      'errors': ['Polymarket 数据暂不可用，请稍后重试']}
        _expires = time.monotonic()+60
        return _value
