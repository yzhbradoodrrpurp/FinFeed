import unittest
from unittest.mock import patch
from news import normalize, snapshot

class NewsCases(unittest.TestCase):
    def test_normalize_filters_ad_unsafe_url_and_duplicates(self):
        rows = [{'content': {'title':'Report', 'pubDate':'2026-10-06T20:00:00Z', 'canonicalUrl':{'url':'https://example.com/report'}, 'provider':{'displayName':'Company'}}}]
        rows += [rows[0], {'ad':True, **rows[0]}, {'content':{'title':'Unsafe','canonicalUrl':{'url':'javascript:alert(1)'}}}]
        result = normalize(rows, 'press')
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['published_at'],'2026-10-06T20:00:00Z')
        self.assertEqual(result[0]['source'],'Company')

    def test_sec_date_and_edgar_link(self):
        from datetime import date
        result = normalize([{'type':'8-K','title':'Current report','date':date(2026,10,6),'edgarUrl':'https://www.sec.gov/Archives/test'}], 'sec')
        self.assertEqual(result[0]['published_at'],'2026-10-06')
        self.assertTrue(result[0]['url'].startswith('https://www.sec.gov/'))

    def test_yahoo_mirror_is_linked_to_sec_original(self):
        result = normalize([{'type':'10-Q', 'date':'2026-10-06', 'edgarUrl':'https://finance.yahoo.com/sec-filing/AAPL/example',
            'exhibits':{'10-Q':'https://cdn.yahoofinance.com/prod/sec-filings/0000320193/000032019326000100/report.htm'}}], 'sec')
        self.assertEqual(result[0]['url'], 'https://www.sec.gov/Archives/edgar/data/320193/000032019326000100/report.htm')

    def test_http_error_cannot_be_cached_as_no_news(self):
        from types import SimpleNamespace
        response = SimpleNamespace(status_code=503, raise_for_status=lambda: (_ for _ in ()).throw(RuntimeError('HTTP 503')))
        with patch('news.yf.Ticker') as ticker:
            ticker.return_value._data.post.return_value = response
            self.assertTrue(snapshot('AAPL', 'press')['errors'])

    def test_failure_is_not_empty_success(self):
        with patch('news.yf.Ticker',side_effect=RuntimeError('provider down')):
            self.assertTrue(snapshot('AAPL','press')['errors'])

if __name__=='__main__':unittest.main()
