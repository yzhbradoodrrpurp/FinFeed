import json
import unittest
from unittest.mock import patch
import backend.providers.polymarket as p
class PolymarketCases(unittest.TestCase):
    def setUp(self):
        p._history.clear()
        p._expires = 0
        p._value = None

    def test_yes_token_is_selected_by_outcome_not_position(self):
        event={'startDate':'2026-10-01T00:00:00Z','title':'Fed', 'markets':[{
            'question':'Fed?', 'groupItemTitle':'No change', 'outcomes':json.dumps(['No','Yes']),
            'outcomePrices':json.dumps(['0.2','0.8']), 'clobTokenIds':json.dumps(['no-token','yes-token'])}]}
        with patch('backend.providers.polymarket.get',return_value=event),patch('backend.providers.polymarket.history',return_value=[]) as history:
            data=p.load()
        self.assertEqual(history.call_args.args[0],'yes-token')
        self.assertEqual(data['series'][0]['price'],.8)

    def test_public_snapshot_shared_until_expiry(self):
        with patch('backend.providers.polymarket.load',return_value={'series':[],'errors':[]}) as load:
            self.assertEqual(p.snapshot(),p.snapshot())
        self.assertEqual(load.call_count,1)

    def test_failure_does_not_present_old_prices_as_current(self):
        p._value={'series':[{'price':.8}]}
        with patch('backend.providers.polymarket.load',side_effect=RuntimeError('secret-url')):
            data=p.snapshot()
        self.assertEqual(data['series'],[])
        self.assertNotIn('secret-url',str(data))

    def test_windowing_and_history_cache(self):
        with patch('backend.providers.polymarket.get',return_value={'history':[{'t':1,'p':.5}]}) as get:
            result=p.history('token',0,40*86400)
            p.history('token',0,40*86400)
        self.assertEqual(get.call_count,3)
        self.assertEqual(result,[{'t':1,'p':.5}])
        self.assertTrue(all(c.kwargs['endTs']-c.kwargs['startTs']<=14*86400 for c in get.call_args_list))

if __name__=='__main__':unittest.main()
