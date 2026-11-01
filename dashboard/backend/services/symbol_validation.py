"""Verify new Watchlist identities before committing account records.

A supplier outage is not evidence that a ticker does not exist. Successful static
identities are shared for one day; explicit empty security lookups for five minutes.
"""
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import threading
import time

from backend.domain.state_validation import SYMBOL

_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='ticker-validation')
_guard = threading.Lock()
_pending = {}


class UnknownTicker(ValueError):
    pass


class ValidationUnavailable(RuntimeError):
    pass


def _lookup(symbol, store):
    us = not symbol.endswith('-USD') and ('.' not in symbol or symbol.rsplit('.', 1)[1] in ('A','B')) and not symbol.startswith('^')
    if us:
        from backend.providers.longbridge import contexts
        from backend.providers.candles import _call
        qctx, _ = contexts()
        rows = _call(lambda: qctx.static_info([symbol+'.US']))
        if not rows:
            return {'ticker':symbol, 'valid':False}
        if len(rows) != 1 or rows[0].symbol != symbol+'.US':
            raise ValidationUnavailable('证券代码校验响应不一致，请稍后重试')
        row = rows[0]
        if not row.name_en or not row.currency or not row.exchange:
            raise ValidationUnavailable('证券资料暂不完整，请稍后重试')
        return {'ticker':symbol, 'valid':True, 'name':row.name_en, 'provider':'longbridge'}
    from backend.providers.yahoo import session
    import yfinance as yf
    session.initialize()
    info = yf.Ticker(symbol).get_info()
    if not info or str(info.get('symbol','')).upper() != symbol or not info.get('quoteType') or not (info.get('shortName') or info.get('longName')):
        # Yahoo may return an incomplete object during upstream failures.
        raise ValidationUnavailable('暂时无法确认该证券，请稍后重试')
    return {'ticker':symbol, 'valid':True, 'name':info.get('shortName') or info['longName'], 'provider':'yahoo'}


def _verify(symbol, store):
    try:
        value = _lookup(symbol, store)
        store.set_cache('ticker-validation:v1:'+symbol, value)
        return value
    except ValidationUnavailable:
        raise
    except Exception as exc:
        from backend.infrastructure.failure_log import failure
        failure('market', 'ticker_validation', symbol=symbol, error=exc)
        raise ValidationUnavailable('数据源暂时无法验证 Ticker，请稍后重试') from exc


def validate_symbols(symbols, store):
    if not isinstance(symbols, list) or len(symbols)>128 or any(not isinstance(s,str) or not SYMBOL.fullmatch(s) for s in symbols):
        raise UnknownTicker('Ticker 格式不正确')
    deadline = time.monotonic()+10
    for symbol in dict.fromkeys(symbols):
        saved = store.get_cache('ticker-validation:v1:'+symbol)
        value = saved[0] if saved and time.time()-saved[1] < (86400 if saved[0].get('valid') else 300) else None
        if value is None:
            # Reuse the already verified Longbridge static block, not prices or
            # the bundled (potentially stale) autocomplete directory.
            static = store.get_cache('longbridge:v1:static:'+symbol)
            data = static[0].get('data', {}) if static and time.time()-static[1]<86400 else {}
            if data.get('symbol') == symbol+'.US' and data.get('name_en') and data.get('exchange') and data.get('currency'):
                value = {'ticker':symbol, 'valid':True}
        if value is None:
            with _guard:
                for key in list(_pending):
                    if key != symbol and _pending[key].done():
                        _pending.pop(key, None)
                if symbol not in _pending:
                    if len(_pending)>=128:
                        raise ValidationUnavailable('证券校验繁忙，请稍后重试')
                    _pending[symbol] = _pool.submit(_verify, symbol, store)
                future = _pending[symbol]
            try:
                value = future.result(timeout=max(.01,deadline-time.monotonic()))
            except FutureTimeout as exc:
                raise ValidationUnavailable('证券校验超时，请稍后重试；尚未添加') from exc
            finally:
                if future.done():
                    with _guard:
                        if _pending.get(symbol) is future:
                            _pending.pop(symbol, None)
        if value.get('valid') is not True:
            raise UnknownTicker(f'没有该 Ticker：{symbol}，无法添加')
    return set(symbols)
