"""Daily consensus estimate cache. Credentials never enter returned provenance."""
import json
import math
import os
import threading
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / '.local' / 'alphavantage.json'
CACHE = ROOT / '.cache' / 'alpha'
LOCK = threading.Lock()
SOURCE = 'https://www.alphavantage.co/documentation/#earnings-estimates'


def estimate_data(symbol, timestamp, store=None):
    key = os.environ.get('ALPHAVANTAGE_API_KEY')
    if not key and CONFIG.exists():
        key = json.loads(CONFIG.read_text()).get('api_key')
    if not key:
        return None
    with LOCK:
        CACHE.mkdir(parents=True, exist_ok=True)
        path = CACHE / f'{symbol}.json'
        stored = store.get_cache('alpha:' + symbol) if store else None
        saved = stored[0] if stored else (json.loads(path.read_text()) if not store and path.exists() else {})
        day = datetime.fromisoformat(timestamp).astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
        budget_day = timestamp[:10]  # Provider quota guard uses UTC; response limits are also handled.
        if saved.get('checked_day') == day:
            return saved
        budget_path = CACHE / 'usage.json'
        budget_saved = store.get_cache('alpha:usage') if store else None
        budget = budget_saved[0] if budget_saved else (json.loads(budget_path.read_text()) if not store and budget_path.exists() else {})
        if budget.get('day') != budget_day:
            budget = {'day': budget_day, 'calls': 0}
        error = None
        payload = None
        if budget['calls'] >= 25:
            error = 'Alpha Vantage 本机每日 25 次额度已用完'
        else:
            budget['calls'] += 1
            if store:
                store.set_cache('alpha:usage', budget)
            else:
                budget_path.write_text(json.dumps(budget))
            url = 'https://www.alphavantage.co/query?' + urllib.parse.urlencode({'function': 'EARNINGS_ESTIMATES', 'symbol': symbol, 'apikey': key})
            try:
                with urllib.request.urlopen(url, timeout=25) as response:
                    candidate = json.load(response)
                if candidate.get('symbol') == symbol and isinstance(candidate.get('estimates'), list):
                    payload = candidate
                else:
                    # Never include raw API messages/URLs, which may contain credentials.
                    error = 'Alpha Vantage 未返回预测数据（可能额度、权限或证券覆盖受限）'
            except Exception as exc:
                error = f'Alpha Vantage 读取失败：{type(exc).__name__}'
        result = {'checked_day': day, 'fetched_at': timestamp if payload is not None else saved.get('fetched_at'),
                  'data': payload if payload is not None else saved.get('data'), 'error': error}
        if store:
            store.set_cache('alpha:' + symbol, result)
        else:
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(result, allow_nan=False))
            temporary.replace(path)
        return result


def next_four_eps(payload, timestamp):
    """Next four full fiscal quarters, not FY1 and not an interpolated rolling year."""
    today = datetime.fromisoformat(timestamp).date()
    quarters = {}
    for row in (payload or {}).get('estimates', []):
        if row.get('horizon') != 'fiscal quarter':
            continue
        try:
            end = datetime.fromisoformat(row['date']).date()
            value = float(row['eps_estimate_average'])
            if not math.isfinite(value):
                continue
        except (KeyError, ValueError, TypeError):
            continue
        if end > today:
            quarters[end.isoformat()] = value
    selected = sorted(quarters.items())[:4]
    if len(selected) != 4:
        return None, selected, 'Alpha Vantage 未提供未来四个完整财季 EPS 预期'
    if not 0 < (datetime.fromisoformat(selected[0][0]).date() - today).days <= 120 or any(not 65 <= (datetime.fromisoformat(b[0]) - datetime.fromisoformat(a[0])).days <= 120 for a, b in zip(selected, selected[1:])):
        return None, selected, '预测财季不连续，无法计算 NTM 近似值'
    return sum(value for _, value in selected), selected, None
