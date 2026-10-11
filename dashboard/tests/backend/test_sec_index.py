import unittest
from unittest.mock import patch
from backend.providers import sec
from backend.services.news import snapshot
from backend.services.notifications import item_events, instant


def payload():
    return {'cik': '0000723125', 'filings': {'recent': {
        'form': ['10-K', '10-Q', '8-K'],
        'accessionNumber': ['0000723125-26-000023', '0000723125-26-000015', '0000723125-26-000024'],
        'filingDate': ['2026-10-09', '2026-06-25', '2026-10-11'],
        'acceptanceDateTime': ['2026-10-09T16:21:00Z', '2026-06-25T16:00:00Z', '2026-10-11T12:01:00Z'],
        'reportDate': ['2026-09-03', '2026-05-28', '2026-10-11'],
        'primaryDocument': ['mu-20260903.htm', 'mu-20260528.htm', 'event.htm']}, 'files': []}}


class SecIndexCases(unittest.TestCase):
    def test_primary_document_and_metadata(self):
        rows = sec.submission_items(payload(), 723125)
        report = next(r for r in rows if r['form'] == '10-K')
        self.assertEqual(report['url'], 'https://www.sec.gov/Archives/edgar/data/723125/000072312526000023/mu-20260903.htm')
        self.assertEqual(report['report_date'], '2026-09-03')
        self.assertEqual(report['accepted_at'], '2026-10-09T16:21:00Z')

    def test_sec_stylesheet_path_and_empty_primary_document(self):
        data=payload(); data['filings']['recent']['primaryDocument'][0]='xslF345X05/ownership.xml'
        rows=sec.submission_items(data,723125)
        self.assertTrue(any('/xslF345X05/ownership.xml' in r['url'] for r in rows))
        data['filings']['recent']['primaryDocument'][0]=''
        self.assertTrue(any('-index.html' in r['url'] for r in sec.submission_items(data,723125)))
        data['filings']['recent']['primaryDocument'][0]='../unsafe.htm'
        with self.assertRaises(ValueError): sec.submission_items(data,723125)

    def test_invalid_columns_fail_closed(self):
        data = payload(); data['filings']['recent']['primaryDocument'].pop()
        with self.assertRaises(ValueError): sec.submission_items(data, 723125)

    def test_official_snapshot_retains_full_index_for_detection(self):
        rows = sec.submission_items(payload(), 723125)
        with patch('backend.providers.sec.index', return_value=(rows, '', 723125)), patch('backend.services.news.yf.Ticker') as yahoo:
            data = snapshot('MU', 'sec')
        self.assertEqual(data['errors'], [])
        self.assertEqual(data['notification_items'], rows)
        yahoo.assert_not_called()

    def test_mapping_and_archive_page(self):
        import json
        data = payload(); data['filings']['recent'] = {k: v[:1] for k, v in data['filings']['recent'].items()}
        data['filings']['files'] = [{'name': 'CIK0000723125-submissions-001.json'}]
        archive = payload()['filings']['recent']
        with patch.object(sec, '_tickers', None), patch.object(sec, 'fetch', side_effect=[
                json.dumps({'0': {'ticker': 'MU', 'cik_str': 723125}}), json.dumps(data), json.dumps(archive)]) as fetch:
            rows, note, cik = sec.index('MU')
            self.assertEqual(cik, 723125); self.assertEqual(len(rows), 3); self.assertFalse(note)
            self.assertEqual(fetch.call_count, 3)

    def test_cutover_old_filing_new_filing_and_delayed_index(self):
        start = instant('2026-10-11T12:00:00Z')
        # The deployment migrates existing cursors before activating the new provider.
        source = 'news:sec:MU'
        cursor = {'ids': ['https://www.sec.gov/Archives/edgar/data/723125/000072312526000023/exhibit.htm'],
                  'baseline_at': start, 'observed_at': start, 'provider': 'sec_edgar'}
        rows = sec.submission_items(payload(), 723125)
        items = [{'id': r['url'], 'url': r['url'], 'title': r['title'], 'date': r['accepted_at']} for r in rows]
        current, events = item_events('news', source, items, cursor, 'MU', now=start+120)
        self.assertEqual(len(events), 1)
        self.assertIn('event.htm', events[0]['body']); self.assertNotIn('mu-20260903.htm', events[0]['body'])
        self.assertEqual(item_events('news', source, items, current, 'MU', now=start+86400)[1], [])
        empty, _ = item_events('news', source, [], cursor, 'MU', now=start+4*86400)
        delayed, events = item_events('news', source, items, empty, 'MU', now=start+5*86400)
        self.assertEqual(len(events), 1); self.assertEqual(delayed['baseline_at'], start)


if __name__ == '__main__': unittest.main()
