"""SEC as-filed 13F holdings. No third-party estimates or CUSIP guessing."""
from datetime import datetime, timezone
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
import json
import os
import re
import threading
import time
from urllib.request import Request, build_opener, ProxyHandler
from xml.etree import ElementTree as ET
from backend.infrastructure.failure_log import failure

FUNDS = {'berkshire': ('1067983', '伯克希尔'), 'pershing': ('1336528', '潘兴广场'),
         'appaloosa': ('1656456', '阿帕卢萨管理'),
         'ark': ('1697748', '方舟投资'), 'coatue': ('1135730', '蔻图资本'),
         'altimeter': ('1541617', '阿尔蒂米特资本'), 'tiger': ('1167483', '老虎环球基金'),
         'polar': ('1837309', '北极星资本'), 'alkeon': ('1230239', '阿尔基昂资本'),
         'westfield': ('1177719', '韦斯特菲尔德资本'),
         'lightstreet': ('1569049', '光街资本'), 'hmi': ('1469026', 'HMI 资本'),
         'atika': ('1599731', '阿提卡资本'),
         'dorsey': ('1671657', '多西资产管理'), 'altarock': ('1631014', '阿尔塔洛克资本'),
         'broadrun': ('1568621', '布罗德朗投资管理')}
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
        if form in {'13F-HR', '13F-HR/A', '13F-NT', '13F-NT/A'}:
            result.append({'form': form, 'filed_at': rows['filingDate'][i],
                           'report_date': rows['reportDate'][i], 'accession': rows['accessionNumber'][i],
                           'accepted_at': rows.get('acceptanceDateTime', rows['filingDate'])[i]})
    return result


def text(node, name):
    return next((item.text.strip() for item in node.iter() if item.tag.rsplit('}', 1)[-1] == name and item.text), '')


def parse_submission(raw, filed_at, diagnostics=None):
    documents = [ET.fromstring(part.strip()) for part in re.findall(r'<XML>\s*(.*?)\s*</XML>', raw, re.S | re.I)]
    cover = next((root for root in documents if text(root, 'tableEntryTotal')), None)
    tables = [row for root in documents for row in root.iter() if row.tag.rsplit('}', 1)[-1] == 'infoTable']
    if cover is None or not tables:
        raise ValueError('SEC 13F 缺少封面或持仓表')
    multiplier = 1000 if filed_at < '2023-01-03' else 1
    rows = []
    for row in tables:
        amount, value = Decimal(text(row, 'sshPrnamt')), Decimal(text(row, 'value')) * multiplier
        if not amount.is_finite() or not value.is_finite() or amount < 0 or value < 0 or amount != amount.to_integral_value() or value != value.to_integral_value():
            raise ValueError('SEC 13F 数值无效')
        rows.append({'name': text(row, 'nameOfIssuer'), 'class': text(row, 'titleOfClass'),
                     'cusip': text(row, 'cusip'), 'put_call': text(row, 'putCall'),
                     'amount_type': text(row, 'sshPrnamtType'), 'shares': int(amount), 'value': int(value)})
    if Decimal(text(cover, 'tableEntryTotal')) != len(rows):
        raise ValueError('SEC 13F 持仓条目数量不一致')
    detail_total = sum(row['value'] for row in rows)
    cover_value = Decimal(text(cover, 'tableValueTotal')) * multiplier
    if not cover_value.is_finite() or cover_value < 0 or cover_value != cover_value.to_integral_value():
        raise ValueError('SEC 13F 封面市值无效')
    cover_total = int(cover_value)
    if detail_total != cover_total:
        message = f'SEC 13F 持仓市值合计不一致：封面 {cover_total:,}，明细 {detail_total:,}，差额 {detail_total - cover_total:+,} 美元'
        failure('sec_edgar', '13f_total_mismatch', reason=message,
                cover_total=cover_total, detail_total=detail_total, difference=detail_total - cover_total)
        raise ValueError(message)

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


def previous_quarter(report_date):
    day = date.fromisoformat(report_date)
    first_month = (day.month - 1) // 3 * 3 + 1
    return (date(day.year, first_month, 1) - timedelta(days=1)).isoformat()


def quarter(cik, available, report_date, deadline):
    bases = [row for row in available if row['form'] == '13F-HR' and row['report_date'] == report_date]
    if not bases:
        return None
    latest = max(bases, key=lambda row: (row['accepted_at'], row['accession']))
    selected = [latest] + sorted([row for row in available if row['form'] == '13F-HR/A'
        and row['report_date'] == report_date and (row['accepted_at'], row['accession']) > (latest['accepted_at'], latest['accession'])],
        key=lambda row: (row['accepted_at'], row['accession']))
    holdings, sources, warnings = [], [], []
    for filing in selected:
        accession = filing['accession']
        filing_cik = filing.get('cik', cik)
        url = f'https://www.sec.gov/Archives/edgar/data/{int(filing_cik)}/{accession.replace("-", "")}/{accession}.txt'
        rows, amendment = parse_submission(fetch(url, deadline), filing['filed_at'], warnings)
        if filing['form'] == '13F-HR' or amendment.upper() == 'RESTATEMENT':
            holdings = rows
        elif amendment.upper() == 'NEW HOLDINGS':
            holdings.extend(rows)
        else:
            raise ValueError('SEC 13F 修订类型无法确认')
        sources.append({**filing, 'url': url, 'amendment': amendment})
    rows = aggregate(holdings)
    return {'report_date': report_date, 'filed_at': selected[-1]['filed_at'], 'holdings': rows,
            'total_value': sum(row['value'] for row in rows), 'sources': sources, 'warnings': warnings,
            'totals_verified': True}


def compare(current, previous):
    # CUSIP identifies the security; issuer/class wording can change between filings.
    # Keep options and principal amounts separate from common stock quantities.
    def indexed(rows):
        result = {}
        for row in rows:
            key = (row['cusip'].strip().upper(), row['put_call'].upper(), row['amount_type'].upper())
            if key not in result:
                result[key] = {**row, 'shares': 0, 'value': 0, 'weight': 0}
            for field in ('shares', 'value', 'weight'):
                result[key][field] += row[field]
        return result
    now, before = indexed(current['holdings']), indexed(previous['holdings'])
    changes = []
    for key in now.keys() | before.keys():
        new, old = now.get(key), before.get(key)
        new_amount, old_amount = (new or {}).get('shares', 0), (old or {}).get('shares', 0)
        delta = new_amount - old_amount
        status = ('new' if new_amount > 0 and old_amount == 0 else
                  'exit' if new_amount == 0 and old_amount > 0 else
                  'increase' if delta > 0 else 'decrease' if delta < 0 else 'unchanged')
        changes.append({**(new or old), 'status': status, 'current_shares': new_amount,
            'previous_shares': old_amount, 'shares_change': delta,
            'shares_change_percent': delta / old_amount * 100 if old_amount else None,
            'current_value': (new or {}).get('value', 0), 'previous_value': (old or {}).get('value', 0),
            'current_weight': (new or {}).get('weight', 0), 'previous_weight': (old or {}).get('weight', 0),
            'weight_change': (new or {}).get('weight', 0) - (old or {}).get('weight', 0)})
    return sorted(changes, key=lambda row: (-max(row['current_value'], row['previous_value']), row['cusip']))


def snapshot(kind, on_update=None):
    cik, name = FUNDS[kind]
    deadline = time.monotonic() + 30
    result = {'fund': kind, 'name': name, 'cik': cik, 'schema_version': 3, 'currency': 'USD',
              'holdings': [], 'previous': None, 'changes': [], 'previous_status': 'loading',
              'retrieved_at': datetime.now(timezone.utc).isoformat(), 'errors': []}
    try:
        data = json.loads(fetch(f'https://data.sec.gov/submissions/CIK{int(cik):010d}.json', deadline))
        available = filings(data)
        for page in data.get('filings', {}).get('files', [])[:2]:
            if len({row['report_date'] for row in available if row['form'] == '13F-HR'}) >= 2:
                break
            available.extend(filings(json.loads(fetch('https://data.sec.gov/submissions/' + page['name'], deadline))))
        # A notice can redirect holdings to another reporting manager.
        latest_hr = max((row['report_date'] for row in available if row['form'] == '13F-HR'), default='')
        notices = [row for row in available if row['form'] in {'13F-NT', '13F-NT/A'}
                   and row['report_date'] > latest_hr]
        if notices:
            notice = max(notices, key=lambda row: (row['report_date'], row['accepted_at']))
            accession = notice['accession']
            notice_url = f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace("-", "")}/{accession}.txt'
            raw = fetch(notice_url, deadline)
            roots = [ET.fromstring(part.strip()) for part in re.findall(r'<XML>\s*(.*?)\s*</XML>', raw, re.S | re.I)]
            managers = [node for root in roots for node in root.iter()
                        if node.tag.rsplit('}', 1)[-1] == 'otherManager' and text(node, 'cik')]
            if len(managers) != 1:
                raise ValueError('SEC 13F 通知未指定唯一申报主体，不能合并猜测')
            manager_cik, manager_name = text(managers[0], 'cik'), text(managers[0], 'name')
            if not manager_cik.isdigit() or int(manager_cik) == int(cik):
                raise ValueError('SEC 13F 通知中的申报主体无效')
            parent = json.loads(fetch(f'https://data.sec.gov/submissions/CIK{int(manager_cik):010d}.json', deadline))
            parent_filings = filings(parent)
            if not any(row['form'] == '13F-HR' and row['report_date'] == notice['report_date'] for row in parent_filings):
                raise ValueError('SEC 13F 通知指定主体尚未取得对应季度持仓报告')
            # Use the same reporting scope for both comparison quarters.
            available = [{**row, 'cik': manager_cik} for row in parent_filings]
            result['reporting_manager'] = manager_name
            result['reporting_notice'] = {'url': notice_url, **notice}
            result['reporting_warning'] = f"原主体自 {notice['report_date']} 起通过 13F-NT 指定 {manager_name} 申报；当前及上季度均读取该主体的报告。本季申报范围发生整合，新建仓、增持及仓位变化可能来自披露范围变化，不能直接视为实际交易。"
        periods = sorted({row['report_date'] for row in available if row['form'] == '13F-HR'}, reverse=True)
        if not periods:
            raise ValueError('SEC 未找到 13F 持仓报告')
        latest_date, previous_date = periods[0], previous_quarter(periods[0])
        result['previous_report_date'] = previous_date
        completed = {}
        # Each quarter loads independently; do not delay displaying the current quarter.
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {pool.submit(quarter, cik, available, period, deadline): label
                       for label, period in [('current', latest_date), ('previous', previous_date)]}
            for future in as_completed(futures):
                label = futures[future]
                try:
                    completed[label] = future.result()
                except Exception as exc:
                    failure('sec_edgar', '13f_quarter', symbol=kind, error=exc, report_date=latest_date if label == 'current' else previous_date)
                    if label == 'current':
                        raise
                    completed[label] = None
                    result['errors'] = ['上季度 SEC 持仓读取失败，暂不计算变化']
                if completed.get('current'):
                    result.update(completed['current'])
                    result['previous'] = completed.get('previous')
                    result['partial'] = len(completed) < 2
                    result['previous_status'] = ('loading' if result['partial'] else
                        'failed' if result['errors'] else 'available' if result['previous'] else 'missing')
                    result['changes'] = compare(result, result['previous']) if result['previous'] else []
                    if on_update and result['partial']:
                        on_update(dict(result))
        result['retrieved_at'] = datetime.now(timezone.utc).isoformat()
        return result
    except Exception as exc:
        failure('sec_edgar', '13f_snapshot', symbol=kind, error=exc)
        return {**result, 'partial': False, 'previous_status': 'failed',
                'errors': ['SEC 持仓读取失败，保留已取得的数据' if result['holdings'] else 'SEC 持仓读取失败，暂未取得有效数据']}
