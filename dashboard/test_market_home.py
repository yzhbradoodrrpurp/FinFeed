import unittest
from datetime import date, datetime
from unittest.mock import patch, MagicMock
import market_home as home

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
        ticker.get_history_metadata.return_value={'regularMarketPrice':105,'chartPreviousClose':100,'regularMarketTime':datetime.fromisoformat('2026-10-05T14:00:00+00:00')}
        with patch('yfinance.Ticker',return_value=ticker):
            result=home.quote(home.INDICES[0])
        self.assertEqual(result['change'],5)
        self.assertAlmostEqual(result['change_percent'],5)
        self.assertIsNotNone(result['quoted_at'])
        self.assertIsNone(result['error'])

    def test_quote_failure_leaves_missing_value(self):
        with patch('yfinance.Ticker',side_effect=RuntimeError('secret-in-url')):
            result=home.quote(home.INDICES[0])
        self.assertIsNone(result['price'])
        self.assertNotIn('secret',str(result))

    def test_quote_cache_shared_across_requests(self):
        home._cached=None;home._expires=0
        with patch('market_home.quote',return_value={'price':1}) as quote:
            home.snapshot();home.snapshot()
        self.assertEqual(quote.call_count,3)

if __name__=='__main__':unittest.main()
