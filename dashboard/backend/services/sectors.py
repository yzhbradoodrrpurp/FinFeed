"""Minute sector quotes with independently persisted, daily-checked history."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone, date
import threading
import time
from backend.services.home import SECTORS, quote
from backend.infrastructure.failure_log import failure

_locks = {s[0]: threading.Lock() for s in SECTORS}
_histories = {}
_retry = {}
_quotes = {}
_history_limit = threading.Semaphore(1)


def complete(rows, today):
    """All eleven ETFs predate this window; short/truncated responses are invalid."""
    if len(rows) < 700:
        return False
    dates = [date.fromisoformat(r['date']) for r in rows]
    return (len(set(dates)) == len(dates) and dates == sorted(dates)
            and dates[0] <= today - timedelta(days=1085)
            and today - timedelta(days=7) <= dates[-1] <= today
            and all(0 < (b-a).days <= 10 for a,b in zip(dates, dates[1:])))


def snapshot(symbol, store, publish=None):
    item = next((s for s in SECTORS if s[0] == symbol), None)
    if item is None:
        raise ValueError('未知板块 ETF')
    with _locks[symbol]:
        if symbol not in _quotes:
            try:
                saved_quote = store.get_cache('market:v1:sector:v3:' + symbol)
                if saved_quote and saved_quote[0].get('sector', {}).get('quoted_at'):
                    _quotes[symbol] = saved_quote[0]['sector']
            except Exception as exc:
                failure("database", "sector_cache_read", symbol=symbol, error=exc)
        recent = quote(item, daily_history=True, history_period='5d')
        now = time.time()
        if recent['error']:
            return {'sector': recent, 'retrieved_at': datetime.now(timezone.utc).isoformat(), 'errors': [recent['error']]}
        previous = _quotes.get(symbol)
        if previous and recent['quoted_at'] < previous['quoted_at']:
            recent.update({k: previous[k] for k in ('price','previous_close','change','change_percent','quoted_at')})
        else:
            _quotes[symbol] = deepcopy(recent)
        today = date.fromisoformat(recent['history'][-1]['date'])
        key = 'market:v1:sector-history:3y:' + symbol
        if symbol not in _histories:
            try:
                saved = store.get_cache(key)
                if saved and complete(saved[0].get('history', []), today):
                    _histories[symbol] = saved[0]
            except Exception as exc:
                failure("database", "sector_history_read", symbol=symbol, error=exc)
        old = _histories.get(symbol)
        old_rows = {r['date']: r['value'] for r in old['history']} if old else {}
        # An overlap correction can indicate a split or provider revision. Rebase
        # the entire series before combining differently adjusted prices.
        corrected = any(r['date'] in old_rows and r['date'] < today.isoformat()
                        and abs(old_rows[r['date']]-r['value']) > 1e-6 for r in recent['history'])
        due = not old or now - old.get('checked_at', 0) >= 86400 or corrected
        warning = None
        if due and now >= _retry.get(symbol, 0):
            if publish:
                preview = {**recent, 'history': old['history'] if old else [],
                           'history_warning': '正在校验三年日线'}
                publish({'sector': preview, 'retrieved_at': datetime.now(timezone.utc).isoformat(), 'refreshing': True})
            with _history_limit:
                full = quote(item, daily_history=True)
            if not full['error'] and complete(full.get('history', []), today):
                old = {'history': full['history'], 'checked_at': now,
                       'retrieved_at': datetime.now(timezone.utc).isoformat()}
                _histories[symbol] = old
                _retry.pop(symbol, None)
                try:
                    getattr(store, 'publish_cache', store.set_cache)(key, old)
                except Exception as exc:
                    failure("database", "sector_history_write", symbol=symbol, error=exc)
                corrected = False
            else:
                _retry[symbol] = now + 300
        if due and (not old or now-old.get('checked_at', 0) >= 86400 or corrected):
            warning = '历史日线校验暂未完成，保留上次成功历史'
        if old:
            rows = {r['date']: r['value'] for r in old['history']}
            if not corrected:
                rows.update({r['date']: r['value'] for r in recent['history']})
            cutoff = today.replace(year=today.year-3) if not (today.month == 2 and today.day == 29) else date(today.year-3, 2, 28)
            recent['history'] = [{'date': d, 'value': v} for d,v in sorted(rows.items()) if d >= cutoff.isoformat()]
        else:
            recent['history'] = []  # Never present five days as three years.
        recent['history_warning'] = warning
        return {'sector': deepcopy(recent), 'retrieved_at': datetime.now(timezone.utc).isoformat(), 'errors': []}
