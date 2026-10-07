import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
from news import normalize, snapshot


def response(module, field, rows):
    return SimpleNamespace(status_code=200, raise_for_status=lambda: None,
        json=lambda: {'quoteSummary': {'result': [{module: {field: rows}}]}})


class NewsCases(unittest.TestCase):
    def test_normalize_filters_ad_unsafe_url_and_duplicates(self):
        row = {'title': 'Call', 'date': 1791318600, 'url': 'https://example.com/call'}
        result = normalize([row, row, {'ad': True, **row},
            {'title': 'Unsafe', 'url': 'javascript:alert(1)'}], 'calls')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['published_at'], '2026-10-06T20:30:00+00:00')

    def test_sec_date_and_edgar_link(self):
        result = normalize([{'type': '8-K', 'title': 'Current report',
            'date': date(2026, 10, 6), 'edgarUrl': 'https://www.sec.gov/Archives/test'}], 'sec')
        self.assertEqual(result[0]['published_at'], '2026-10-06')
        self.assertTrue(result[0]['url'].startswith('https://www.sec.gov/'))

    def test_yahoo_mirror_is_linked_to_sec_original(self):
        result = normalize([{'type': '10-Q', 'date': '2026-10-06',
            'edgarUrl': 'https://finance.yahoo.com/sec-filing/AAPL/example',
            'exhibits': {'10-Q': 'https://cdn.yahoofinance.com/prod/sec-filings/0000320193/000032019326000100/report.htm'}}], 'sec')
        self.assertEqual(result[0]['url'], 'https://www.sec.gov/Archives/edgar/data/320193/000032019326000100/report.htm')

    def test_raw_sec_exhibits_list_links_original(self):
        result = normalize([{'type': '8-K', 'date': '2026-10-06',
            'edgarUrl': 'https://finance.yahoo.com/sec-filing/AAPL/example',
            'exhibits': [{'type': '8-K', 'url': 'https://www.sec.gov/Archives/report.htm'}]}], 'sec')
        self.assertEqual(result[0]['url'], 'https://www.sec.gov/Archives/report.htm')

    def test_calls_snapshot_and_no_coverage(self):
        with patch('news.yahoo_session.initialize'), patch('news.yf.Ticker') as ticker:
            ticker.return_value._data.get.return_value = response('earningsCallTranscripts', 'transcripts',
                [{'title': 'Call', 'date': 1791318600, 'url': 'https://finance.yahoo.com/call'}])
            self.assertEqual(len(snapshot('PENG', 'calls')['items']), 1)
            ticker.return_value._data.get.return_value.status_code = 404
            empty = snapshot('VOO', 'calls')
            self.assertEqual(empty['errors'], [])
            self.assertIn('未提供', empty['note'])

    def test_bounded_retry_recovers_both_sources(self):
        for kind, module, field, row in [
            ('calls', 'earningsCallTranscripts', 'transcripts', {'title': 'Call', 'url': 'https://example.com/call'}),
            ('sec', 'secFilings', 'filings', {'type': '8-K', 'edgarUrl': 'https://www.sec.gov/Archives/test'})]:
            with self.subTest(kind=kind), patch('news.yahoo_session.initialize'), patch('news.yf.Ticker') as ticker:
                get = ticker.return_value._data.get
                get.side_effect = [TimeoutError('timeout'), response(module, field, [row])]
                value = snapshot('AAPL', kind)
                self.assertEqual(value['errors'], [])
                self.assertEqual(len(value['items']), 1)
                self.assertEqual(get.call_count, 2)
                self.assertIn('query2.', get.call_args_list[0].args[0])
                self.assertIn('query1.', get.call_args_list[1].args[0])
                self.assertTrue(all(call.kwargs['timeout'] == 6 for call in get.call_args_list))

    def test_http_and_schema_errors_are_not_empty_success(self):
        failed_http = SimpleNamespace(status_code=503,
            raise_for_status=lambda: (_ for _ in ()).throw(RuntimeError('HTTP 503')))
        for result in [failed_http, response('secFilings', 'wrongField', []),
                       response('secFilings', 'filings', None)]:
            with self.subTest(result=result), patch('news.yahoo_session.initialize'), patch('news.yf.Ticker') as ticker:
                get = ticker.return_value._data.get
                get.return_value = result
                self.assertTrue(snapshot('AAPL', 'sec')['errors'])
                self.assertEqual(get.call_count, 2)

    def test_valid_empty_index_is_success(self):
        with patch('news.yahoo_session.initialize'), patch('news.yf.Ticker') as ticker:
            ticker.return_value._data.get.return_value = response('secFilings', 'filings', [])
            value = snapshot('VOO', 'sec')
            self.assertEqual(value['items'], [])
            self.assertEqual(value['errors'], [])

    def test_press_is_unsupported(self):
        with self.assertRaises(ValueError):
            snapshot('AAPL', 'press')

if __name__ == '__main__':
    unittest.main()
