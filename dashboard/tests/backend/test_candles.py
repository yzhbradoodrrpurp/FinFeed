"""History validation and failed-refresh durability; no live provider calls."""
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from backend.providers.candles import normalize, snapshot
from backend.infrastructure.refresh_jobs import RefreshJobs
from backend.storage.store import Store


class CandleCases(unittest.TestCase):
    def bar(self, day=2, **overrides):
        return SimpleNamespace(**dict(dict(timestamp=datetime(2026, 1, day, 20, tzinfo=timezone.utc),
            open=10, high=12, low=9, close=11, volume=100), **overrides))

    def test_daily_observations_sort_deduplicate_and_respect_exchange_dates(self):
        rows = [self.bar(3), self.bar(2), self.bar(2), self.bar(1)]
        values = normalize(rows, date(2026,1,2), date(2026,1,3), timezone.utc)
        self.assertEqual([b['time'] for b in values], ['2026-01-02','2026-01-03'])
        for bad in (self.bar(high=8), self.bar(volume=-1), self.bar(close=float('nan'))):
            with self.assertRaises(ValueError):
                normalize([bad], date(2026,1,1), date(2026,1,3), timezone.utc)
        with self.assertRaises(ValueError):
            normalize([self.bar(),self.bar(volume=200)],date(2026,1,1),date(2026,1,3),timezone.utc)
        with self.assertRaises(ValueError):
            normalize([],date(2026,1,1),date(2026,1,3),timezone.utc)

    def test_dates_use_exchange_timezone_including_naive_sdk_datetimes(self):
        from zoneinfo import ZoneInfo
        stamp = datetime(2026, 1, 3, 2, tzinfo=timezone.utc)
        expected = '2026-01-02'
        for value in (stamp, stamp.astimezone().replace(tzinfo=None)):
            bars = normalize([self.bar(timestamp=value)], date(2026,1,1), date(2026,1,3), ZoneInfo('America/New_York'))
            self.assertEqual(bars[0]['time'], expected)

    def test_unsupported_market_never_uses_guessed_us_symbol(self):
        from unittest.mock import patch
        with patch('backend.providers.candles.contexts') as provider:
            self.assertTrue(snapshot('BTC-USD')['unsupported'])
            self.assertTrue(snapshot('0700.HK')['unsupported'])
            provider.assert_not_called()

    def test_refresh_failure_retains_persisted_full_history(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(sqlite_path=str(Path(folder)/'test.sqlite'))
            old = {'bars':[{'time':'2025-01-02','open':10}], 'errors':[]}
            store.set_cache('market:v1:candles:3y:v1:AAPL',old)
            jobs = RefreshJobs(store)
            def failed(publish):
                raise OSError('provider unavailable')
            values = list(jobs.events('candles:3y:v1:AAPL',failed,0,lambda v:bool(v.get('bars'))))
            self.assertTrue(values[-1]['stale'])
            self.assertEqual(values[-1]['bars'],old['bars'])
            self.assertEqual(store.get_cache('market:v1:candles:3y:v1:AAPL')[0],old)
