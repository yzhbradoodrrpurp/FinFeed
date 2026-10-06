"""Public macro observations, shared fresh cache, explicit provenance and gaps."""
import os
import json
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

UTC = timezone.utc
_guard = threading.Lock()
_cache = {}
SERIES = {'jobs': ['PAYEMS', 'UNRATE', 'CES0500000003'], 'pce': ['PCEPI', 'PCEPILFE'], 'treasury': ['DGS10']}


def fetch(url):
    with urlopen(Request(url, headers={'User-Agent': 'FinFeed/1.0 macro research'}), timeout=30) as response:
        return response.read().decode('utf-8')


def observations(series):
    key = os.environ.get('FRED_API_KEY', '')
    if not key:
        raise ValueError('FRED_API_KEY 未配置')
    query = {'api_key': key, 'file_type': 'json', 'series_id': series, 'sort_order': 'desc'}
    if series == 'DGS10':
        query['observation_start'] = history_start()
    else:
        query['limit'] = 36
    params = urlencode(query)
    data = json.loads(fetch('https://api.stlouisfed.org/fred/series/observations?' + params))
    return sorted([{'date': r['date'], 'value': float(r['value'])}
                   for r in data['observations'] if r['value'] != '.'], key=lambda r: r['date'])


def growth(rows, lag):
    out = []
    for i in range(lag, len(rows)):
        old, new = rows[i-lag], rows[i]
        # Do not silently span missing months.
        months = (int(new['date'][:4])-int(old['date'][:4]))*12 + int(new['date'][5:7])-int(old['date'][5:7])
        if months == lag and old['value'] > 0:
            out.append({'date': new['date'], 'value': (new['value']/old['value']-1)*100})
    return out


def schedule(kind, now):
    if kind == 'pce':
        data = json.loads(fetch('https://apps.bea.gov/API/signup/release_dates.json'))
        dates = [datetime.fromisoformat(s) for s in data['Personal Income and Outlays']['release_dates']]
        source = 'https://www.bea.gov/news/schedule/full'
    else:
        from curl_cffi import requests
        response = requests.get('https://www.bls.gov/schedule/news_release/bls.ics', impersonate='chrome', timeout=30)
        response.raise_for_status()
        text = response.text
        text = re.sub(r'\r?\n[ \t]', '', text)
        dates = []
        for event in text.split('BEGIN:VEVENT')[1:]:
            if 'Employment Situation' not in event:
                continue
            match = re.search(r'DTSTART([^:]*):(\d{8}T\d{6}Z?)', event)
            if match:
                raw = match[2]
                dt = datetime.strptime(raw.rstrip('Z'), '%Y%m%dT%H%M%S')
                dates.append(dt.replace(tzinfo=UTC if raw.endswith('Z') else ZoneInfo('America/New_York')))
        source = 'https://www.bls.gov/schedule/news_release/empsit.htm'
    previous = [d for d in dates if d <= now]
    future = [d for d in dates if d > now]
    return {'last_release': max(previous).isoformat() if previous else None,
            'next_release': min(future).isoformat() if future else None, 'calendar_source': source}


def history_start():
    today = datetime.now(UTC).date()
    try:
        return today.replace(year=today.year-3).isoformat()
    except ValueError:
        return today.replace(year=today.year-3, day=28).isoformat()


def metric(label, rows, unit, source, full_history=False):
    return {'label': label, 'unit': unit, 'latest': rows[-1] if rows else None,
            'previous': rows[-2] if len(rows) > 1 else None,
            'history': rows if full_history else rows[-24:], 'source': source}


def _load_metrics(kind):
    now = datetime.now(UTC)
    card = {'id': kind, 'retrieved_at': now.isoformat(), 'metrics': [], 'errors': []}
    try:
        if kind == 'dxy':
            import yfinance as yf
            from data import LIMIT
            with LIMIT:
                frame = yf.Ticker('DX-Y.NYB').history(start=history_start(), interval='1d', auto_adjust=False, timeout=30)
            rows = [{'date': d.date().isoformat(), 'value': float(row['Close'])} for d, row in frame.iterrows() if row['Close'] == row['Close']]
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
            card['errors'].append('部分数据未取得')
    except Exception:
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
        except Exception:
            card['errors'].append('发布日历暂不可用')
    return card


def snapshot(kind):
    if kind not in {'jobs', 'pce', 'dxy', 'treasury'}:
        raise ValueError('Unknown macro indicator')
    # Separate per-indicator locks allow the four cards to load independently.
    with _guard:
        entry = _cache.setdefault(kind, {'lock': threading.Lock(), 'expires': 0})
    with entry['lock']:
        if time.monotonic() < entry['expires']:
            return entry['value']
        value = load(kind)
        entry['value'] = value
        entry['expires'] = time.monotonic() + (60 if value['errors'] else 3600)
        return value
