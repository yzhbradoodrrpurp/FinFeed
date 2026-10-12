"""Minute refreshes update quotes, valuations, and financial statements together."""
import unittest
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch
import pandas as pd
import backend.services.securities as data
class RefreshCases(unittest.TestCase):
    def test_provider_limit_is_four(self):
        acquired = 0
        try:
            for _ in range(4):
                self.assertTrue(data.LIMIT.acquire(blocking=False))
                acquired += 1
            self.assertFalse(data.LIMIT.acquire(blocking=False))
        finally:
            for _ in range(acquired):
                data.LIMIT.release()

    def test_provider_requests_overlap_and_wait_at_global_limit(self):
        # Reserve most permits to test the real global limit with four threads.
        for _ in range(1):
            self.assertTrue(data.LIMIT.acquire(blocking=False))
            self.addCleanup(data.LIMIT.release)
        release = threading.Event()
        three_entered = threading.Event()
        guard = threading.Lock()
        active = 0
        peak = 0
        calls = 0

        def fetch(symbol, saved, estimate_store, force=False):
            nonlocal active, peak, calls
            with guard:
                active += 1
                calls += 1
                peak = max(peak, active)
                if active == 3:
                    three_entered.set()
            release.wait(3)
            with guard:
                active -= 1
            return {"ticker": symbol, "metrics": {"price": {"value": 100}}}

        store = MagicMock()
        store.get_cache.return_value = None
        with patch.object(data, 'fetch_security', side_effect=fetch), ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(data.security, symbol, store=store) for symbol in ('QA1', 'QA2', 'QA3', 'QA4')]
            try:
                self.assertTrue(three_entered.wait(2), 'Requests must overlap instead of serializing')
                self.assertEqual(calls, 3, 'Fourth request must wait for the provider limit')
            finally:
                release.set()
            self.assertTrue(all(f.result(timeout=3)['metrics']['price']['value'] == 100 for f in futures))
        self.assertEqual(peak, 3)
        self.assertEqual(calls, 4)

    def test_forced_refresh_bypasses_snapshot(self):
        saved={"schema_version":data.SCHEMA_VERSION,"financial_checked_at":data.now(),"metrics":{"price":{"value":100}}}
        store=MagicMock();store.get_cache.return_value=(saved,data.time.time()-20)
        with patch.object(data,"financial_due",return_value=False),patch.object(data,"fetch_security",return_value=saved) as fetch:
            results=[data.security("SHARED",refresh=True,store=store) for _ in range(3)]
            self.assertEqual(fetch.call_count,3)
        self.assertTrue(all(not r["cached"] for r in results))
        store.get_cache.return_value=(saved,data.time.time()-61)
        with patch.object(data,"financial_due",return_value=False),patch.object(data,"fetch_security",return_value=saved) as fetch:
            data.security("SHARED",refresh=True,store=store)
            fetch.assert_called_once()

    def setUp(self):
        alpha_patch = patch.object(data, "estimate_data", return_value=None)
        alpha_patch.start(); self.addCleanup(alpha_patch.stop)
        self.item = MagicMock()
        self.item.get_info.return_value = {'quoteType': 'EQUITY', 'currency': 'USD', 'financialCurrency': 'USD', 'regularMarketPrice': 100, 'regularMarketTime': 1790956800, 'trailingEps': 10}
        self.item.history.return_value = None
        self.item.get_history_metadata.return_value = {}
        frame = pd.DataFrame({pd.Timestamp('2026-06-30'): {'DilutedEPS': 2, 'TotalRevenue': 100, 'TotalDebt': 50, 'OperatingCashFlow': 20, 'CapitalExpenditure': -5}})
        for method in ('get_income_stmt', 'get_balance_sheet', 'get_cashflow'):
            getattr(self.item, method).return_value = frame
        self.item.get_earnings_estimate.return_value = pd.DataFrame({'avg': [3], 'numberOfAnalysts': [10]}, index=['0q'])
        self.item._analysis._earnings_trend = []
        self.ticker = patch.object(data.yf, 'Ticker', return_value=self.item)
        self.ticker.start()
        self.addCleanup(self.ticker.stop)

    def fetch(self, timestamp, saved=None):
        with patch.object(data, 'now', return_value=timestamp):
            return data._fetch_yahoo_security('QA', saved)

    def test_active_longbridge_route_keeps_statements_without_yahoo_market_calls(self):
        from test_longbridge import blocks
        market = data.longbridge.normalize('QA', blocks(), '2026-10-03T00:00:00+00:00', 'EQUITY')
        with patch.object(data.longbridge, 'market_snapshot', return_value=market):
            result = data.fetch_security('QA')
        for method in ('get_info', 'history', 'get_history_metadata', 'get_earnings_estimate', 'get_shares_full'):
            getattr(self.item, method).assert_not_called()
        self.item.get_income_stmt.assert_called_once()
        self.item.get_balance_sheet.assert_called_once()
        self.item.get_cashflow.assert_called_once()
        self.assertEqual(result['metrics']['revenue_q0']['value'], 100)
        self.assertEqual(result['metrics']['pe_ltm']['value'], 12.5)
        self.assertAlmostEqual(result['metrics']['pe_forward_4q']['value'], 100/14)

    def test_quote_arrives_while_yahoo_statements_are_still_running(self):
        from test_longbridge import blocks
        started=threading.Event();release=threading.Event();quoted=threading.Event();events=[]
        market=data.longbridge.normalize('QA',blocks(),data.now(),'EQUITY')
        def statements(symbol):
            started.set();release.wait(3)
            return {'income':self.item.get_income_stmt(),'balance':self.item.get_balance_sheet(),
                    'cashflow':self.item.get_cashflow(),'errors':[],'diagnostics':{},'fetched_at':data.now()}
        def snapshot(symbol,store,quote_type,force,on_quote=None,financial_refresh=None):
            self.assertTrue(started.wait(2));on_quote(market);return market
        def publish(r):
            events.append(r)
            if r.get('metrics',{}).get('price',{}).get('value') is not None:quoted.set()
        with patch.object(data,'_statement_blocks',side_effect=statements),patch.object(data.longbridge,'market_snapshot',side_effect=snapshot),ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(data.fetch_security,'QA',on_update=publish)
            try:
                self.assertTrue(quoted.wait(2));self.assertFalse(future.done())
                self.assertTrue(events[0]['partial'])
            finally:release.set()
            result=future.result(timeout=3)
        self.assertEqual(result['metrics']['revenue_q0']['value'],100)

    def test_financial_cache_has_separate_five_minute_ttl(self):
        saved={'market_provider':'longbridge','quote_type':'EQUITY','series':{'capex':{}},
               'financial_checked_at':'2026-10-12T00:00:00+00:00',
               'yahoo_session':{'mode':data.yahoo_session.mode(),'proxy_enabled':data.yahoo_session.proxy_enabled()}}
        self.assertFalse(data.financial_due(saved,'2026-10-12T00:04:59+00:00'))
        self.assertTrue(data.financial_due(saved,'2026-10-12T00:05:00+00:00'))

    def test_yahoo_task_failure_does_not_erase_fresh_longbridge_quote(self):
        from test_longbridge import blocks
        from concurrent.futures import Future
        market=data.longbridge.normalize('QA',blocks(),data.now(),'EQUITY')
        future=Future();future.set_exception(RuntimeError('offline'))
        with patch.object(data.STATEMENT_POOL,'submit',return_value=future),patch.object(data.longbridge,'market_snapshot',return_value=market),patch.object(data,'failure'):
            result=data.fetch_security('QA')
        self.assertEqual(result['metrics']['price']['value'],100)
        self.assertEqual(result['market_provider'],'longbridge')
        self.assertTrue(result['financial_errors'])

    def test_scheduled_quote_refresh_does_not_force_fresh_financials(self):
        from test_longbridge import blocks
        market=data.longbridge.normalize('QA',blocks(),data.now(),'EQUITY')
        saved=data._fetch_yahoo_security('QA');saved['market_provider']='longbridge'
        with patch.object(data.STATEMENT_POOL,'submit') as submit,patch.object(data.longbridge,'market_snapshot',return_value=market):
            result=data.fetch_security('QA',saved,force=True,financial_refresh=False)
        submit.assert_not_called()
        self.assertEqual(result['metrics']['revenue_q0']['value'],100)

    def test_independent_yahoo_calls_overlap(self):
        quote_barrier = threading.Barrier(2)
        financial_barrier = threading.Barrier(5)
        def overlap(barrier, value):
            def call(*args, **kwargs):
                barrier.wait(timeout=2)
                return value
            return call
        self.item.get_info.side_effect = overlap(quote_barrier, self.item.get_info.return_value)
        self.item.history.side_effect = overlap(quote_barrier, None)
        for method in ('get_income_stmt', 'get_balance_sheet', 'get_cashflow', 'get_earnings_estimate'):
            mock = getattr(self.item, method)
            mock.side_effect = overlap(financial_barrier, mock.return_value)
        self.item.get_shares_full.side_effect = overlap(financial_barrier, None)
        record = self.fetch('2026-10-04T02:00:00+00:00')
        self.assertEqual(record['metrics']['eps_q0']['value'], 2)
        self.assertFalse(any('BrokenBarrierError' in error for error in record['errors']))

    def test_next_minute_updates_all_financial_blocks(self):
        first = self.fetch('2026-10-04T02:00:00+00:00')
        self.item.get_info.return_value.update(regularMarketPrice=120, trailingEps=99)
        self.item.get_history_metadata.return_value = {'regularMarketPrice': 120}
        second = self.fetch('2026-10-04T02:01:00+00:00', first)
        self.assertEqual(self.item.get_income_stmt.call_count, 2)
        self.assertEqual(self.item.get_balance_sheet.call_count, 2)
        self.assertEqual(self.item.get_cashflow.call_count, 2)
        self.assertEqual(self.item.get_earnings_estimate.call_count, 2)
        self.assertEqual(self.item.get_info.call_count, 2)
        self.assertEqual(second['metrics']['pe_quarter']['value'], 15)
        self.assertEqual(second['financial_fetched_at'], '2026-10-04T02:01:00+00:00')
        self.assertEqual(self.item.history.call_args.kwargs['period'], '1mo')

    def test_empty_info_uses_chart_metadata_and_still_fetches_financials(self):
        self.item.get_info.return_value = {}
        self.item.get_history_metadata.return_value = {
            'instrumentType': 'EQUITY', 'currency': 'USD', 'longName': 'Test Company',
            'exchangeName': 'NMS', 'regularMarketPrice': 100, 'regularMarketTime': pd.Timestamp('2026-10-02T20:00:00Z'),
            'fiftyTwoWeekHigh': 110, 'fiftyTwoWeekLow': 60}
        self.item.get_balance_sheet.return_value.loc['OrdinarySharesNumber'] = 50
        record = self.fetch('2026-10-04T02:00:00+00:00')
        self.assertEqual(record['metrics']['market_cap']['value'], 5000)
        self.assertEqual(record['metrics']['market_cap']['inputs']['shares_period'], '2026-06-30')
        self.assertEqual(record['quote_type'], 'EQUITY')
        self.assertEqual(record['name'], 'Test Company')
        self.assertEqual(record['metrics']['high_52w']['value'], 110)
        self.assertEqual(record['metrics']['eps_q0']['value'], 2)
        self.assertEqual(record['metrics']['pe_quarter']['value'], 12.5)
        self.assertTrue(record['errors'])

    def test_empty_frames_leave_failed_financial_values_empty(self):
        first = self.fetch('2026-10-04T15:59:00+00:00')
        self.item.get_income_stmt.return_value = pd.DataFrame()
        failed = self.fetch('2026-10-04T16:00:00+00:00', first)
        self.assertIsNone(failed['metrics']['eps_q0']['value'])
        self.assertFalse(failed['financial_stale'])

    def test_forecast_failure_does_not_rollback_new_historical_debt(self):
        self.item._analysis._earnings_trend = [{'period': '0q', 'endDate': '2026-09-30'}]
        first = self.fetch('2026-10-04T15:59:00+00:00')
        frame = pd.DataFrame({
            pd.Timestamp('2026-06-30'): {'DilutedEPS': 2, 'TotalRevenue': 100, 'TotalDebt': 50, 'OperatingCashFlow': 20, 'CapitalExpenditure': -5},
            pd.Timestamp('2026-03-31'): {'DilutedEPS': 1.5, 'TotalRevenue': 80, 'TotalDebt': 40, 'OperatingCashFlow': 15, 'CapitalExpenditure': -4},
            pd.Timestamp('2025-12-31'): {'DilutedEPS': 1, 'TotalRevenue': 60, 'TotalDebt': 25, 'OperatingCashFlow': 10, 'CapitalExpenditure': -3},
        })
        for method in ('get_income_stmt', 'get_balance_sheet', 'get_cashflow'):
            getattr(self.item, method).return_value = frame
        self.item.get_earnings_estimate.side_effect = RuntimeError('Forecast unavailable')
        updated = self.fetch('2026-10-04T16:00:00+00:00', first)
        self.assertEqual(len(updated['series']['debt']), 3)
        self.assertAlmostEqual(updated['metrics']['debt_qoq_q0']['value'], 0.25)
        self.assertAlmostEqual(updated['metrics']['debt_qoq_q1']['value'], 0.60)
        self.assertEqual(updated['financial_fetched_at'], '2026-10-04T16:00:00+00:00')
        self.assertTrue(updated['financial_errors'])
        self.assertFalse(updated['financial_stale'])
        self.assertIsNone(updated['metrics']['forward_eps_next']['value'])
        self.assertIsNone(updated['metrics']['pe_forward_quarter']['value'])

    def test_quarterly_annualization_and_next_period_match(self):
        record = self.fetch('2026-10-04T02:00:00+00:00')
        record['metrics']['forward_eps_q0'] = {'value': 3, 'period': '2026-09-30', 'currency': 'USD'}
        record['metrics']['price']['value'] = 120
        data.revalue(record)
        self.assertEqual(record['metrics']['pe_quarter']['value'], 15)
        self.assertEqual(record['metrics']['pe_forward_quarter']['value'], 10)
        self.assertEqual(record['metrics']['pe_forward_quarter']['period'], '2026-09-30')
        record['metrics']['forward_eps_q0']['period'] = '2026-12-31'
        data.revalue(record)
        self.assertIsNone(record['metrics']['pe_forward_quarter']['value'])

    def test_partial_balance_does_not_fill_missing_quarters_from_cache(self):
        self.item.get_balance_sheet.return_value = pd.DataFrame({
            pd.Timestamp('2026-06-30'): {'TotalDebt': 50},
            pd.Timestamp('2026-03-31'): {'TotalDebt': 40},
        })
        first = self.fetch('2026-10-04T15:59:00+00:00')
        self.item.get_balance_sheet.return_value = pd.DataFrame({pd.Timestamp('2026-06-30'): {'TotalDebt': 60}})
        second = self.fetch('2026-10-04T16:00:00+00:00', first)
        self.assertEqual(len(second['series']['debt']), 1)
        self.assertEqual(second['metrics']['debt_q0']['value'], 60)
        self.assertIsNone(second['metrics']['debt_qoq_q0']['value'])

    def test_request_exception_preserves_old_quote_and_does_not_write_cache(self):
        store = MagicMock()
        store.get_cache.return_value = ({'schema_version': data.SCHEMA_VERSION, 'metrics': {'price': {'value': 100}}}, 0)
        with patch.object(data, 'fetch_security', side_effect=RuntimeError('offline')):
            result = data.security('QA', refresh=True, store=store)
        self.assertEqual(result['metrics']['price']['value'], 100)
        self.assertTrue(result['stale'])
        self.assertTrue(result['refresh_checked_at'])
        self.assertTrue(result['errors'])
        store.publish_cache.assert_not_called()

    def test_cache_read_outage_does_not_block_provider_refresh(self):
        store = MagicMock()
        store.get_cache.side_effect = RuntimeError('cache unavailable')
        fresh = {'ticker': 'QA', 'metrics': {'price': {'value': 110}}, 'fetched_at': data.now()}
        with patch.object(data, 'fetch_security', return_value=fresh) as fetch:
            result = data.security('QA', refresh=True, store=store)
        fetch.assert_called_once()
        self.assertEqual(result['metrics']['price']['value'], 110)
        self.assertFalse(result.get('stale', False))

    def test_cache_write_outage_does_not_roll_back_fresh_data(self):
        store = MagicMock()
        store.get_cache.return_value = ({'schema_version': data.SCHEMA_VERSION,
            'metrics': {'price': {'value': 100}}}, 0)
        store.publish_cache.side_effect = RuntimeError('cache unavailable')
        fresh = {'ticker': 'QA', 'metrics': {'price': {'value': 110}}, 'fetched_at': data.now()}
        with patch.object(data, 'fetch_security', return_value=fresh):
            result = data.security('QA', refresh=True, store=store)
        self.assertEqual(result['metrics']['price']['value'], 110)
        self.assertFalse(result.get('stale', False))
        self.assertFalse(result['cached'])

    def test_empty_provider_response_cannot_poison_successful_cache(self):
        saved={'schema_version':data.SCHEMA_VERSION,'name':'Test Company',
               'fetched_at':'2026-10-04T01:00:00+00:00','quote_date':'2026-10-02',
               'metrics':{'price':{'value':100},'eps_q0':{'value':2}}}
        store=MagicMock();store.get_cache.return_value=(saved,0)
        empty={'ticker':'QA','metrics':{'price':{'value':None}},'errors':['provider failed']}
        with patch.object(data,'fetch_security',return_value=empty):
            result=data.security('QA',refresh=True,store=store)
        self.assertEqual(result['metrics'],saved['metrics'])
        self.assertEqual(result['fetched_at'],saved['fetched_at'])
        self.assertEqual(result['quote_date'],saved['quote_date'])
        self.assertTrue(result['stale'])
        store.publish_cache.assert_not_called()
        self.assertNotIn('stale',saved)
        # Next successful retry replaces the old snapshot and removes stale status.
        fresh={**saved,'metrics':{'price':{'value':110}},'fetched_at':data.now()}
        with patch.object(data,'fetch_security',return_value=fresh):
            result=data.security('QA',refresh=True,store=store)
        self.assertEqual(result['metrics']['price']['value'],110)
        self.assertFalse(result.get('stale',False))
        store.publish_cache.assert_called_once()

    def test_first_failed_quote_has_no_fabricated_cache(self):
        store=MagicMock();store.get_cache.return_value=None
        with patch.object(data,'fetch_security',return_value={'metrics':{},'errors':['offline']}):
            result=data.security('NEW',store=store)
        self.assertEqual(result['metrics'],{})
        self.assertFalse(result.get('stale',False))
        store.publish_cache.assert_not_called()

    def test_yahoo_forecast_preferred_and_alpha_only_fills_gaps(self):
        record = self.fetch('2026-10-04T02:00:00+00:00')
        record['metrics']['forward_eps_q0'] = {'value': 3, 'period': '2026-09-30', 'currency': 'USD', 'source': 'Yahoo'}
        payload = {'fetched_at': record['fetched_at'], 'data': {'estimates': [
            {'horizon': 'fiscal quarter', 'date': '2026-09-30', 'eps_estimate_average': '4'}]}}
        with patch.object(data, 'estimate_data', return_value=payload) as provider:
            self.assertEqual(data.next_forecast(record)['value'], 3)
            provider.assert_not_called()
            record['metrics']['forward_eps_q0']['period'] = '2026-12-31'
            self.assertEqual(data.next_forecast(record)['value'], 4)
            provider.assert_called_once()
            record['metrics']['forward_eps_q0'].update(value=None, period='2026-09-30')
            self.assertEqual(data.next_forecast(record)['value'], 4)

    def test_quarterly_losses_and_currency_mismatch_are_not_valid_pe(self):
        record = self.fetch('2026-10-04T02:00:00+00:00')
        record['metrics']['eps_q0']['value'] = -2
        data.revalue(record)
        self.assertIsNone(record['metrics']['pe_quarter']['value'])
        record['metrics']['eps_q0'].update(value=2, currency='EUR')
        data.revalue(record)
        self.assertIsNone(record['metrics']['pe_quarter']['value'])

    def test_beijing_midnight_refreshes_financials(self):
        first = self.fetch('2026-10-04T15:59:00+00:00')
        second = self.fetch('2026-10-04T16:00:00+00:00', first)
        self.assertEqual(self.item.get_income_stmt.call_count, 2)
        self.assertEqual(second['financial_fetched_at'], '2026-10-04T16:00:00+00:00')

    def test_failed_financial_fetch_retries_next_minute(self):
        first = self.fetch('2026-10-04T15:59:00+00:00')
        self.item.get_income_stmt.side_effect = RuntimeError('source offline')
        failed = self.fetch('2026-10-04T16:00:00+00:00', first)
        self.assertFalse(failed['financial_stale'])
        self.assertIsNone(failed['metrics']['eps_q0']['value'])
        self.assertEqual(failed['financial_fetched_at'], '2026-10-04T16:00:00+00:00')
        again = self.fetch('2026-10-04T16:01:00+00:00', failed)
        self.assertEqual(self.item.get_income_stmt.call_count, 3)
        self.assertIsNone(again['metrics']['eps_q0']['value'])


if __name__ == '__main__':
    unittest.main()
