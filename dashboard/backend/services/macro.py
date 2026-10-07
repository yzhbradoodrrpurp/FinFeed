"""Public macro observations, shared fresh cache, explicit provenance and gaps."""
from backend.infrastructure.failure_log import failure
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from backend.providers import fred, bls, bea
from backend.providers.yahoo import market as yahoo_market
from backend.domain.macro_metrics import growth, history_start, metric

UTC = timezone.utc
_guard = threading.Lock()
_cache = {}
SERIES = {'jobs': ['PAYEMS', 'UNRATE', 'CES0500000003'], 'pce': ['PCEPI', 'PCEPILFE'], 'treasury': ['DGS10']}


def observations(series):
    started = time.monotonic()
    try:
        rows = fred.observations(series, observation_start=history_start() if series == 'DGS10' else None)
        if not rows:
            failure('fred', 'observations', symbol=series, reason='empty observations', started=started)
        return rows
    except Exception as exc:
        failure('fred', 'observations', symbol=series, error=exc, started=started)
        raise


def _schedule(kind, now):
    return (bea if kind == 'pce' else bls).schedule(now)


def schedule(kind, now):
    started = time.monotonic()
    try:
        result = _schedule(kind, now)
        if not result.get('next_release'):
            failure('bea' if kind == 'pce' else 'bls', 'release_calendar',
                    reason='next release missing', started=started)
        return result
    except Exception as exc:
        failure('bea' if kind == 'pce' else 'bls', 'release_calendar', error=exc, started=started)
        raise


def _load_metrics(kind):
    started = time.monotonic()
    now = datetime.now(UTC)
    card = {'id': kind, 'retrieved_at': now.isoformat(), 'metrics': [], 'errors': []}
    try:
        if kind == 'dxy':
            rows = yahoo_market.dxy_history(history_start())
            card['metrics'] = [metric('美元指数', rows, '点', 'https://finance.yahoo.com/quote/DX-Y.NYB/', full_history=True)]
            card['note'] = '最近三年 Yahoo 日线收盘价，最新一日可能尚未收盘；非实时行情，无固定月度发布时间。'
        else:
            with ThreadPoolExecutor(max_workers=3) as pool:
                values = dict(zip(SERIES[kind], pool.map(observations, SERIES[kind])))
            if kind == 'jobs':
                rows = values['PAYEMS']
                changes = []
                for i in range(1, len(rows)):
                    a, b = rows[i-1], rows[i]
                    if (int(b['date'][:4])-int(a['date'][:4]))*12+int(b['date'][5:7])-int(a['date'][5:7]) == 1:
                        changes.append({'date': b['date'], 'value': b['value']-a['value']})
                card['metrics'] = [metric('非农新增就业', changes, '千人', 'https://fred.stlouisfed.org/series/PAYEMS'), metric('失业率', values['UNRATE'], '%', 'https://fred.stlouisfed.org/series/UNRATE'), metric('平均时薪同比', growth(values['CES0500000003'], 12), '%', 'https://fred.stlouisfed.org/series/CES0500000003')]
                card['note'] = 'BLS 数据经 FRED 获取；就业与失业率经季调。前值为当前修订值，暂无发布前预期及修订前快照。'
            elif kind == 'pce':
                for series, label in [('PCEPI', '总体 PCE'), ('PCEPILFE', '核心 PCE')]:
                    card['metrics'].extend([metric(label+'同比', growth(values[series], 12), '%', 'https://fred.stlouisfed.org/series/'+series), metric(label+'环比', growth(values[series], 1), '%', 'https://fred.stlouisfed.org/series/'+series)])
                card['note'] = 'BEA 价格指数经 FRED 获取；同比 = 指数 ÷ 12 个月前指数 − 1，环比 = 指数 ÷ 上月指数 − 1。暂无市场预期。'
            else:
                card['metrics'] = [metric('十年期美债收益率', values['DGS10'], '%', 'https://fred.stlouisfed.org/series/DGS10', full_history=True)]
                card['note'] = '最近三年 H.15 十年恒定期限收益率，日度统计；非实时单只国债报价。工作日 16:15 美国东部时间发布，节假日除外。5.1% 为个人观察线。'
        if not card['metrics'] or any(m['latest'] is None for m in card['metrics']):
            failure('macro', kind, reason='latest metric missing / empty response', started=started)
            card['errors'].append('部分数据未取得')
    except Exception as exc:
        failure('macro', kind, error=exc, started=started)
        # HTTP exceptions may contain credential-bearing URLs. Never serialize them.
        card['errors'].append('数据请求失败，暂不显示历史缓存，请稍后重试')
    return card


def load(kind):
    # Calendar retrieval and metrics have no dependency on one another.
    if kind not in {'jobs', 'pce'}:
        return _load_metrics(kind)
    with ThreadPoolExecutor(max_workers=2) as pool:
        metrics_task = pool.submit(_load_metrics, kind)
        calendar_task = pool.submit(schedule, kind, datetime.now(UTC))
        card = metrics_task.result()
        try:
            card.update(calendar_task.result())
        except Exception as exc:
            failure('bea' if kind == 'pce' else 'bls', 'release_calendar', error=exc)
            card['errors'].append('发布日历暂不可用')
    return card


def snapshot(kind, force=False):
    if kind not in {'jobs', 'pce', 'dxy', 'treasury'}:
        raise ValueError('Unknown macro indicator')
    # Separate per-indicator locks allow the four cards to load independently.
    with _guard:
        entry = _cache.setdefault(kind, {'lock': threading.Lock(), 'expires': 0})
    with entry['lock']:
        if not force and time.monotonic() < entry['expires']:
            return entry['value']
        value = load(kind)
        entry['value'] = value
        entry['expires'] = time.monotonic() + (60 if value['errors'] else 3600)
        return value
