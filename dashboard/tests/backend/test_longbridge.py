"""Provider selection, EPS fiscal alignment, valuation and stale-cache boundaries."""
import unittest
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

from backend.providers import longbridge as lb
from backend.services import securities


def financial():
    values = []
    for label, end in [('Q2 2026', '2026-06-30'), ('Q1 2026', '2026-03-31')]:
        stamp = int(datetime.fromisoformat(end + 'T04:00:00+00:00').timestamp())
        values.append(dict(period=label, fp_end=str(stamp), value='100'))
    return {'list': {'IS': {'indicators': [{'accounts': [{'field': 'OperatingRevenue', 'values': values}]}]}}}


def consensus(missing=None):
    values = [('Q2 2026', True, 2), ('Q1 2026', True, 1), ('Q3 2026', False, 3),
              ('Q4 2026', False, 4), ('Q1 2027', False, 5), ('Q2 2027', False, 6)]
    return {'currency': 'USD', 'list': [{'period_text': label, 'details': [
        {'key': 'eps', 'is_released': actual, 'actual': value if actual else None,
         'estimate': value if not actual else None}]} for label, actual, value in values if label != missing]}


def blocks(missing=None):
    quote_day = datetime(2026, 10, 2, 4, tzinfo=timezone.utc)
    bars = [{'timestamp': (quote_day-timedelta(days=i)).isoformat(), 'high': 110,
             'low': 90, 'volume': 200 if i == 0 else 100} for i in range(11)]
    raw = {'static': {'currency': 'USD', 'exchange': 'NASD', 'name_en': 'Example'},
           'quote': {'timestamp': '2026-10-02T20:00:00+00:00', 'last_done': 100},
           'indexes': {'total_market_value': 10000, 'pe_ttm_ratio': 12.5},
           'bars': bars, 'financial': financial(), 'consensus': consensus(missing)}
    return {k: {'data': v, 'fetched_at': '2026-10-03T00:00:00+00:00'} for k, v in raw.items()}


class LongbridgeCases(unittest.TestCase):
    def setUp(self):
        cooldown = patch.object(lb, '_block_retry', {})
        cooldown.start();self.addCleanup(cooldown.stop)

    def test_many_users_share_one_forced_provider_request(self):
        import threading
        class Store:
            def __init__(self):self.data={}
            def get_cache(self,key):return self.data.get(key)
            def set_cache(self,key,value):self.data[key]=(value,time.time())
        store=Store();calls=[]
        def fetch():
            calls.append(1);time.sleep(.03);return {'price':100}
        with ThreadPoolExecutor(max_workers=12) as pool:
            results=list(pool.map(lambda _:lb._cached('SHARED','quote',fetch,store,60,True),range(12)))
        self.assertEqual(len(calls),1)
        self.assertTrue(all(r['data']['price']==100 for r in results))

    def test_failed_raw_block_has_one_minute_retry_cooldown(self):
        calls=[]
        def fail():calls.append(1);raise RuntimeError('offline')
        with patch.object(lb,'failure'):
            for _ in range(10):
                with self.assertRaises(RuntimeError):lb._cached('NO-CACHE','consensus',fail,None,300,True)
        self.assertEqual(len(calls),1)

    def test_quote_time_is_not_rewritten_by_financial_merge(self):
        b=blocks();b['quote']['fetched_at']='2026-10-02T22:00:00+00:00'
        r=lb.normalize('QA',b,'2026-10-03T00:00:00+00:00','EQUITY')
        self.assertEqual(r['fetched_at'],b['quote']['fetched_at'])
        self.assertEqual(r['provider_blocks']['consensus']['fetched_at'],b['consensus']['fetched_at'])

    def test_scheduled_market_force_respects_fundamental_cache_ttl(self):
        fixture=blocks()
        for manual in (False,True):
            seen={}
            def cached(symbol,name,action,store,ttl,force):
                seen[name]=(ttl,force);return fixture[name]
            with patch.object(lb,'contexts',return_value=(None,None)),patch.object(lb,'_cached',side_effect=cached):
                lb.market_snapshot('QA',None,'EQUITY',True,financial_refresh=manual)
            self.assertEqual(seen['quote'],(60,True))
            self.assertEqual(seen['consensus'],(300,manual))
            self.assertEqual(seen['financial'],(300,manual))

    def test_yahoo_failure_does_not_restore_intentionally_unavailable_forward_pe(self):
        from unittest.mock import MagicMock
        from copy import deepcopy
        saved={'schema_version':securities.SCHEMA_VERSION,'market_provider':'longbridge',
               'fetched_at':securities.now(),'metrics':{'price':{'value':100},'pe_forward_4q':{'value':20}}}
        for failed in (False,True):
            result={'schema_version':securities.SCHEMA_VERSION,'market_provider':'longbridge',
                    'fetched_at':securities.now(),'errors':['Longbridge consensus failed' if failed else 'Yahoo financial failed'],
                    'metrics':{'price':{'value':101},'pe_forward_4q':{'value':None,'stale':failed}}}
            store=MagicMock();store.get_cache.return_value=(deepcopy(saved),time.time()-120)
            with patch.object(securities,'fetch_security',return_value=result):
                value=securities.security('ISOLATED',refresh=True,store=store)
            self.assertEqual(value['metrics']['pe_forward_4q']['value'],20 if failed else None)
    def test_ttm_is_vendor_index_and_forward_is_two_actual_two_forecasts(self):
        r = lb.normalize('QA', blocks(), '2026-10-03T00:00:00+00:00', 'EQUITY')
        self.assertEqual(r['metrics']['pe_ltm']['value'], 12.5)
        self.assertAlmostEqual(r['metrics']['pe_forward_4q']['value'], 100/10)
        self.assertEqual(r['metrics']['eps_q0']['value'], 2)
        self.assertEqual(r['metrics']['eps_q1']['value'], 1)
        self.assertEqual(r['metrics']['forward_eps_next']['estimate_label'], 'Q3 2026')
        self.assertEqual(r['metrics']['relative_volume_10']['value'], 2)

    def test_missing_future_quarter_never_substitutes_actual_or_skips_gap(self):
        r = lb.normalize('QA', blocks('Q4 2026'), '2026-10-03T00:00:00+00:00', 'EQUITY')
        self.assertIsNone(r['metrics']['pe_forward_4q']['value'])
        self.assertEqual(r['metrics']['forward_eps_next']['value'], 3)
        self.assertIn('未来两个', r['metrics']['pe_forward_4q']['reason'])

    def test_negative_forecast_quarter_is_allowed_when_four_quarter_sum_positive(self):
        b = blocks();b['consensus']['data']['list'][2]['details'][0]['estimate'] = -3
        r = lb.normalize('QA', b, '2026-10-03T00:00:00+00:00', 'EQUITY')
        self.assertAlmostEqual(r['metrics']['pe_forward_4q']['value'], 100/4)
        for item in b['consensus']['data']['list'][2:]:item['details'][0]['estimate'] = -1
        r = lb.normalize('QA', b, '2026-10-03T00:00:00+00:00', 'EQUITY')
        self.assertAlmostEqual(r['metrics']['pe_forward_4q']['value'], 100)

    def test_signed_pe_and_zero_denominators(self):
        b = blocks();b['indexes']['data']['pe_ttm_ratio'] = -12.5
        for row in b['consensus']['data']['list'][2:]:row['details'][0]['estimate'] = -4
        r = lb.normalize('QA', b, '2026-10-03T00:00:00+00:00', 'EQUITY')
        self.assertEqual(r['metrics']['pe_ltm']['value'], -12.5)
        self.assertEqual(r['metrics']['pe_forward_4q']['value'], -20)
        self.assertIn('负', r['metrics']['pe_forward_4q']['valuation_status'])
        for row in b['consensus']['data']['list'][2:]:row['details'][0]['estimate'] = -1.5
        r = lb.normalize('QA', b, '2026-10-03T00:00:00+00:00', 'EQUITY')
        self.assertIsNone(r['metrics']['pe_forward_4q']['value'])
        self.assertIn('为零', r['metrics']['pe_forward_4q']['reason'])
        for missing in ('Q1 2026', 'Q2 2026'):
            r = lb.normalize('QA', blocks(missing), '2026-10-03T00:00:00+00:00', 'EQUITY')
            self.assertIsNone(r['metrics']['pe_forward_4q']['value'])

    def test_currency_mismatch_etf_and_intraday_not_applicable(self):
        b = blocks();b['consensus']['data']['currency'] = 'EUR'
        r = lb.normalize('QA', b, '2026-10-03T00:00:00+00:00', 'EQUITY')
        self.assertIsNone(r['metrics']['pe_forward_4q']['value'])
        r = lb.normalize('QA', blocks(), '2026-10-02T18:00:00+00:00', 'ETF')
        for key in ('eps_q0', 'market_cap', 'pe_ltm', 'pe_forward_4q', 'relative_volume_10'):
            self.assertIsNone(r['metrics'][key]['value'])

    def test_overlay_does_not_change_quarterly_financial_anchors(self):
        market = lb.normalize('QA', blocks(), '2026-10-03T00:00:00+00:00', 'EQUITY')
        r = {'ticker': 'QA', 'quarter_0': '2026-03-31', 'quarter_1': '2025-12-31',
             'metrics': {'revenue_q0': {'value': 80}}, 'series': {},
             'fetched_at': market['fetched_at'], 'longbridge_market': market}
        with patch.object(securities, 'next_forecast', side_effect=AssertionError('Yahoo forecast must not run')):
            securities.revalue(r)
        self.assertEqual(r['quarter_0'], '2026-03-31')
        self.assertEqual(r['metrics']['revenue_q0']['value'], 80)
        self.assertEqual(r['market_quarter_0'], '2026-06-30')
        self.assertEqual(r['metrics']['pe_quarter'], r['metrics']['pe_ltm'])

    def test_failed_component_retains_successful_provider_block(self):
        class Store:
            def get_cache(self, key):return ({'data': {'value': 5}, 'fetched_at': '2026-10-01T00:00:00Z'}, 0)
            def set_cache(self, *args):raise AssertionError('Must not write failed refresh')
        with patch.object(lb, 'failure'):
            r = lb._cached('QA', 'consensus', lambda: (_ for _ in ()).throw(RuntimeError('offline')), Store(), 60)
        self.assertTrue(r['stale']);self.assertEqual(r['data']['value'], 5)

    def test_stale_forecasts_and_52week_range_are_labelled(self):
        b = blocks();b['consensus']['stale'] = True;b['bars']['stale'] = True
        r = lb.normalize('QA', b, '2026-10-03T00:00:00+00:00', 'EQUITY')
        self.assertTrue(r['metrics']['pe_forward_4q']['stale'])
        self.assertTrue(r['metrics']['high_52w']['stale'])
        self.assertTrue(r['errors'])

    def test_unused_future_quarter_is_not_required_but_both_actuals_are(self):
        r = lb.normalize('QA', blocks('Q2 2027'), '2026-10-03T00:00:00+00:00', 'EQUITY')
        self.assertAlmostEqual(r['metrics']['pe_forward_4q']['value'], 100/10)
        r = lb.normalize('QA', blocks('Q2 2026'), '2026-10-03T00:00:00+00:00', 'EQUITY')
        self.assertIsNone(r['metrics']['pe_forward_4q']['value'])

    def test_database_outage_does_not_discard_fresh_provider_data(self):
        class Store:
            def get_cache(self, key):raise RuntimeError('database offline')
            def set_cache(self, *args):raise RuntimeError('database offline')
        with patch.object(lb, 'failure'):
            r = lb._cached('QA', 'quote', lambda: {'price': 99}, Store(), 60)
        self.assertEqual(r['data']['price'], 99)

    def test_parallel_fundamental_requests_respect_one_second_quota(self):
        with patch.object(lb, '_fundamental_last', 0), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(lb._fundamental_call, time.monotonic)
            second = pool.submit(lb._fundamental_call, time.monotonic)
            starts = sorted([first.result(), second.result()])
        self.assertGreaterEqual(starts[1] - starts[0], 1.0)

    def test_cutover_failure_does_not_relabel_old_quarterly_pe(self):
        from unittest.mock import MagicMock
        saved = {'schema_version': 8, 'metrics': {'price': {'value': 100},
                 'pe_quarter': {'value': 25}}, 'fetched_at': securities.now()}
        store = MagicMock();store.get_cache.return_value = (saved, time.time()-120)
        with patch.object(securities, 'fetch_security', side_effect=RuntimeError('offline')), patch.object(securities, 'failure'):
            r = securities.security('QA', store=store)
        self.assertTrue(r['stale'])
        self.assertEqual(r['metrics']['price']['value'], 100)
        self.assertIsNone(r['metrics']['pe_ltm']['value'])
        self.assertIsNone(r['metrics']['pe_forward_4q']['value'])
        store.set_cache.assert_not_called()

if __name__ == '__main__':unittest.main()
