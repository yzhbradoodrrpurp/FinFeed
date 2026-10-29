import tempfile
import threading
import time
import unittest
from flask import Flask
from backend.storage.store import Store
from backend.infrastructure.refresh_jobs import RefreshJobs
from backend.infrastructure.snapshot_read import content_version, response


class SnapshotReadCases(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = Store(sqlite_path=self.directory.name+'/cache.db')
        self.app = Flask(__name__)

    def test_unchanged_returns_empty_304_but_changed_value_returns_body(self):
        key = 'market:v1:macro:test'
        self.store.set_cache(key, {'price': 10, 'retrieved_at': 'first'})
        with self.app.test_request_context('/'):
            first = response(self.store, key, 3600)
            version = first.json['cache_version']
        self.store.set_cache(key, {'price': 10, 'retrieved_at': 'later'})
        with self.app.test_request_context('/?version='+version):
            unchanged = response(self.store, key, 3600)
            self.assertEqual(unchanged.status_code, 304)
            self.assertEqual(unchanged.get_data(), b'')
            self.assertIn('X-FinFeed-Checked-At', unchanged.headers)
        self.store.set_cache(key, {'price': 11, 'retrieved_at': 'later'})
        with self.app.test_request_context('/?version='+version):
            self.assertEqual(response(self.store,key,3600).json['price'], 11)

    def test_cache_only_never_invokes_provider_and_failure_retains_snapshot(self):
        jobs = RefreshJobs(self.store)
        def forbidden(publish):
            raise AssertionError('provider called by read')
        with self.app.test_request_context('/?cache=only'):
            missing = jobs.response('home:test', forbidden, 3600, lambda v:True)
            self.assertEqual(missing[1], 202)
        self.store.set_cache('market:v1:home:test', {'index': {'price': 42}})
        self.store.set_cache('refresh-status:market:v1:home:test', {'failed':True})
        with self.app.test_request_context('/?cache=only'):
            result = jobs.response('home:test', forbidden, 3600, lambda v:True).json
            self.assertEqual(result['index']['price'],42)
            self.assertTrue(result['stale'])

    def test_period_and_source_changes_are_not_hidden_by_version(self):
        base = {'value':1,'period':'2026-06-30','source':'SEC'}
        for field,value in [('value',2),('period','2026-09-30'),('source','Longbridge')]:
            self.assertNotEqual(content_version(base),content_version({**base,field:value}))

    def test_kick_is_nonblocking_and_deduplicates_running_job(self):
        jobs = RefreshJobs(self.store)
        entered, release, done = threading.Event(),threading.Event(),threading.Event()
        calls=[]
        def slow(publish):
            calls.append(1); entered.set(); release.wait(2);done.set()
            return {'price':1}
        try:
            jobs.kick('security:TEST',slow,60,lambda v:True)
            self.assertTrue(entered.wait(1))
            jobs.kick('security:TEST',slow,60,lambda v:True)
            self.assertEqual(len(calls),1)
        finally:
            release.set();done.wait(2)
            deadline = time.monotonic()+2
            while jobs.entries["security:TEST"]["running"] and time.monotonic()<deadline:
                time.sleep(.01)

    def test_scheduler_deduplicates_accounts_and_separates_intervals(self):
        import json
        from backend.services.market_schedule import symbols, cycle
        with self.store.transaction() as db:
            for uid,watch,positions in [('a',['AAPL','MSFT'],[{'ticker':'MU'}]),('b',['AAPL'],[]),('disabled',['NVDA'],[])]:
                self.store.execute(db,'INSERT INTO accounts (id,name,state,revision,created) VALUES (?,?,?,?,?)',
                    (uid,uid,json.dumps({'watchlist':watch,'positions':positions}),0,0))
            self.store.execute(db,'INSERT INTO disabled_accounts (id,created) VALUES (?,?)',('disabled',0))
        market,news=symbols(self.store)
        self.assertEqual(market,['AAPL','MSFT','MU'])
        self.assertEqual(news,['AAPL','MSFT'])
        class Jobs:
            def __init__(self):self.calls={}
            def kick(self,key,loader,ttl,valid,**kwargs):self.calls[key]=(ttl,loader,kwargs)
        jobs=Jobs();cycle(self.store,jobs,market,news)
        self.assertEqual(jobs.calls['security:AAPL'][0],60)
        self.assertEqual(jobs.calls['financial:AAPL'][0],3600)
        self.assertEqual(jobs.calls['macro:fed'][0],3600)
        self.assertEqual(jobs.calls['home:^GSPC'][0],3600)
        self.assertNotIn('news:sec-edgar:v1:MU',jobs.calls)
