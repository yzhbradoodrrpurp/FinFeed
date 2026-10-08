import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pandas as pd
from backend.services.home import SECTORS, sector_snapshot


class SectorCases(unittest.TestCase):
    def test_daily_history_and_previous_trading_close(self):
        ticker = MagicMock()
        ticker.history.return_value = pd.DataFrame({'Close': [100., float('nan'), 104., 106.]},
            index=pd.to_datetime(['2026-10-01', '2026-10-02', '2026-10-05', '2026-10-06']).tz_localize('America/New_York'))
        ticker.get_history_metadata.return_value = {'currency': 'USD', 'regularMarketPrice': 107.,
            'previousClose': 70., 'regularMarketTime': datetime(2026, 10, 6, 18, tzinfo=timezone.utc).timestamp()}
        with patch('yfinance.Ticker', return_value=ticker):
            data = sector_snapshot('XLK')['sector']
        self.assertEqual(data['previous_close'], 104.)
        self.assertEqual(data['change'], 3.)
        self.assertEqual(len(data['history']), 3)
        self.assertEqual(data['price'], 107.)
        ticker.history.assert_called_once_with(period='3y', interval='1d', auto_adjust=False, timeout=30, raise_errors=True)

    def test_failure_cannot_be_accepted_as_success(self):
        with patch('yfinance.Ticker', side_effect=RuntimeError('timeout')):
            data = sector_snapshot('XLC')
        self.assertIsNone(data['sector']['price'])
        self.assertTrue(data['errors'])

    def test_exact_sector_universe_and_unknown_symbol(self):
        self.assertEqual({s[0] for s in SECTORS}, {'XLC','XLY','XLP','XLE','XLF','XLV','XLI','XLB','XLRE','XLK','XLU'})
        with self.assertRaises(ValueError):
            sector_snapshot('AAPL')
