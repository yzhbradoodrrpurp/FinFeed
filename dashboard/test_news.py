import unittest
from unittest.mock import patch
from news import normalize, snapshot, press_from_search

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

    def test_press_search_filters_publisher_and_exact_ticker(self):
        from types import SimpleNamespace
        def row(publisher, related):
            return {'publisher':publisher, 'relatedTickers':related, 'type':'STORY',
                'title':'Results', 'link':'https://finance.yahoo.com/release', 'providerPublishTime':1791318600}
        rows = [row('Business Wire',['PENG']), row('PR Newswire',['PENG']), row('GlobeNewswire',['PENG']),
            row('Reuters',['PENG']), row('Business Wire',['OTHER']), row('Business Wire',[]), row('Business Wire News',['PENG'])]
        response = SimpleNamespace(raise_for_status=lambda:None, json=lambda:{'news':rows})
        with patch('news.yf.Ticker') as ticker:
            ticker.return_value._data.get.return_value = response
            result = press_from_search(ticker.return_value,'PENG')
            self.assertEqual(len(result), 3)
            ticker.return_value._data.post.side_effect = RuntimeError('native feed unavailable')
            value = snapshot('PENG','press')
            self.assertEqual(value['errors'], [])
            self.assertEqual(value['items'][0]['classification'], 'newswire')

    def test_calls_use_event_time_and_link(self):
        result = normalize([{'title':'PENG Q4 FY2026 earnings call transcript', 'date':1791318600,
            'url':'https://finance.yahoo.com/quote/PENG/earnings/test.html'}], 'calls')
        self.assertEqual(result[0]['published_at'], '2026-10-06T20:30:00+00:00')
        self.assertEqual(result[0]['kind'], 'calls')

    def test_calls_snapshot_and_no_coverage(self):
        from types import SimpleNamespace
        response = SimpleNamespace(status_code=200, raise_for_status=lambda:None,
            json=lambda:{'quoteSummary':{'result':[{'earningsCallTranscripts':{'transcripts':[
                {'title':'Call', 'date':1791318600, 'url':'https://finance.yahoo.com/call'}]}}]}})
        with patch('news.yf.Ticker') as ticker:
            ticker.return_value._data.get.return_value = response
            self.assertEqual(len(snapshot('PENG','calls')['items']), 1)
            response.status_code = 404
            empty = snapshot('VOO','calls')
            self.assertEqual(empty['errors'], [])
            self.assertIn('未提供', empty['note'])

    def test_failure_is_not_empty_success(self):
        with patch('news.yf.Ticker',side_effect=RuntimeError('provider down')):
            self.assertTrue(snapshot('AAPL','press')['errors'])

if __name__=='__main__':unittest.main()
