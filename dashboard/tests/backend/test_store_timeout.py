"""Ensure pooled operations bound SQL/lock waits before reading private data."""
from contextlib import contextmanager
import unittest
from unittest.mock import Mock
from backend.storage.store import Store

class StoreTimeoutCases(unittest.TestCase):
    def test_pooled_transaction_sets_local_timeouts_before_business_queries(self):
        store = Store.__new__(Store)
        store.sqlite_path = None
        connection = Mock()
        @contextmanager
        def checkout():
            yield connection
        store.pool = Mock()
        store.pool.connection.side_effect = checkout
        with store.transaction() as active:
            self.assertIs(active, connection)
            active.execute('SELECT private_record')
        self.assertEqual(connection.execute.call_args_list[0].args[0],
            "SET LOCAL statement_timeout = '8s'; SET LOCAL lock_timeout = '3s'; "
            "SET LOCAL idle_in_transaction_session_timeout = '15s'; SET LOCAL search_path TO finfeed_private")
        store.cache_pool = Mock()
        store.cache_pool.connection.side_effect = checkout
        with store.transaction(cache=True):
            pass
        self.assertEqual(store.pool.connection.call_count, 1)
        self.assertEqual(store.cache_pool.connection.call_count, 1)

if __name__ == '__main__':
    unittest.main()
