import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from cloud_store import Store
from refresh_jobs import RefreshJobs


class RefreshJobCases(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = self.directory.name + '/cache.db'
        self.store = Store(sqlite_path=self.path)
        self.good = lambda value: value.get('price') is not None

    def test_scheduled_refresh_bypasses_cache_but_coalesces_recent_completion(self):
        jobs = RefreshJobs(self.store)
        key = 'macro:forced'
        self.store.set_cache('market:v1:' + key, {'price': 100})
        calls = []
        def loader(publish):
            calls.append(1)
            return {'price': 101}
        self.assertEqual(list(jobs.events(key, loader, 3600, self.good))[-1]['price'], 100)
        self.assertFalse(calls)
        self.assertEqual(list(jobs.events(key, loader, 3600, self.good, force=True))[-1]['price'], 101)
        self.assertEqual(list(jobs.events(key, loader, 3600, self.good, force=True))[-1]['price'], 101)
        self.assertEqual(len(calls), 1)

    def test_stages_arrive_before_completion_and_subscribers_share_one_job(self):
        jobs = RefreshJobs(self.store, deadline=1)
        release = threading.Event()
        entered = threading.Event()
        calls = []
        def loader(publish):
            calls.append(1)
            publish({'price': 100, 'partial': True})
            entered.set()
            release.wait(1)
            return {'price': 101, 'finance': 7}
        events = jobs.events('home:QA', loader, 60, self.good)
        first = next(events)
        self.assertEqual(first['price'], 100)
        self.assertTrue(first['partial'])
        with ThreadPoolExecutor(1) as pool:
            other = pool.submit(lambda: list(jobs.events('home:QA', loader, 60, self.good)))
            release.set()
            results = list(events)
            self.assertEqual(other.result()[-1]['price'], 101)
        self.assertEqual(results[-1]['finance'], 7)
        self.assertFalse(results[-1]['refreshing'])
        self.assertEqual(len(calls), 1)

    def test_persistent_cache_survives_new_store_and_job_registry(self):
        jobs = RefreshJobs(self.store)
        list(jobs.events('macro:QA', lambda publish: {'price': 100}, 3600, self.good))
        recreated = RefreshJobs(Store(sqlite_path=self.path))
        def forbidden(publish):
            raise AssertionError('Fresh durable snapshot must avoid provider')
        values = list(recreated.events('macro:QA', forbidden, 3600, self.good))
        self.assertEqual(values[-1]['price'], 100)
        self.assertFalse(values[-1]['stale'])

    def test_timeout_keeps_partial_data_without_duplicate_provider(self):
        release = threading.Event()
        jobs = RefreshJobs(self.store, deadline=.03)
        calls = []
        def slow(publish):
            calls.append(1)
            publish({'price': 100, 'partial': True})
            release.wait(1)
            return {'price': 101}
        try:
            started = time.monotonic()
            result = list(jobs.events('home:QA', slow, 60, self.good))[-1]
            self.assertLess(time.monotonic() - started, .2)
            self.assertEqual(result['price'], 100)
            self.assertTrue(result['stale'])
            list(jobs.events('home:QA', slow, 60, self.good))
            self.assertEqual(len(calls), 1)
        finally:
            release.set()
            time.sleep(.02)

    def test_failure_backoff_does_not_replace_durable_success(self):
        self.store.set_cache('market:v1:macro:QA', {'price': 100})
        calls = []
        def fail(publish):
            calls.append(1)
            return {'errors': ['offline']}
        jobs = RefreshJobs(self.store)
        results = list(jobs.events('macro:QA', fail, 0, self.good))
        self.assertEqual(results[-1]['price'], 100)
        self.assertTrue(results[-1]['stale'])
        list(jobs.events('macro:QA', fail, 0, self.good))
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.store.get_cache('market:v1:macro:QA')[0]['price'], 100)

    def test_partial_financial_failure_does_not_back_off_healthy_quotes(self):
        jobs = RefreshJobs(self.store)
        calls = []
        def quote(publish):
            calls.append(1)
            return {'price': 100, 'errors': ['forecast unavailable']}
        list(jobs.events('security:QA', quote, 0, self.good, persist=False))
        list(jobs.events('security:QA', quote, 0, self.good, persist=False))
        self.assertEqual(len(calls), 2)
        self.assertEqual(jobs.entries['security:QA']['retry'], 0)

    def test_batch_quote_read_prewarms_memory_and_returns_copies(self):
        self.store.set_cache('quote:QA', {'metrics': {'price': {'value': 100}}})
        recreated = Store(sqlite_path=self.path)
        recreated.get_cached_quotes(['QA'])
        def no_database():
            raise AssertionError('Hot quote should not query database again')
        recreated.transaction = no_database
        first = recreated.get_cache('quote:QA')
        first[0]['metrics']['price']['value'] = 0
        self.assertEqual(recreated.get_cache('quote:QA')[0]['metrics']['price']['value'], 100)

if __name__ == '__main__':
    unittest.main()
