"""Bounded Yahoo SEC and earnings-call index snapshots; no article body storage."""
from datetime import datetime, timezone
from urllib.parse import urlsplit
import threading
import re
from zoneinfo import ZoneInfo
import yfinance as yf
import yahoo_session
from failure_log import failure

LIMIT = threading.BoundedSemaphore(4)


def safe_url(value):
    if not isinstance(value, str):
        return ''
    try:
        url = urlsplit(value)
        return value if url.scheme == 'https' and url.hostname and not url.username and not url.password else ''
    except ValueError:
        return ''


def fiscal_period(value):
    year, quarter = value.get('fiscalYear'), value.get('fiscalPeriod')
    match = re.fullmatch(r'Q?([1-4])', str(quarter or ''), re.I)
    if match and str(year).isdigit():
        return int(year) * 4 + int(match[1]) - 1
    title = str(value.get('title') or '')
    match = re.search(r'\bQ([1-4])\s+(?:FY\s*)?(20\d{2})\b', title, re.I)
    if match:
        return int(match[2]) * 4 + int(match[1]) - 1
    return None


def recent_items(items, kind, now=None):
    now = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo('America/New_York'))
    today = now.date().isoformat()
    items = [item for item in items if item.get('published_at', '')[:10] <= today]
    if kind == 'calls':
        periods = [item['fiscal_period'] for item in items if item.get('fiscal_period') is not None]
        if not periods:
            return []
        latest = max(periods)
        return [item for item in items if item.get('fiscal_period') in {latest, latest - 1}]
    # Index rows do not have report-period metadata. Anchor the filing window
    # to the latest two original quarterly/annual reports, not calendar quarters.
    anchors = sorted({item['published_at'][:10] for item in items
        if re.match(r'^10-[QK](?:\s|$)', item.get('title', ''))
        and re.fullmatch(r'\d{4}-\d{2}-\d{2}', item.get('published_at', '')[:10])}, reverse=True)[:2]
    if not anchors:
        return []
    start = min(anchors)
    return [item for item in items if start <= item.get('published_at', '')[:10] <= today]


def normalize(raw, kind):
    if not isinstance(raw, list):
        raise ValueError('Invalid provider response')
    items, seen = [], set()
    for row in raw:
        if not isinstance(row, dict) or row.get('ad'):
            continue
        value = row
        if not isinstance(value, dict):
            continue
        if kind == 'calls':
            url = safe_url(value.get('url'))
            title = value.get('title')
            timestamp = value.get('date')
            date = datetime.fromtimestamp(timestamp, timezone.utc).isoformat() if isinstance(timestamp, (int, float)) else ''
            source = 'Yahoo Finance · 财报电话会'
        else:
            url = safe_url(value.get('edgarUrl') or value.get('url'))
            exhibits = value.get('exhibits') or {}
            if isinstance(exhibits, list):
                exhibits = {entry.get('type'): entry.get('url') for entry in exhibits if isinstance(entry, dict)}
            if not isinstance(exhibits, dict):
                exhibits = {}
            for exhibit in exhibits.values():
                candidate = safe_url(exhibit)
                parsed = urlsplit(candidate)
                if parsed.hostname == 'cdn.yahoofinance.com' and parsed.path.startswith('/prod/sec-filings/'):
                    parts = parsed.path.split('/')[3:]
                    if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit():
                        url = 'https://www.sec.gov/Archives/edgar/data/' + str(int(parts[0])) + '/' + '/'.join(parts[1:])
                        break
                elif parsed.hostname in {'sec.gov', 'www.sec.gov'}:
                    url = candidate
                    break
            if not url:
                url = next((safe_url(u) for u in exhibits.values() if safe_url(u)), '')
            title = ' · '.join(str(v) for v in (value.get('type'), value.get('title')) if v)
            date = str(value.get('date') or '')
            source = 'SEC EDGAR'
        if not url or not title or url in seen:
            continue
        seen.add(url)
        item = {'title': str(title), 'url': url, 'published_at': str(date or ''), 'source': source, 'kind': kind}
        if kind == 'calls':
            item['fiscal_period'] = fiscal_period(value)
        items.append(item)
    return sorted(items, key=lambda x: x['published_at'], reverse=True)



def fetch_index(ticker, symbol, kind):
    module = 'earningsCallTranscripts' if kind == 'calls' else 'secFilings'
    field = 'transcripts' if kind == 'calls' else 'filings'
    last_error = None
    # Bounded retry through Yahoo's other host. Never turn HTTP/schema failures into empty success.
    for host in ('query2', 'query1'):
        try:
            response = ticker._data.get('https://' + host + '.finance.yahoo.com/v10/finance/quoteSummary/' + symbol,
                params={'modules': module, 'formatted': 'false'}, timeout=6)
            if response.status_code == 404:
                return [], 'Yahoo 暂未提供该标的的' + ('财报电话会' if kind == 'calls' else 'SEC 披露') + '记录'
            response.raise_for_status()
            payload = response.json()['quoteSummary']
            if payload.get('error'):
                raise ValueError('Provider reported an error')
            rows = payload['result'][0][module][field]
            if not isinstance(rows, list):
                raise ValueError('Invalid index response')
            return rows, ''
        except Exception as exc:
            last_error = exc
    raise last_error


def snapshot(symbol, kind):
    if kind not in {'calls', 'sec'}:
        raise ValueError('Unsupported news category')
    value = {'ticker': symbol, 'kind': kind, 'items': [], 'retrieved_at': datetime.now(timezone.utc).isoformat(), 'errors': []}
    acquired = LIMIT.acquire(timeout=3)
    try:
        if not acquired:
            raise TimeoutError('News provider slots busy')
        yahoo_session.initialize()
        raw, note = fetch_index(yf.Ticker(symbol), symbol, kind)
        value['items'] = recent_items(normalize(raw, kind), kind)
        value['period_basis'] = 'fiscal_quarter' if kind == 'calls' else 'latest_periodic_filings'
        if note:
            value['note'] = note
        elif raw and not value['items']:
            value['note'] = '来源索引中没有可识别的已披露财季记录'
    except Exception as exc:
        failure('yahoo', 'news_' + kind, symbol=symbol, error=exc)
        value['errors'] = ['该来源暂时无法获取，下次更新重试']
    finally:
        if acquired:
            LIMIT.release()
    return value
