"""Bounded Yahoo press-release and SEC index snapshots; no article body storage."""
from datetime import datetime, timezone
from urllib.parse import urlsplit
import threading
import yfinance as yf
import yahoo_session
from failure_log import failure

LIMIT = threading.BoundedSemaphore(8)


def safe_url(value):
    if not isinstance(value, str):
        return ''
    try:
        url = urlsplit(value)
        return value if url.scheme == 'https' and url.hostname and not url.username and not url.password else ''
    except ValueError:
        return ''


def normalize(raw, kind):
    if not isinstance(raw, list):
        raise ValueError('Invalid provider response')
    items, seen = [], set()
    for row in raw:
        if not isinstance(row, dict) or row.get('ad'):
            continue
        value = row.get('content', row) if kind == 'press' else row
        if not isinstance(value, dict):
            continue
        if kind == 'press':
            link = value.get('canonicalUrl') or value.get('clickThroughUrl') or {}
            url = safe_url(link.get('url') if isinstance(link, dict) else link)
            title, date = value.get('title'), value.get('pubDate')
            provider = value.get('provider') or {}
            source = provider.get('displayName', '公司新闻稿') if isinstance(provider, dict) else '公司新闻稿'
        else:
            url = safe_url(value.get('edgarUrl') or value.get('url'))
            for exhibit in (value.get('exhibits') or {}).values():
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
                url = next((safe_url(u) for u in (value.get('exhibits') or {}).values() if safe_url(u)), '')
            title = ' · '.join(str(v) for v in (value.get('type'), value.get('title')) if v)
            date = str(value.get('date') or '')
            source = 'SEC EDGAR'
        if not url or not title or url in seen:
            continue
        seen.add(url)
        items.append({'title': str(title), 'url': url, 'published_at': str(date or ''), 'source': source, 'kind': kind})
    return sorted(items, key=lambda x: x['published_at'], reverse=True)[:20]


def snapshot(symbol, kind):
    value = {'ticker': symbol, 'kind': kind, 'items': [], 'retrieved_at': datetime.now(timezone.utc).isoformat(), 'errors': []}
    try:
        with LIMIT:
            yahoo_session.initialize()
            ticker = yf.Ticker(symbol)
            if kind == 'press':
                # Check HTTP and schema: get_news currently turns a 404 into [].
                response = ticker._data.post('https://finance.yahoo.com/xhr/ncp?queryRef=pressRelease&serviceKey=ncp_fin',
                    body={'serviceConfig': {'snippetCount': 20, 's': [symbol]}})
                if response.status_code == 404:
                    # Current Yahoo page configuration uses this expanded queryRef.
                    response = ticker._data.post('https://finance.yahoo.com/xhr/ncp?queryRef=finance-US-en-US-ticker-pressrelease&serviceKey=ncp_fin',
                        body={'serviceConfig': {'snippetCount': 20, 's': [symbol]}})
                response.raise_for_status()
                raw = response.json()['data']['tickerStream']['stream']
            else:
                raw = ticker.get_sec_filings()
        # yfinance represents missing filings as an empty dictionary.
        if kind == 'sec' and raw == {}:
            raw = []
        value['items'] = normalize(raw, kind)
    except Exception as exc:
        failure('yahoo', 'news_' + kind, symbol=symbol, error=exc)
        value['errors'] = ['该来源暂时无法获取，请稍后重试']
    return value
