"""Official SEC EDGAR company submissions, using the shared SEC fair-access limiter."""
from datetime import datetime
import json
import re
import threading
import time
from urllib.parse import quote
from backend.services.whales import fetch

_lock = threading.Lock()
_tickers = None
_loaded = 0


def company_cik(symbol, deadline):
    global _tickers, _loaded
    with _lock:
        if _tickers is None or time.monotonic() - _loaded > 86400:
            data = json.loads(fetch('https://www.sec.gov/files/company_tickers.json', deadline))
            if not isinstance(data, dict) or not data:
                raise ValueError('Invalid SEC ticker map')
            mapping = {}
            for row in data.values():
                if not isinstance(row, dict) or not isinstance(row.get('ticker'), str) or not str(row.get('cik_str', '')).isdigit():
                    raise ValueError('Invalid SEC ticker row')
                mapping[row['ticker'].upper().replace('.', '-')] = int(row['cik_str'])
            _tickers, _loaded = mapping, time.monotonic()
        return _tickers.get(symbol.upper().replace('.', '-'))


def submission_items(data, cik):
    rows = data.get('filings', {}).get('recent', data)
    required = ('accessionNumber', 'form', 'filingDate', 'primaryDocument', 'acceptanceDateTime')
    if not isinstance(rows, dict) or any(not isinstance(rows.get(k), list) for k in required):
        raise ValueError('Invalid SEC submissions schema')
    size = len(rows['form'])
    if any(len(rows[k]) != size for k in required):
        raise ValueError('Misaligned SEC submissions columns')
    for key in ('reportDate', 'acceptanceDateTime'):
        if key in rows and (not isinstance(rows[key], list) or len(rows[key]) != size):
            raise ValueError('Misaligned SEC metadata columns')
    items = {}
    for i in range(size):
        accession, form, day, document, accepted = (rows[k][i] for k in required)
        if not isinstance(accession, str) or not re.fullmatch(r'\d{10}-\d{2}-\d{6}', accession):
            raise ValueError('Invalid SEC accession')
        if not isinstance(document, str) or document.startswith('/') or any(part in {'.', '..'} for part in document.split('/')):
            raise ValueError('Invalid SEC primary document')
        if not isinstance(form, str) or not form or not isinstance(day, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day):
            raise ValueError('Invalid SEC filing metadata')
        datetime.fromisoformat(day)
        if not isinstance(accepted, str) or datetime.fromisoformat(accepted.replace('Z', '+00:00')).tzinfo is None:
            raise ValueError('Invalid SEC acceptance timestamp')
        url = f'https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace("-", "")}/{quote(document or accession + '-index.html', safe="/._-")}'
        items[accession] = {'title': form, 'form': form, 'url': url, 'published_at': day,
            'accepted_at': accepted,
            'report_date': rows.get('reportDate', [''] * size)[i], 'accession': accession,
            'source': 'SEC EDGAR · 官方 API', 'kind': 'sec'}
    return sorted(items.values(), key=lambda r: (r['published_at'], r['accession']), reverse=True)


def index(symbol):
    deadline = time.monotonic() + 30
    cik = company_cik(symbol, deadline)
    if cik is None:
        return [], 'SEC 官方公司索引未覆盖该标的', None
    data = json.loads(fetch(f'https://data.sec.gov/submissions/CIK{cik:010d}.json', deadline))
    if int(data.get('cik', -1)) != cik:
        raise ValueError('SEC company identity mismatch')
    items = submission_items(data, cik)
    # The recent index includes at least one year or 1,000 filings. Obtain
    # older pages only when needed to anchor the page's two-report window.
    for page in data.get('filings', {}).get('files', []):
        if len({r['published_at'] for r in items if r['form'] in {'10-Q', '10-K', '20-F', '40-F'}}) >= 2:
            break
        name = page.get('name', '')
        if not re.fullmatch(r'CIK\d{10}-submissions-\d+\.json', name):
            raise ValueError('Invalid SEC submissions page')
        items.extend(submission_items(json.loads(fetch('https://data.sec.gov/submissions/' + name, deadline)), cik))
    return sorted({r['accession']: r for r in items}.values(), key=lambda r: (r['published_at'], r['accession']), reverse=True), '', cik
