import json
import os
import time
import unittest
from unittest.mock import patch
from failure_log import failure, safe_text


class FailureLogCases(unittest.TestCase):
    def test_sensitive_urls_and_credentials_never_enter_log(self):
        with patch.dict(os.environ, {'FRED_API_KEY':'private-test-key', 'YAHOO_COOKIE_T':'private-cookie'}):
            with self.assertLogs('finfeed.failures', level='WARNING') as logs:
                failure('fred', 'observations', symbol='DGS10',
                        error=TimeoutError('private-test-key private-cookie https://host/path?api_key=secret crumb=secret'),
                        started=time.monotonic())
        record = json.loads(logs.records[0].message)
        self.assertEqual(record['error_type'], 'TimeoutError')
        self.assertEqual(record['symbol'], 'DGS10')
        self.assertIsInstance(record['elapsed_ms'], int)
        for secret in ('private-test-key','private-cookie','api_key=secret','crumb=secret'):
            self.assertNotIn(secret, logs.records[0].message)

    def test_http_status_retained(self):
        from urllib.error import HTTPError
        with self.assertLogs('finfeed.failures', level='WARNING') as logs:
            failure('bea', 'calendar', error=HTTPError('https://host?key=secret', 429, 'Too many requests', {}, None))
        self.assertEqual(json.loads(logs.records[0].message)['http_status'], 429)

    def test_empty_response_logged_without_exception(self):
        with self.assertLogs('finfeed.failures', level='WARNING') as logs:
            failure('yahoo', 'quote', reason='price missing', fallback_available=True)
        self.assertTrue(json.loads(logs.records[0].message)['fallback_available'])
