"""Longbridge market adapter; statements outside market/EPS remain independent."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import os
from decimal import Decimal
import re
import threading
import time
from typing import Any
from zoneinfo import ZoneInfo

from backend.domain.metrics import number, prior_quarter_period, trailing_pe, volume_metrics
from backend.infrastructure.failure_log import failure

VERSION = 1
SOURCE = 'https://open.longbridge.com/docs/quote/pull/calc-index'
EPS_SOURCE = 'https://open.longbridge.com/docs/fundamental/fundamental/consensus'
KEYS = ('market_cap', 'price', 'high_52w', 'low_52w', 'avg_volume_10',
        'relative_volume_10', 'eps_q0', 'eps_q1', 'forward_eps_next', 'pe_ltm', 'pe_forward_4q')
_contexts = None
_context_lock = threading.Lock()
_fundamental_lock = threading.Lock()
_fundamental_last = 0.0
_block_guard = threading.Lock()
_block_locks: dict[str, threading.Lock] = {}
_block_retry: dict[str, float] = {}
FUNDAMENTAL_TTL = 300


def _fundamental_call(action: Any) -> Any:
    """Respect the fundamental API's one-request-per-second quota across workers' threads."""
    global _fundamental_last
    with _fundamental_lock:
        wait = 1.1 - (time.monotonic() - _fundamental_last)
        if wait > 0:
            time.sleep(wait)
        _fundamental_last = time.monotonic()
        return action()


def metric(value: Any, period: str | None, basis: str, source: str = SOURCE,
           **extra: Any) -> dict:
    """Keep unavailable observations distinct from zero."""
    value = number(value)
    return dict(value=value, period=period, basis=basis, source=source,
                reason=None if value is not None else '长桥未提供该指标', **extra)


def _utc(value: datetime) -> datetime:
    # The SDK uses the process's local timezone for naive Python timestamps.
    return value.astimezone(timezone.utc)


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return _utc(value).isoformat()
    return {k: _plain(getattr(value, k)) for k in dir(value)
            if not k.startswith('_') and not callable(getattr(value, k))}


def contexts() -> tuple:
    """Create one shared quote/fundamental client per worker, without SDK output."""
    global _contexts
    with _context_lock:
        if _contexts is None:
            from longbridge.openapi import Config, QuoteContext, FundamentalContext
            credentials = [os.environ.get('LONGBRIDGE_' + key) for key in
                           ('APP_KEY', 'APP_SECRET', 'ACCESS_TOKEN')]
            if not all(credentials):
                raise RuntimeError('Longbridge credentials missing')
            config = Config.from_apikey(*credentials, enable_print_quote_packages=False)
            _contexts = QuoteContext(config), FundamentalContext(config)
        return _contexts


def _cached(symbol: str, block: str, action: Any, store: Any,
            ttl: int, force: bool = False) -> dict:
    with _block_guard:
        lock = _block_locks.setdefault(f'{block}:{symbol}', threading.Lock())
    with lock:
        return _cached_locked(symbol, block, action, store, ttl, force)


def _cached_locked(symbol: str, block: str, action: Any, store: Any,
                   ttl: int, force: bool = False) -> dict:
    """Share successful provider blocks across users; failed refreshes retain them."""
    key = f'longbridge:v{VERSION}:{block}:{symbol}'
    try:
        saved = store.get_cache(key) if store else None
    except Exception as exc:
        failure('database', 'longbridge_cache_read', symbol=symbol, error=exc)
        saved = None
    minimum = 60 if block in ('financial', 'consensus') else 10
    if saved and time.time() - saved[1] < (minimum if force else ttl):
        return saved[0]
    if time.monotonic() < _block_retry.get(key, 0):
        if saved:
            return {**saved[0], 'stale': True}
        raise RuntimeError('Longbridge block retry cooldown')
    try:
        data = action()
        if not data:
            raise ValueError('Empty provider block')
        payload = {'data': data, 'fetched_at': datetime.now(timezone.utc).isoformat()}
    except Exception as exc:
        _block_retry[key] = time.monotonic()+60
        failure('longbridge', block, symbol=symbol, error=exc, fallback_available=bool(saved))
        if saved:
            return {**saved[0], 'stale': True}
        raise
    _block_retry.pop(key, None)
    if store:
        try:
            getattr(store, 'publish_cache', store.set_cache)(key, payload)
        except Exception as exc:
            failure('database', 'longbridge_cache_write', symbol=symbol, error=exc)
    return payload


def earnings(financial: dict, consensus: dict, fetched_at: str) -> dict:
    """Match released diluted EPS and three future forecasts to fiscal labels."""
    revenue = {}
    for statement in financial.get('list', {}).values():
        for indicator in statement.get('indicators', []):
            for account in indicator.get('accounts', []):
                if account.get('field') != 'OperatingRevenue':
                    continue
                for item in account.get('values', []):
                    label = item.get('period', '')
                    if re.fullmatch(r'Q[1-4] \d{4}', label) and item.get('fp_end') and number(item.get('value')) is not None:
                        end = datetime.fromtimestamp(int(item['fp_end']), ZoneInfo('America/New_York')).date().isoformat()
                        if end <= fetched_at[:10]:
                            revenue[end] = label
    q0 = max(revenue, default=None)
    q1 = prior_quarter_period(q0, revenue) if q0 else None
    currency = consensus.get('currency')
    rows = {row.get('period_text'): row for row in consensus.get('list', [])}
    def eps(label: str | None, actual: bool) -> dict | None:
        return next((d for d in rows.get(label, {}).get('details', [])
                     if d.get('key') == 'eps' and bool(d.get('is_released')) == actual), None)
    metrics = {}
    for key, period in [('eps_q0', q0), ('eps_q1', q1)]:
        label = revenue.get(period)
        item = eps(label, True) or {}
        metrics[key] = metric(item.get('actual'), period, '长桥已披露单季 GAAP 稀释 EPS',
                              EPS_SOURCE, currency=currency, fiscal_label=label, fetched_at=fetched_at)
    forecast_labels = []
    if q0:
        quarter, year = map(int, re.fullmatch(r'Q([1-4]) (\d{4})', revenue[q0]).groups())
        for _ in range(3):
            quarter, year = (quarter + 1, year) if quarter < 4 else (1, year + 1)
            forecast_labels.append(f'Q{quarter} {year}')
    forecasts = []
    for label in forecast_labels:
        item = eps(label, False) or {}
        forecasts.append({'fiscal_label': label, 'value': number(item.get('estimate'))})
    first = forecasts[0] if forecasts else {}
    metrics['forward_eps_next'] = metric(first.get('value'), None,
        '长桥下一财季分析师 GAAP 稀释 EPS 均值；不是全年预测', EPS_SOURCE,
        currency=currency, estimate_label=first.get('fiscal_label'), fetched_at=fetched_at)
    return {'metrics': metrics, 'market_quarter_0': q0, 'market_quarter_1': q1,
            'forecast_quarters': forecasts, 'eps_currency': currency}


def normalize(symbol: str, blocks: dict, fetched_at: str, quote_type: str) -> dict:
    """Calculate market metrics from regular-session bars and documented indexes."""
    static, quote, indexes = (blocks[name]['data'] for name in ('static', 'quote', 'indexes'))
    tz = ZoneInfo('America/New_York')
    quote_time = datetime.fromisoformat(quote['timestamp'])
    quote_date = quote_time.astimezone(tz).date().isoformat()
    url = f'https://longbridge.com/en/quote/{symbol}.US'
    currency = static.get('currency')
    m = {}
    m['price'] = metric(quote.get('last_done'), quote_date, '长桥常规交易时段最近成交价；不合并盘前盘后', url, currency=currency)
    m['market_cap'] = metric(indexes.get('total_market_value'), quote_date, '长桥总市值指标；ETF 不用资产规模代替', SOURCE, currency=currency)
    pe = number(indexes.get('pe_ttm_ratio'))
    m['pe_ltm'] = metric(pe if pe is not None and pe > 0 else None, quote_date,
                        '长桥 TTM P/E = 当前股价 / 最近十二个月 EPS；供应商计算指标', SOURCE)
    if pe is not None and pe <= 0:
        m['pe_ltm']['reason'] = 'TTM 盈利非正，P/E 不适用'
    bars = blocks.get('bars', {}).get('data', [])
    dated = sorted([(datetime.fromisoformat(b['timestamp']).astimezone(tz).date().isoformat(), b)
                    for b in bars], key=lambda row: row[0])
    # NYSE calendar also covers Nasdaq regular-session holidays/early closes.
    import pandas_market_calendars as calendars
    schedule = calendars.get_calendar('NYSE').schedule(start_date=quote_date, end_date=quote_date)
    complete = bool(not schedule.empty and datetime.fromisoformat(fetched_at) >= schedule.iloc[0]['market_close'].to_pydatetime())
    avg, ratio, reason, inputs = volume_metrics([(d, b['volume']) for d, b in dated], quote_date, complete)
    m['avg_volume_10'] = metric(avg, quote_date, '此前 10 个完整交易日平均成交股数；排除比较日', url,
        inputs=[{'date': d, 'volume': v} for d, v in inputs])
    m['relative_volume_10'] = metric(ratio, quote_date, '比较日完整成交量 / 此前 10 日均量；未使用长桥内置量比', url,
        inputs={'average': avg, 'volume': next((b['volume'] for d, b in dated if d == quote_date), None)})
    m['relative_volume_10']['reason'] = reason
    cutoff = (datetime.fromisoformat(quote_date).date() - timedelta(days=365)).isoformat()
    ranges = [b for d, b in dated if cutoff < d <= quote_date]
    for key, name, fn in [('high_52w', 'high', max), ('low_52w', 'low', min)]:
        values = [number(b[name]) for b in ranges if number(b[name]) is not None]
        m[key] = metric(fn(values) if values else None, quote_date,
            '长桥最近 365 日常规时段前复权日线极值；复权含公司行动，可能与 Yahoo 区间口径不同', url,
            currency=currency, window_start=cutoff, adjustment='ForwardAdjust', fetched_at=blocks.get('bars', {}).get('fetched_at'))
    output = dict(ticker=symbol, name=static.get('name_en') or symbol, currency=currency,
                  exchange=static.get('exchange'), exchange_timezone='America/New_York',
                  quote_date=quote_date, quote_at=quote_time.isoformat(), volume_complete=complete,
                  fetched_at=blocks['quote'].get('fetched_at', fetched_at), market_provider='longbridge', market_version=VERSION,
                  market_type=quote_type, metrics=m, sources={'quote': url, 'market_eps': EPS_SOURCE},
                  errors=[], delay_minutes=None)
    if quote_type == 'ETF':
        for key in ('market_cap', 'pe_ltm', 'pe_forward_4q', 'eps_q0', 'eps_q1', 'forward_eps_next'):
            m[key] = metric(None, None, 'ETF 公司财务与市盈率不适用')
            m[key]['reason'] = 'ETF 公司财务与市盈率不适用'
    else:
        actual = earnings(blocks.get('financial', {}).get('data', {}), blocks.get('consensus', {}).get('data', {}),
                          min(blocks.get('financial', {}).get('fetched_at', fetched_at), blocks.get('consensus', {}).get('fetched_at', fetched_at)))
        output.update({k: v for k, v in actual.items() if k != 'metrics'})
        m.update(actual['metrics'])
        forecasts = actual['forecast_quarters']
        quarters = [{'fiscal_label': m['eps_q0'].get('fiscal_label'),
                     'period': actual['market_quarter_0'], 'kind': 'actual',
                     'value': m['eps_q0']['value']},
                    *[{**x, 'kind': 'forecast'} for x in forecasts]]
        complete_eps = len(quarters) == 4 and all(x['value'] is not None for x in quarters)
        total = sum(x['value'] for x in quarters) if complete_eps else None
        pe, reason = trailing_pe(m['price']['value'], total)
        if complete_eps and total <= 0:
            reason = '实际 1 季 + 预测 3 季的 EPS 合计为零或负值，Forward P/E 不适用'
        if not complete_eps:
            reason = '缺少最近已披露季度实际 EPS 或未来三个连续财季预测 EPS；未跳过缺季或使用单季年化'
        if actual['eps_currency'] != currency:
            pe, reason = None, '报价与预测 EPS 币种不同，未自动换汇'
        m['pe_forward_4q'] = metric(pe, None, 'Forward P/E = 当前股价 /（最近已披露季度实际 GAAP 稀释 EPS + 未来三个连续财季预测 GAAP 稀释 EPS）；实际 1 季 + 预测 3 季，不是标准 NTM', EPS_SOURCE,
            estimate_label=' / '.join(x['fiscal_label'] or '缺失' for x in quarters),
            inputs={'price': m['price']['value'], 'quarters': quarters, 'four_quarter_eps_sum': total})
        m['pe_forward_4q']['reason'] = reason
    for name, block in blocks.items():
        if block.get('stale') or block.get('failed'):
            output['errors'].append('长桥 ' + name + (' 读取失败，暂无成功缓存' if block.get('failed') else ' 刷新失败，使用成功缓存'))
            affected = {'bars': ('high_52w', 'low_52w', 'avg_volume_10', 'relative_volume_10'),
                        'indexes': ('market_cap', 'pe_ltm'), 'quote': ('price', 'pe_forward_4q'),
                        'financial': ('eps_q0', 'eps_q1', 'forward_eps_next', 'pe_forward_4q'),
                        'consensus': ('eps_q0', 'eps_q1', 'forward_eps_next', 'pe_forward_4q')}.get(name, ())
            for key in affected:
                m[key].update(stale=True, cache_fetched_at=block.get('fetched_at'))
    output['provider_blocks'] = {name: {'fetched_at': block.get('fetched_at'),
                                      'stale': bool(block.get('stale') or block.get('failed'))} for name, block in blocks.items()}
    if blocks.get('quote', {}).get('stale'):
        output['stale'] = True
    return output


def market_snapshot(symbol: str, store: Any, quote_type: str, force: bool = False,
                    on_quote: Any = None, financial_refresh: bool | None = None) -> dict:
    """Fetch only market/EPS blocks; never requests orders or trading endpoints."""
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9.\-]{0,19}', symbol):
        raise ValueError('Unsupported Longbridge US symbol')
    from longbridge.openapi import CalcIndex, Period, AdjustType, TradeSessions, FinancialReportKind, FinancialReportPeriod
    qctx, fctx = contexts()
    code = symbol + '.US'
    def one(action: Any, fields: tuple) -> dict:
        rows = action()
        if len(rows) != 1 or rows[0].symbol != code:
            raise ValueError('Unexpected quote symbol')
        return {key: (_utc(getattr(rows[0], key)).isoformat() if key == 'timestamp' else
                      number(getattr(rows[0], key)) if key in ('last_done', 'total_market_value', 'pe_ttm_ratio') else
                      getattr(rows[0], key)) for key in fields}
    requests = [
        ('static', lambda: one(lambda: qctx.static_info([code]), ('symbol', 'name_en', 'currency', 'exchange')), 86400),
        ('quote', lambda: one(lambda: qctx.quote([code]), ('symbol', 'last_done', 'timestamp')), 60),
        ('indexes', lambda: one(lambda: qctx.calc_indexes([code], [CalcIndex.TotalMarketValue, CalcIndex.PeTtmRatio]),
                                ('symbol', 'total_market_value', 'pe_ttm_ratio')), 60),
        ('bars', lambda: [{'timestamp': _utc(b.timestamp).isoformat(), 'high': number(b.high), 'low': number(b.low), 'volume': b.volume}
                          for b in qctx.candlesticks(code, Period.Day, 280, AdjustType.ForwardAdjust, TradeSessions.Intraday)], 60),
    ]
    if quote_type != 'ETF':
        requests += [('financial', lambda: _plain(_fundamental_call(lambda: fctx.financial_report(code, FinancialReportKind.All, FinancialReportPeriod.QuarterlyFull))), FUNDAMENTAL_TTL),
                     ('consensus', lambda: _plain(_fundamental_call(lambda: fctx.consensus(code))), FUNDAMENTAL_TTL)]
    blocks = {}
    errors = []
    for name, action, ttl in requests:
        try:
            block_force = force
            if name in ('financial', 'consensus') and financial_refresh is not None:
                block_force = financial_refresh
            blocks[name] = _cached(symbol, name, action, store, ttl, block_force)
        except Exception as exc:
            if name in ('static', 'quote'):
                raise
            errors.append('长桥 ' + name + ' 读取失败：' + type(exc).__name__)
            blocks[name] = {'data': {} if name != 'bars' else [], 'failed': True, 'fetched_at': datetime.now(timezone.utc).isoformat()}
        if name == 'bars' and on_quote:
            preview_blocks = deepcopy(blocks)
            if store and quote_type != 'ETF':
                for extra in ('financial', 'consensus'):
                    try:
                        saved = store.get_cache(f'longbridge:v{VERSION}:{extra}:{symbol}')
                    except Exception:
                        saved = None
                    if saved:
                        preview_blocks[extra] = {**saved[0], 'stale': time.time()-saved[1] >= FUNDAMENTAL_TTL}
            preview = normalize(symbol, preview_blocks, datetime.now(timezone.utc).isoformat(), quote_type)
            preview['partial'] = True
            on_quote(preview)
    output = normalize(symbol, blocks, datetime.now(timezone.utc).isoformat(), quote_type)
    output['errors'].extend(errors)
    return output


def apply(result: dict, market: dict) -> dict:
    """Overlay market fields without changing quarterly statement anchors/series."""
    for key in ('name', 'currency', 'exchange', 'exchange_timezone', 'quote_date', 'quote_at',
                'volume_complete', 'delay_minutes', 'market_provider', 'market_version',
                'market_quarter_0', 'market_quarter_1'):
        if key in market:
            result[key] = market[key]
    result.setdefault('sources', {}).update(market['sources'])
    result['sources'].pop('estimates', None)
    result['sources'].pop('estimates_alpha', None)
    result.setdefault('metrics', {}).update(deepcopy(market['metrics']))
    # Compatible legacy keys keep existing consumers working, with corrected bases.
    result['metrics']['pe_quarter'] = deepcopy(result['metrics']['pe_ltm'])
    result['metrics']['pe_forward_quarter'] = deepcopy(result['metrics']['pe_forward_4q'])
    result['market_fetched_at'] = market['fetched_at']
    result['longbridge_blocks'] = deepcopy(market.get('provider_blocks', {}))
    result['stale'] = bool(market.get('stale'))
    return result
