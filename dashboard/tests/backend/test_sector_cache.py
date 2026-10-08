import unittest
from unittest.mock import patch, MagicMock
from datetime import date, timedelta
from copy import deepcopy
from backend.services import sectors

class SectorCacheCases(unittest.TestCase):
    def setUp(self):
        sectors._histories.clear(); sectors._retry.clear(); sectors._quotes.clear()
        end=date(2026,10,7)
        self.rows=[{'date': (end-timedelta(days=i)).isoformat(), 'value': 100.}
                   for i in reversed(range(1096)) if (end-timedelta(days=i)).weekday()<5]
        self.recent={'symbol':'XLK','price':101.,'quoted_at':'2026-10-07T20:00:00+00:00',
                     'history':self.rows[-5:],'error':None,'previous_close':100.,'change':1.,'change_percent':1.}
        self.store=MagicMock(); self.store.get_cache.return_value=None
    def test_full_history_reused_with_minute_quotes(self):
        full={**self.recent,'history':self.rows}
        with patch.object(sectors,'quote',side_effect=[deepcopy(self.recent),full,deepcopy(self.recent)]) as fetch:
            a=sectors.snapshot('XLK',self.store); b=sectors.snapshot('XLK',self.store)
        self.assertEqual(len(a['sector']['history']),len(self.rows))
        self.assertEqual(b['sector']['history'],a['sector']['history'])
        self.assertEqual([c.kwargs['history_period'] for c in fetch.call_args_list if 'history_period' in c.kwargs],['5d','5d'])
        self.assertEqual(fetch.call_count,3)
    def test_short_history_rejected_quote_survives_and_retry_bounded(self):
        with patch.object(sectors,'quote',side_effect=lambda *a,**k:deepcopy(self.recent)) as fetch:
            a=sectors.snapshot('XLK',self.store); sectors.snapshot('XLK',self.store)
        self.assertEqual(a['sector']['price'],101.)
        self.assertEqual(a['sector']['history'],[])
        self.assertTrue(a['sector']['history_warning'])
        self.assertEqual(fetch.call_count,3)
    def test_revision_reloads_and_old_quote_does_not_replace_new(self):
        sectors._histories['XLK']={'history':self.rows,'checked_at':sectors.time.time()}
        sectors._quotes['XLK']=deepcopy(self.recent)
        changed=deepcopy(self.recent); changed['history'][-2]['value']=50.
        changed['price']=99.; changed['quoted_at']='2026-10-06T20:00:00+00:00'
        with patch.object(sectors,'quote',side_effect=[changed,{'error':'timeout'}]):
            a=sectors.snapshot('XLK',self.store)['sector']
        self.assertEqual(a['price'],101.)
        self.assertEqual(a['history'][-2]['value'],100.)
        self.assertTrue(a['history_warning'])
    def test_validation_rejects_gaps_and_duplicates(self):
        today=date(2026,10,7)
        self.assertTrue(sectors.complete(self.rows,today))
        self.assertFalse(sectors.complete(self.rows[:-1]+[self.rows[-2]],today))
        self.assertFalse(sectors.complete(self.rows[:100]+self.rows[130:],today))
