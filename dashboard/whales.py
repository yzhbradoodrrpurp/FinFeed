"""SEC as-filed 13F holdings. No third-party estimates or CUSIP guessing."""
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
import re
import threading
import time
from urllib.request import Request, build_opener, ProxyHandler
from xml.etree import ElementTree as ET
from failure_log import failure

FUNDS = {'berkshire': ('1067983', '伯克希尔'), 'pershing': ('1336528', 'Pershing Square')}
_guard = threading.Lock()
_last_request = 0.0
# Public project maintainer contact; override for another deployment/operator.
USER_AGENT = 'FinFeed Research zhihangyi0224@gmail.com'


def fetch(url, deadline):
    global _last_request
    started = time.monotonic()
    try:
        # One shared SEC limiter, comfortably below SEC's 10 requests/second.
        with _guard:
            delay = max(0, _last_request + .25 - time.monotonic())
            if delay:
                time.sleep(delay)
            _last_request = time.monotonic()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('SEC 13F 总请求时间超过 30 秒')
        proxy = os.environ.get('SEC_PROXY_URL')
        opener = build_opener(ProxyHandler({'https': proxy} if proxy else {}))
        with opener.open(Request(url, headers={'User-Agent': os.environ.get('SEC_USER_AGENT', USER_AGENT),
                                               'Accept-Encoding': 'identity'}), timeout=min(30, remaining)) as response:
            data = response.read(20_000_001)
        if len(data) > 20_000_000:
            raise ValueError('SEC 文件超过大小限制')
        return data.decode('utf-8-sig')
    except Exception as exc:
        failure('sec_edgar', '13f_download', error=exc, started=started)
        raise


def filings(data):
    rows = data.get('filings', {}).get('recent', data)
    result = []
    for i, form in enumerate(rows.get('form', [])):
        if form in {'13F-HR', '13F-HR/A'}:
            result.append({'form': form, 'filed_at': rows['filingDate'][i],
                           'report_date': rows['reportDate'][i], 'accession': rows['accessionNumber'][i],
                           'accepted_at': rows.get('acceptanceDateTime', rows['filingDate'])[i]})
    return result


def text(node, name):
    return next((item.text.strip() for item in node.iter() if item.tag.rsplit('}', 1)[-1] == name and item.text), '')


def parse_submission(raw, filed_at):
    documents = [ET.fromstring(part.strip()) for part in re.findall(r'<XML>\s*(.*?)\s*</XML>', raw, re.S | re.I)]
    cover = next((root for root in documents if text(root, 'tableEntryTotal')), None)
    tables = [row for root in documents for row in root.iter() if row.tag.rsplit('}', 1)[-1] == 'infoTable']
    if cover is None or not tables:
        raise ValueError('SEC 13F 缺少封面或持仓表')
    multiplier = 1000 if filed_at < '2023-01-03' else 1
    rows = []
    for row in tables:
        amount, value = Decimal(text(row, 'sshPrnamt')), Decimal(text(row, 'value')) * multiplier
        if amount < 0 or value < 0 or not amount.is_finite() or not value.is_finite():
            raise ValueError('SEC 13F 数值无效')
        rows.append({'name': text(row, 'nameOfIssuer'), 'class': text(row, 'titleOfClass'),
                     'cusip': text(row, 'cusip'), 'put_call': text(row, 'putCall'),
                     'amount_type': text(row, 'sshPrnamtType'), 'shares': int(amount), 'value': int(value)})
    if len(rows) != int(text(cover, 'tableEntryTotal')):
        raise ValueError('SEC 13F 持仓条目数量不一致')
    if sum(row['value'] for row in rows) != int(Decimal(text(cover, 'tableValueTotal')) * multiplier):
        raise ValueError('SEC 13F 持仓市值合计不一致')
    return rows, text(cover, 'amendmentType')


def aggregate(rows):
    combined = {}
    for row in rows:
        key = (row['cusip'], row['class'], row['put_call'], row['amount_type'])
        if key not in combined:
            combined[key] = {**row, 'shares': 0, 'value': 0}
        combined[key]['shares'] += row['shares']
        combined[key]['value'] += row['value']
    total = sum(row['value'] for row in combined.values())
    if not total:
        raise ValueError('SEC 13F 市值合计为空')
    return [{**row, 'weight': row['value'] / total * 100}
            for row in sorted(combined.values(), key=lambda row: row['value'], reverse=True)]


def snapshot(kind):
    cik, name = FUNDS[kind]
    deadline = time.monotonic() + 30
    try:
        data = json.loads(fetch(f'https://data.sec.gov/submissions/CIK{int(cik):010d}.json', deadline))
        available = filings(data)
        # Small filers can have current 13Fs in an older submissions page.
        if not available:
            for page in data.get('filings', {}).get('files', [])[:2]:
                available.extend(filings(json.loads(fetch('https://data.sec.gov/submissions/' + page['name'], deadline))))
                if available:
                    break
        bases = [row for row in available if row['form'] == '13F-HR']
        if not bases:
            raise ValueError('SEC 未找到 13F 持仓报告')
        latest = max(bases, key=lambda row: (row['report_date'], row['accepted_at'], row['accession']))
        selected = [latest] + sorted([row for row in available if row['form'] == '13F-HR/A'
            and row['report_date'] == latest['report_date'] and (row['accepted_at'], row['accession']) > (latest['accepted_at'], latest['accession'])],
            key=lambda row: (row['accepted_at'], row['accession']))
        holdings, sources = [], []
        for filing in selected:
            accession = filing['accession']
            url = f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace("-", "")}/{accession}.txt'
            rows, amendment = parse_submission(fetch(url, deadline), filing['filed_at'])
            if filing['form'] == '13F-HR' or amendment.upper() == 'RESTATEMENT':
                holdings = rows
            elif amendment.upper() == 'NEW HOLDINGS':
                holdings.extend(rows)
            else:
                raise ValueError('SEC 13F 修订类型无法确认')
            sources.append({**filing, 'url': url, 'amendment': amendment})
        rows = aggregate(holdings)
        return {'fund': kind, 'name': name, 'cik': cik, 'report_date': latest['report_date'],
                'filed_at': selected[-1]['filed_at'], 'currency': 'USD', 'holdings': rows,
                'total_value': sum(row['value'] for row in rows), 'sources': sources,
                'retrieved_at': datetime.now(timezone.utc).isoformat(), 'errors': []}
    except Exception as exc:
        failure('sec_edgar', '13f_snapshot', symbol=kind, error=exc)
        return {'fund': kind, 'name': name, 'holdings': [], 'errors': ['SEC 持仓读取失败，保留已取得的数据'],
                'retrieved_at': datetime.now(timezone.utc).isoformat()}
