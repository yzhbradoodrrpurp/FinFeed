import unittest
import threading
import os
import json
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone
from unittest.mock import patch
import backend.services.macro as macro
class MacroCases(unittest.TestCase):
    def test_bls_fallback_uses_announced_dates_and_eastern_dst(self):
        from backend.providers import bls
        dates = ['2026-10-02', '2026-11-06', '2026-12-04']
        with patch.object(bls, 'official_schedule', side_effect=TimeoutError()), \
                patch('backend.providers.fred.release_dates', return_value=dates) as release:
            result = bls.schedule(datetime(2026, 10, 10, tzinfo=timezone.utc))
        release.assert_called_once_with(50)
        self.assertEqual(result['last_release'], '2026-10-02T08:30:00-04:00')
        self.assertEqual(result['next_release'], '2026-11-06T08:30:00-05:00')
        self.assertIn('未提供时刻', result['calendar_time_basis'])

    def test_bls_fallback_never_invents_future_dates(self):
        from backend.providers import bls
        with patch.object(bls, 'official_schedule', side_effect=TimeoutError()), \
                patch('backend.providers.fred.release_dates', return_value=['2026-10-02']):
            with self.assertRaises(ValueError):
                bls.schedule(datetime(2026, 10, 10, tzinfo=timezone.utc))

    def test_treasury_fetches_three_years_without_row_limit(self):
        rows=[{'date':'2023-10-05','value':'4.7'},{'date':'2023-10-06','value':'.'}]
        with patch.dict(os.environ, {'FRED_API_KEY':'test'}), patch('backend.services.macro.history_start',return_value='2023-10-05'), patch('backend.providers.fred.fetch',return_value=json.dumps({'observations':rows})) as fetch:
            result=macro.observations('DGS10')
        query=parse_qs(urlparse(fetch.call_args.args[0]).query)
        self.assertEqual(query['observation_start'],['2023-10-05'])
        self.assertNotIn('limit',query)
        self.assertEqual(result,[{'date':'2023-10-05','value':4.7}])

    def test_daily_history_keeps_all_observations(self):
        rows=[{'date':f'2026-01-{day:02d}','value':day} for day in range(1,32)]
        result=macro.metric('daily',rows,'%', 'source',full_history=True)
        self.assertEqual(result['history'],rows)
        self.assertEqual(result['latest'],rows[-1])
        self.assertEqual(result['previous'],rows[-2])

    def test_metrics_and_calendar_overlap(self):
        barrier = threading.Barrier(2)
        def metrics(kind):
            barrier.wait(timeout=2)
            return {'metrics': [1], 'errors': []}
        def calendar(kind, now):
            barrier.wait(timeout=2)
            return {'next_release': 'future'}
        with patch('backend.services.macro._load_metrics', side_effect=metrics), patch('backend.services.macro.schedule', side_effect=calendar):
            result = macro.load('pce')
        self.assertEqual(result['metrics'], [1])
        self.assertEqual(result['next_release'], 'future')

    def test_calendar_failure_preserves_metrics(self):
        with patch('backend.services.macro._load_metrics', return_value={'metrics': [1], 'errors': []}), patch('backend.services.macro.schedule', side_effect=RuntimeError):
            result = macro.load('jobs')
        self.assertEqual(result['metrics'], [1])
        self.assertEqual(result['errors'], ['发布日历暂不可用'])

    def test_growth_does_not_bridge_missing_month(self):
        rows=[{'date':'2026-01-01','value':100},{'date':'2026-03-01','value':110}]
        self.assertEqual(macro.growth(rows,1), [])
        rows.insert(1,{'date':'2026-02-01','value':105})
        self.assertAlmostEqual(macro.growth(rows,1)[0]['value'],5)

    def test_failure_replaces_expired_snapshot(self):
        macro._cache.clear()
        with patch('backend.services.macro.load',return_value={'metrics':[1],'errors':[]}):
            self.assertEqual(macro.snapshot('jobs')['metrics'],[1])
        macro._cache['jobs']['expires']=0
        with patch('backend.services.macro.load',return_value={'metrics':[],'errors':['unavailable']}):
            self.assertEqual(macro.snapshot('jobs')['metrics'],[])

    def test_bea_calendar_uses_timezone_and_nearest_future(self):
        payload='{"Personal Income and Outlays":{"release_dates":["2026-09-30T12:30:00+00:00","2026-10-29T12:30:00+00:00"]}}'
        with patch('backend.providers.bea.fetch',return_value=payload):
            result=macro.schedule('pce',datetime(2026,10,5,tzinfo=timezone.utc))
        self.assertEqual(result['next_release'],'2026-10-29T12:30:00+00:00')

    def test_previous_release_is_actual_calendar_entry_not_observation_date(self):
        payload='{"Personal Income and Outlays":{"release_dates":["2026-10-29T12:30:00+00:00","2026-09-30T12:30:00+00:00","2026-09-30T12:30:00+00:00"]}}'
        with patch('backend.providers.bea.fetch',return_value=payload):
            result=macro.schedule('pce',datetime(2026,10,29,14,tzinfo=timezone.utc))
        self.assertEqual(result['previous_release'],'2026-09-30T12:30:00+00:00')
        self.assertEqual(result['last_release'],'2026-10-29T12:30:00+00:00')
        with patch('backend.providers.bea.fetch',return_value=payload):
            early=macro.schedule('pce',datetime(2026,10,5,tzinfo=timezone.utc))
        self.assertIsNone(early['previous_release'])

    def test_errors_do_not_leak_credentials(self):
        with patch('backend.services.macro.observations',side_effect=RuntimeError('secret-key-in-url')):
            result=macro.load('treasury')
        self.assertNotIn('secret-key',str(result))
        self.assertEqual(result['metrics'],[])

if __name__=='__main__': unittest.main()
