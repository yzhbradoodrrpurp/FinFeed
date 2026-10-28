"""Read-only public Polymarket event prices; shared cache across accounts."""
from backend.infrastructure.failure_log import failure
import json
import os
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
_history_retry = {}
_requests = threading.BoundedSemaphore(4)


def get(url, _text=False, **params):
    started = time.monotonic()
    try:
        options = {'proxy': os.environ['POLYMARKET_PROXY_URL']} if os.environ.get('POLYMARKET_PROXY_URL') else {}
        with _requests:
            response = requests.get(url, params=params, impersonate='chrome', timeout=15, **options)
        response.raise_for_status()
        return response.text if _text else response.json()
    except Exception as exc:
        from urllib.parse import urlsplit
        target = urlsplit(url)
        failure('polymarket', target.path, error=exc, started=started)
        raise


def valid_price(value):
    value = float(value)
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('Invalid probability')
    return value


def cache_read(store, key):
    try:
        return store.get_cache(key) if store else None
    except Exception as exc:
        failure('database', 'polymarket_cache_read', error=exc)


def cache_write(store, key, value):
    try:
        if store:
            store.set_cache(key, value)
    except Exception as exc:
        failure('database', 'polymarket_cache_write', error=exc)


def history_key(token, slug=SLUG):
    return 'polymarket:history:v1:' + slug + ':' + token


def history(token, start, end, store=None, slug=SLUG):
    key = (slug, token)
    cached = _history.get(key)
    if cached is None:
        saved = cache_read(store, history_key(token, slug))
        if saved and saved[0].get('history'):
            value, updated = saved
            cached = (time.monotonic() + max(0, 3600-(time.time()-updated)),
                      value['history'], value['retrieved_at'])
            _history[key] = cached
    if cached and time.monotonic() < cached[0]:
        return cached[1]
    if time.monotonic() < _history_retry.get(key, 0):
        raise RuntimeError('History refresh cooling down')
    # The API limits explicit time ranges. Fetch non-overlapping fortnight windows.
    windows = [(left, min(left + 14*86400, end)) for left in range(start, end, 14*86400)]
    def window(bounds):
        for attempt in range(2):
            try:
                data = get('https://clob.polymarket.com/prices-history', market=token,
                           startTs=bounds[0], endTs=bounds[1], fidelity=360)
                return [{'t': int(row['t']), 'p': valid_price(row['p'])} for row in data['history']]
            except Exception as exc:
                failure('polymarket', 'history_window', error=exc,
                        window_start=bounds[0], window_end=bounds[1], attempt=attempt+1)
                if attempt:
                    raise
                time.sleep(.5)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            rows = [row for chunk in pool.map(window, windows) for row in chunk]
        rows = sorted({row['t']: row for row in rows}.values(), key=lambda row: row['t'])
        if not rows:
            raise ValueError('Empty history response')
    except Exception:
        _history_retry[key] = time.monotonic()+60
        raise
    retrieved = datetime.now(timezone.utc).isoformat()
    _history[key] = (time.monotonic()+3600, rows, retrieved)
    _history_retry.pop(key, None)
    cache_write(store, history_key(token, slug), {'history': rows, 'retrieved_at': retrieved})
    return rows


def load(store=None):
    from backend.providers.fed_market import select_event
    event, meeting = select_event(get, store)
    slug = event['slug']
    now = datetime.now(timezone.utc)
    start = int(datetime.fromisoformat(event['startDate'].replace('Z', '+00:00')).timestamp())
    def market(m):
        outcomes = json.loads(m['outcomes'])
        yes = outcomes.index('Yes')
        token = json.loads(m['clobTokenIds'])[yes]
        key = (slug, token)
        result = {'label': LABELS.get(m.get('groupItemTitle'), m['question']),
                  'price': valid_price(json.loads(m['outcomePrices'])[yes]),
                  'token': token, 'history': [], 'history_error': False}
        try:
            result['history'] = history(token, start, int(now.timestamp()), store, slug)
        except Exception as exc:
            failure('polymarket', 'history', reason=result['label'], error=exc)
            result['history_error'] = True
            cached = _history.get(key)
            if cached:
                result['history'] = cached[1]
        cached = _history.get(key)
        result['history_retrieved_at'] = cached[2] if cached else None
        return result
    markets = sorted(event['markets'], key=lambda m: list(LABELS).index(m['groupItemTitle']) if m.get('groupItemTitle') in LABELS else 99)
    with ThreadPoolExecutor(max_workers=5) as pool:
        series = list(pool.map(market, markets))
    return {'title': event['title'], 'slug': slug, 'meeting': meeting,
            'source': 'https://polymarket.com/zh/event/' + slug, 'retrieved_at': now.isoformat(),
            'closed': event.get('closed', False), 'volume': event.get('volume'),
            'liquidity': event.get('liquidity'), 'rules': markets[0].get('description', ''),
            'series': series, 'errors': []}


def snapshot(store=None, on_update=None):
    global _value, _expires
    with _lock:
        if _value is not None and time.monotonic() < _expires:
            return _value
        if _value is None:
            saved = (cache_read(store, 'polymarket:current:v2')
                     or cache_read(store, 'polymarket:event:v1:' + SLUG))
            if saved:
                _value = saved[0]
        if on_update and _value and _value.get('series'):
            on_update({**_value, 'cached': True, 'refreshing': True})
        try:
            fresh = load(store) if store else load()
            old_slug = (_value or {}).get('slug', SLUG)
            if _value and fresh.get('slug', SLUG) != old_slug and any(
                    not item.get('history') for item in fresh.get('series', [])):
                raise ValueError('Next meeting history not ready')
            _value = fresh
            cache_write(store, 'polymarket:event:v1:' + _value.get('slug', SLUG), _value)
            cache_write(store, 'polymarket:current:v2', _value)
        except Exception as exc:
            failure('polymarket', 'event_snapshot', error=exc)
            _value = {**(_value or {'series': [], 'source': SOURCE}),
                      'stale': True,
                      'errors': ['Polymarket 市场或日程更新失败，保留上次会议数据，时间见下方']}
        _expires = time.monotonic()+60
        return _value
