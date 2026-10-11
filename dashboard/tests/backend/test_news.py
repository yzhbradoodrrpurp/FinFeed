import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
from backend.services.news import normalize, snapshot, recent_items


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
        with patch('backend.services.news.yahoo_session.initialize'), patch('backend.services.news.yf.Ticker') as ticker:
            ticker.return_value._data.get.return_value = response('earningsCallTranscripts', 'transcripts',
                [{'title': 'PENG Q4 FY2026 Call', 'date': 1791318600, 'url': 'https://finance.yahoo.com/call'}])
            self.assertEqual(len(snapshot('PENG', 'calls')['items']), 1)
            ticker.return_value._data.get.return_value.status_code = 404
            empty = snapshot('VOO', 'calls')
            self.assertEqual(empty['errors'], [])
            self.assertIn('未提供', empty['note'])

    def test_bounded_retry_recovers_calls(self):
        with patch('backend.services.news.yahoo_session.initialize'), patch('backend.services.news.yf.Ticker') as ticker:
            get = ticker.return_value._data.get
            get.side_effect = [TimeoutError('timeout'), response('earningsCallTranscripts', 'transcripts',
                [{'title': 'AAPL Q4 FY2026 Call', 'date': 1791318600, 'url': 'https://example.com/call'}])]
            value = snapshot('AAPL', 'calls')
            self.assertEqual(value['errors'], [])
            self.assertEqual(len(value['items']), 1)
            self.assertEqual(get.call_count, 2)

    def test_official_sec_failure_is_not_empty_success(self):
        with patch('backend.providers.sec.index', side_effect=ValueError('Invalid schema')):
            self.assertTrue(snapshot('AAPL', 'sec')['errors'])

    def test_official_sec_has_no_yahoo_dependency(self):
        with patch('backend.providers.sec.index', return_value=([], '未覆盖', None)), patch('backend.services.news.yf.Ticker') as yahoo:
            value = snapshot('VOO', 'sec')
            self.assertEqual(value['items'], [])
            self.assertEqual(value['errors'], [])
            self.assertEqual(value['provider'], 'sec_edgar')
            yahoo.assert_not_called()

    def test_calls_keep_adjacent_fiscal_quarter_across_year_boundary(self):
        rows = [dict(title=f'Company Q{quarter} FY{year} earnings call transcript',
                     url=f'https://example.com/{year}/{quarter}', date=1791318600)
                for year, quarter in [(2027, 1), (2026, 4), (2026, 3)]]
        items = recent_items(normalize(rows, 'calls'), 'calls')
        self.assertEqual(len(items), 2)
        self.assertEqual({item['fiscal_period'] for item in items}, {2027 * 4, 2027 * 4 - 1})
        # Missing previous quarter must not silently include an older third quarter.
        self.assertEqual(len(recent_items(normalize([rows[0], rows[2]], 'calls'), 'calls')), 1)

    def test_sec_window_rolls_only_when_new_periodic_report_is_published(self):
        from datetime import datetime, timezone
        now = datetime(2026, 10, 7, tzinfo=timezone.utc)
        rows = [dict(title=title, published_at=day) for title, day in [
            ('10-K · Annual', '2026-02-01'), ('10-Q · Q1', '2026-05-01'),
            ('10-Q · Q2', '2026-08-01'), ('10-Q/A · Amendment', '2026-09-01'),
            ('8-K · Event', '2026-10-06'), ('10-Q · Future', '2026-11-01')]]
        result = recent_items(rows, 'sec', now)
        self.assertEqual([item['published_at'] for item in result],
            ['2026-05-01', '2026-08-01', '2026-09-01', '2026-10-06'])
        result = recent_items(rows, 'sec', datetime(2026, 11, 7, tzinfo=timezone.utc))
        self.assertEqual(result[0]['published_at'], '2026-08-01')
        self.assertEqual(result[-1]['published_at'], '2026-11-01')

    def test_press_is_unsupported(self):
        with self.assertRaises(ValueError):
            snapshot('AAPL', 'press')

if __name__ == '__main__':
    unittest.main()
