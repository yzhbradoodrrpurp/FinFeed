import unittest
from unittest.mock import patch, MagicMock
from tempfile import TemporaryDirectory
from pathlib import Path
import json
import backend.providers.alpha_vantage as alpha
from backend.storage.store import Store


class EstimateCases(unittest.TestCase):
    def test_four_quarters_exclude_annual_and_past_periods(self):
        rows = [{'date': date, 'horizon': 'fiscal quarter', 'eps_estimate_average': str(value)} for date, value in [('2026-09-30', 99), ('2026-12-31', 1), ('2027-03-31', 2), ('2027-06-30', 3), ('2027-09-30', 4)]]
        rows.append({'date': '2027-09-30', 'horizon': 'fiscal year', 'eps_estimate_average': '999'})
        denominator, quarters, reason = alpha.next_four_eps({'estimates': rows}, '2026-10-04T00:00:00+00:00')
        self.assertEqual(denominator, 10)
        self.assertEqual(len(quarters), 4)
        self.assertIsNone(reason)
        self.assertIsNone(alpha.next_four_eps({'estimates': rows[:2]}, '2026-10-04T00:00:00+00:00')[0])
        rows[2]['date'] = '2027-02-01'
        self.assertIsNone(alpha.next_four_eps({'estimates': rows}, '2026-10-04T00:00:00+00:00')[0])

    def test_minute_cache_and_failure_preserve_forecast_without_exposing_key(self):
        with TemporaryDirectory() as directory:
            store=Store(sqlite_path=str(Path(directory)/'cache.db'))
            response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps({'symbol':'QA','estimates':[]}).encode()
            with patch.dict(alpha.os.environ,{'ALPHAVANTAGE_API_KEY':'private-test-key'}),patch.object(alpha.urllib.request,'urlopen',return_value=response) as request:
                first=alpha.estimate_data('QA','2026-10-04T15:59:00+00:00',store=store)
                alpha.estimate_data('QA','2026-10-04T15:59:30+00:00',store=store)
                self.assertEqual(request.call_count,1)
                request.side_effect=RuntimeError('private-test-key')
                failed=alpha.estimate_data('QA','2026-10-04T16:00:00+00:00',store=store)
                self.assertEqual(failed['data'],first['data'])
                self.assertNotIn('private-test-key',json.dumps(failed))
                alpha.estimate_data('QA','2026-10-04T16:01:00+00:00',store=store)
                self.assertEqual(request.call_count,3)

if __name__=='__main__':unittest.main()
