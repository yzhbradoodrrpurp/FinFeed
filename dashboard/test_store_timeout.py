"""Ensure pooled operations bound SQL/lock waits before reading private data."""
from contextlib import contextmanager
import unittest
from unittest.mock import Mock
from cloud_store import Store

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
        self.assertEqual([call.args[0] for call in connection.execute.call_args_list], [
            "SET LOCAL statement_timeout = '8s'",
            "SET LOCAL lock_timeout = '3s'",
            "SET LOCAL idle_in_transaction_session_timeout = '15s'",
            'SET LOCAL search_path TO finfeed_private',
            'SELECT private_record'])

if __name__ == '__main__':
    unittest.main()
