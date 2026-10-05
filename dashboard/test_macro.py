import unittest
import threading
from datetime import datetime, timezone
from unittest.mock import patch
import macro

class MacroCases(unittest.TestCase):
    def test_metrics_and_calendar_overlap(self):
        barrier = threading.Barrier(2)
        def metrics(kind):
            barrier.wait(timeout=2)
            return {'metrics': [1], 'errors': []}
        def calendar(kind, now):
            barrier.wait(timeout=2)
            return {'next_release': 'future'}
        with patch('macro._load_metrics', side_effect=metrics), patch('macro.schedule', side_effect=calendar):
            result = macro.load('pce')
        self.assertEqual(result['metrics'], [1])
        self.assertEqual(result['next_release'], 'future')

    def test_calendar_failure_preserves_metrics(self):
        with patch('macro._load_metrics', return_value={'metrics': [1], 'errors': []}), patch('macro.schedule', side_effect=RuntimeError):
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
        with patch('macro.load',return_value={'metrics':[1],'errors':[]}):
            self.assertEqual(macro.snapshot('jobs')['metrics'],[1])
        macro._cache['jobs']['expires']=0
        with patch('macro.load',return_value={'metrics':[],'errors':['unavailable']}):
            self.assertEqual(macro.snapshot('jobs')['metrics'],[])

    def test_bea_calendar_uses_timezone_and_nearest_future(self):
        payload='{"Personal Income and Outlays":{"release_dates":["2026-09-30T12:30:00+00:00","2026-10-29T12:30:00+00:00"]}}'
        with patch('macro.fetch',return_value=payload):
            result=macro.schedule('pce',datetime(2026,10,5,tzinfo=timezone.utc))
        self.assertEqual(result['next_release'],'2026-10-29T12:30:00+00:00')

    def test_errors_do_not_leak_credentials(self):
        with patch('macro.observations',side_effect=RuntimeError('secret-key-in-url')):
            result=macro.load('treasury')
        self.assertNotIn('secret-key',str(result))
        self.assertEqual(result['metrics'],[])

if __name__=='__main__': unittest.main()
