import json
import unittest
from unittest.mock import patch
import backend.providers.polymarket as p
class PolymarketCases(unittest.TestCase):
    def setUp(self):
        p._history.clear()
        p._history_retry.clear()
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
        self.assertEqual(data['series'],[{'price':.8}])
        self.assertTrue(data['stale'])
        self.assertNotIn('retrieved_at', data)
        self.assertNotIn('secret-url',str(data))

    def test_windowing_and_history_cache(self):
        with patch('backend.providers.polymarket.get',return_value={'history':[{'t':1,'p':.5}]}) as get:
            result=p.history('token',0,40*86400)
            p.history('token',0,40*86400)
        self.assertEqual(get.call_count,3)
        self.assertEqual(result,[{'t':1,'p':.5}])
        self.assertTrue(all(c.kwargs['endTs']-c.kwargs['startTs']<=14*86400 for c in get.call_args_list))

    def test_restart_and_failed_refresh_preserve_durable_history(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from backend.storage.store import Store
        with TemporaryDirectory() as directory:
            store = Store(sqlite_path=str(Path(directory)/'cache.db'))
            with patch.object(p, 'get', return_value={'history':[{'t':1,'p':.5}]}):
                p.history('yes-token',0,86400,store)
            p._history.clear()
            with patch.object(p, 'get', side_effect=AssertionError('Fresh cache must avoid network')):
                self.assertEqual(p.history('yes-token',0,86400,store),[{'t':1,'p':.5}])
            cached = p._history['yes-token']
            p._history['yes-token'] = (0,cached[1],cached[2])
            event={'startDate':'2026-10-01T00:00:00Z','title':'Fed','markets':[{
                'question':'Fed?', 'groupItemTitle':'No change','outcomes':'["Yes","No"]',
                'outcomePrices':'["0.8","0.2"]','clobTokenIds':'["yes-token","no-token"]'}]}
            def get(url, **params):
                if 'events/slug' in url:
                    return event
                raise ConnectionError('TLS connection interrupted')
            with patch.object(p,'get',side_effect=get),patch.object(p.time,'sleep'):
                data=p.load(store)
            series=data['series'][0]
            self.assertEqual(series['history'],cached[1])
            self.assertEqual(series['history_retrieved_at'],cached[2])
            self.assertTrue(series['history_error'])
            self.assertEqual(series['price'],.8)
            self.assertEqual(store.get_cache(p.history_key('yes-token'))[0]['history'],cached[1])

    def test_failed_window_retries_without_discarding_other_windows(self):
        calls={}
        def get(url, **params):
            start=params['startTs']
            calls[start]=calls.get(start,0)+1
            if start==0 and calls[start]==1:
                raise ConnectionError('temporary')
            return {'history':[{'t':start,'p':.5}]}
        with patch.object(p,'get',side_effect=get),patch.object(p.time,'sleep'):
            rows=p.history('retry',0,28*86400)
        self.assertEqual(len(rows),2)
        self.assertEqual(calls,{0:2,14*86400:1})

    def test_empty_response_cannot_replace_successful_history(self):
        p._history['token']=(0,[{'t':1,'p':.5}],'2026-10-01T00:00:00Z')
        with patch.object(p,'get',return_value={'history':[]}):
            with self.assertRaises(ValueError):
                p.history('token',0,86400)
        self.assertEqual(p._history['token'][1],[{'t':1,'p':.5}])

if __name__=='__main__':unittest.main()
