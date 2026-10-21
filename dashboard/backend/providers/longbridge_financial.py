"""Quarterly Longbridge observations; never mix periods or substitute Net FCF."""
from datetime import datetime, timezone
import os
import re
import threading
from zoneinfo import ZoneInfo
from backend.domain.metrics import number
from backend.providers import longbridge as lb

SOURCE = 'https://open.longbridge.com/docs/fundamental/fundamental/financial-report'
_lock = threading.Lock()
_client = None


def client():
    global _client
    with _lock:
        if _client is None:
            from longbridge.openapi import HttpClient
            _client = HttpClient.from_apikey(*[os.environ['LONGBRIDGE_' + key]
                for key in ('APP_KEY', 'APP_SECRET', 'ACCESS_TOKEN')])
        return _client


def read_statement(symbol, kind):
    data = client().request('GET',
        f'/v1/quote/financials/statements?symbol={symbol}.US&kind={kind}&report=qf')
    if not isinstance(data, dict) or not data.get('list'):
        raise ValueError('Empty quarterly statement')
    return data


def normalize(blocks):
    """Prefer detailed values for the exact same quarter; missing stays missing."""
    series = {key: {} for key in ('revenue', 'gross_margin', 'operating_margin',
                                  'capex', 'fcf', 'debt', 'eps')}
    currency = blocks.get('statement_IS', {}).get('data', {}).get('currency') or blocks.get('statement_CF', {}).get('data', {}).get('currency')
    raw = {}
    errors = []
    times = []
    def put(key, period, value, block, field, basis=None):
        value = number(value)
        if value is None or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', period or '') or period > datetime.now(timezone.utc).date().isoformat():
            return
        raw.setdefault(key, {})[period] = dict(value=value, period=period, source=SOURCE,
            basis=basis or '长桥单季财务：' + field, source_field=field,
            fetched_at=block.get('fetched_at'), stale=bool(block.get('stale')),
            provider='longbridge', currency=currency, reason=None)
    for name, block in blocks.items():
        if block.get('failed') or block.get('stale'):
            errors.append('长桥 ' + name + ' 更新失败' + ('，保留上次成功数据' if block.get('stale') else ''))
        if block.get('fetched_at'):
            times.append(block['fetched_at'])
    generic = blocks.get('financial', {})
    mapping = {'OperatingRevenue':'revenue', 'OperatingIncome':'operating_income',
               'GrossMgn':'gross_percent', 'NetDebt':'debt',
               'NetOperateCashFlow':'ocf', 'CapEx':'capex'}
    for statement in generic.get('data', {}).get('list', {}).values():
        for indicator in statement.get('indicators', []):
            for account in indicator.get('accounts', []):
                key = mapping.get(account.get('field'))
                if key is None:
                    continue
                for entry in account.get('values', []):
                    if not re.fullmatch(r'Q[1-4] \d{4}', entry.get('period', '')) or not entry.get('fp_end'):
                        continue
                    period = datetime.fromtimestamp(int(entry['fp_end']), ZoneInfo('America/New_York')).date().isoformat()
                    put(key, period, entry.get('value'), generic, account['field'])
    detail_fields = {'IS': {'rev':'revenue', 'gp':'gross_profit', 'oper_inc':'operating_income'},
                     'CF': {'cash_oper':'ocf', 'capex':'capex'}}
    for kind, fields in detail_fields.items():
        block = blocks.get('statement_' + kind, {})
        for row in block.get('data', {}).get('list', []):
            if not re.fullmatch(r'Q[1-4] \d{4}', row.get('report_txt', '')):
                continue
            for entry in row.get('fields', []):
                if entry.get('field') in fields:
                    put(fields[entry['field']], row.get('fp_end'), entry.get('value'),
                        block, entry['field'])
    for key in ('revenue', 'debt'):
        series[key] = raw.get(key, {})
    for metric in series['debt'].values():
        metric['basis'] = '长桥 NetDebt：财季末净债务；负值表示供应商口径下的净现金，不是 Total Debt'
    for period, revenue in series['revenue'].items():
        for key, numerator in [('gross_margin', 'gross_profit'), ('operating_margin', 'operating_income')]:
            item = raw.get(numerator, {}).get(period)
            if item is not None:
                series[key][period] = {**item, 'value':item['value']/revenue['value'] if revenue['value']>0 else None,
                    'currency':None, 'basis':('毛利率' if key=='gross_margin' else '营业利润率')+' = 同季度利润 / 营收',
                    'reason':None if revenue['value']>0 else '营收非正，利润率不适用',
                    'stale':item.get('stale') or revenue.get('stale'),
                    'inputs':{'numerator':item['value'],'revenue':revenue['value']}}
            elif key == 'gross_margin' and period in raw.get('gross_percent', {}):
                item = raw['gross_percent'][period]
                series[key][period] = {**item, 'value':item['value']/100, 'currency':None,
                                      'basis':'长桥 GrossMgn / 100；供应商利润率口径'}
    for period, item in raw.get('capex', {}).items():
        series['capex'][period] = {**item, 'value':abs(item['value']),
            'basis':'单季资本开支；现金流出取正数，不扣除补助等抵减项目',
            'inputs':{'reported_capex':item['value']}}
        ocf = raw.get('ocf', {}).get(period)
        if ocf is not None:
            series['fcf'][period] = {**item, 'value':ocf['value']-abs(item['value']),
                'basis':'FCF = 同季度经营现金流 − abs(CapEx)；非 GAAP；未使用长桥 NetFreeCashFlow',
                'fetched_at':min(item.get('fetched_at') or '', ocf.get('fetched_at') or ''),
                'stale':bool(item.get('stale') or ocf.get('stale')),
                'inputs':{'operating_cash_flow':ocf['value'],'capital_expenditure':abs(item['value'])}}
    return {'series':series, 'errors':errors, 'fetched_at':min(times) if times else None, 'currency':currency}


def snapshot(symbol, store, force=False):
    """Reuse EPS raw blocks, existing limiter and durable, coalesced caches."""
    from longbridge.openapi import FinancialReportKind, FinancialReportPeriod
    _, ctx = lb.contexts()
    actions = [('financial', lambda: lb._plain(lb._fundamental_call(
        lambda: ctx.financial_report(symbol+'.US', FinancialReportKind.All, FinancialReportPeriod.QuarterlyFull))))]
    actions += [('statement_' + kind, lambda kind=kind: lb._fundamental_call(
        lambda: read_statement(symbol, kind))) for kind in ('IS', 'CF')]
    blocks = {}
    for name, action in actions:
        try:
            blocks[name] = lb._cached(symbol, name, action, store, lb.FUNDAMENTAL_TTL, force)
        except Exception:
            blocks[name] = {'data':{}, 'failed':True}
    return normalize(blocks)
