import unittest
from datetime import date, datetime
from unittest.mock import patch, MagicMock
import backend.services.home as home
class HomeCases(unittest.TestCase):
    def test_holidays_weekends_and_early_close(self):
        rows=home.sessions(date(2026,11,26))
        self.assertEqual(rows[0]['open'],'2026-11-27T14:30:00+00:00')
        self.assertEqual(rows[0]['close'],'2026-11-27T18:00:00+00:00')
        self.assertEqual(rows[1]['open'],'2026-11-30T14:30:00+00:00')

    def test_daylight_saving_changes_opening_utc(self):
        rows=home.sessions(date(2026,10,30))
        self.assertEqual(rows[0]['open'],'2026-10-30T13:30:00+00:00')
        self.assertEqual(rows[1]['open'],'2026-11-02T14:30:00+00:00')

    def test_quote_change_and_provenance(self):
        ticker=MagicMock()
        ticker.get_history_metadata.return_value={'regularMarketPrice':105,'previousClose':100,'regularMarketTime':datetime.fromisoformat('2026-10-05T14:00:00+00:00')}
        with patch('yfinance.Ticker',return_value=ticker):
            result=home.quote(home.INDICES[0])
        self.assertEqual(result['change'],5)
        self.assertAlmostEqual(result['change_percent'],5)
        self.assertIsNotNone(result['quoted_at'])
        self.assertIsNone(result['error'])

    def test_daily_history_uses_previous_session_not_range_start(self):
        import pandas as pd
        ticker=MagicMock()
        ticker.history.return_value=pd.DataFrame({'Close':[90,100,105]},index=pd.to_datetime(['2026-10-01','2026-10-02','2026-10-05']))
        ticker.get_history_metadata.return_value={'regularMarketPrice':105,'chartPreviousClose':80,'regularMarketTime':datetime.fromisoformat('2026-10-05T14:00:00+00:00')}
        with patch('yfinance.Ticker',return_value=ticker):
            result=home.quote(home.INDICES[0])
        self.assertEqual(result['previous_close'],100)
        self.assertEqual(result['change'],5)

    def test_quote_failure_leaves_missing_value(self):
        with patch('yfinance.Ticker',side_effect=RuntimeError('secret-in-url')):
            result=home.quote(home.INDICES[0])
        self.assertIsNone(result['price'])
        self.assertNotIn('secret',str(result))

    def test_quote_cache_shared_across_requests(self):
        home._cached=None;home._expires=0
        with patch('backend.services.home.quote',return_value={'price':1}) as quote:
            home.snapshot();home.snapshot()
        self.assertEqual(quote.call_count,3)

    def test_slow_index_does_not_block_other_index_or_calendar(self):
        from threading import Event
        from concurrent.futures import ThreadPoolExecutor
        entered,release=Event(),Event()
        home._index_cache.clear()
        def quote(index):
            if index[0]=='^GSPC':
                entered.set()
                release.wait(3)
            return {'symbol':index[0],'price':1}
        with patch('backend.services.home.quote',side_effect=quote), ThreadPoolExecutor(max_workers=2) as pool:
            slow=pool.submit(home.index_snapshot,'^GSPC')
            try:
                self.assertTrue(entered.wait(1))
                fast=pool.submit(home.index_snapshot,'^IXIC')
                self.assertEqual(fast.result(timeout=1)['index']['symbol'],'^IXIC')
                self.assertTrue(home.calendar_snapshot()['sessions'])
                self.assertFalse(slow.done())
            finally:
                release.set()
            slow.result(timeout=1)

if __name__=='__main__':unittest.main()
