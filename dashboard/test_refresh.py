"""Refresh cadence and valuation must not silently refetch daily fundamentals."""
import unittest
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch
import pandas as pd
import data


class RefreshCases(unittest.TestCase):
    def test_provider_requests_overlap_but_never_exceed_three(self):
        release = threading.Event()
        three_entered = threading.Event()
        guard = threading.Lock()
        active = 0
        peak = 0
        calls = 0

        def fetch(symbol, saved, estimate_store):
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
            return data.fetch_security('QA', saved)

    def test_same_day_only_market_updates_and_pe_uses_daily_eps(self):
        first = self.fetch('2026-10-04T02:00:00+00:00')
        self.item.get_info.return_value.update(regularMarketPrice=120, trailingEps=99)
        self.item.get_history_metadata.return_value = {'regularMarketPrice': 120}
        second = self.fetch('2026-10-04T02:01:00+00:00', first)
        self.assertEqual(self.item.get_income_stmt.call_count, 1)
        self.assertEqual(self.item.get_balance_sheet.call_count, 1)
        self.assertEqual(self.item.get_cashflow.call_count, 1)
        self.assertEqual(self.item.get_earnings_estimate.call_count, 1)
        self.assertEqual(self.item.get_info.call_count, 1)
        self.assertEqual(second['metrics']['pe_quarter']['value'], 15)
        self.assertEqual(second['financial_fetched_at'], first['financial_fetched_at'])
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

    def test_empty_frames_preserve_previous_financial_values(self):
        first = self.fetch('2026-10-04T15:59:00+00:00')
        self.item.get_income_stmt.return_value = pd.DataFrame()
        failed = self.fetch('2026-10-04T16:00:00+00:00', first)
        self.assertEqual(failed['metrics']['eps_q0']['value'], 2)
        self.assertTrue(failed['financial_stale'])

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
        self.assertEqual(updated['metrics']['forward_eps_next']['value'], 3)
        self.assertTrue(updated['metrics']['forward_eps_next']['estimate_stale'])

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

    def test_failed_daily_fetch_preserves_old_values_without_minute_retries(self):
        first = self.fetch('2026-10-04T15:59:00+00:00')
        self.item.get_income_stmt.side_effect = RuntimeError('source offline')
        failed = self.fetch('2026-10-04T16:00:00+00:00', first)
        self.assertTrue(failed['financial_stale'])
        self.assertEqual(failed['metrics']['eps_q0'], first['metrics']['eps_q0'])
        self.assertEqual(failed['financial_fetched_at'], first['financial_fetched_at'])
        again = self.fetch('2026-10-04T16:01:00+00:00', failed)
        self.assertEqual(self.item.get_income_stmt.call_count, 2)
        self.assertTrue(again['financial_stale'])


if __name__ == '__main__':
    unittest.main()
