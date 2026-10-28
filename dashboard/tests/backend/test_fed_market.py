import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from backend.providers import fed_market as f

OCT = {'start':'2026-10-27','end':'2026-10-28','statement_published':False}
DEC = {'start':'2026-12-08','end':'2026-12-09','statement_published':False}
JAN = {'start':'2027-01-26','end':'2027-01-27','statement_published':False}

def event(month, dates, year):
    return {'slug':f'fed-decision-{month}-{year}', 'title':f'Fed Decision in {month}?',
            'active':True, 'closed':False, 'markets':[{'description':f'Meeting {month} {dates}, {year} {f.CALENDAR}'}]}

class FedMarketCases(unittest.TestCase):
    def setUp(self):
        f._cache.clear()
        self.events = [event('October','27-28',2026), event('December','8-9',2026), event('January','26-27',2027)]

    def choose(self, date, meetings=None):
        def get(url, **kwargs):
            if url == f.CALENDAR:
                return 'html'
            if 'public-search' in url:
                return {'events':self.events,'pagination':{'hasMore':False}}
            return next(e for e in self.events if url.endswith(e['slug']))
        with patch.object(f, 'parse_calendar', return_value=meetings or [OCT,DEC,JAN]):
            return f.select_event(get, now=datetime.fromisoformat(date).replace(tzinfo=timezone.utc))

    def test_does_not_roll_at_midnight_or_before_statement(self):
        for stamp in ['2026-10-28T04:01:00','2026-10-28T17:59:00','2026-10-28T18:01:00']:
            self.assertEqual(self.choose(stamp)[1]['end'], OCT['end'])

    def test_published_statement_rolls_to_december_not_november(self):
        self.assertEqual(self.choose('2026-10-28T18:01:00',[{**OCT,'statement_published':True},DEC,JAN])[1],DEC)

    def test_cross_year_and_dst(self):
        self.assertEqual(self.choose('2026-12-09T18:59:00',[{**DEC,'statement_published':True},JAN])[1]['end'], DEC['end'])
        self.assertEqual(self.choose('2026-12-10T05:01:00',[DEC,JAN])[1], JAN)

    def test_missing_or_ambiguous_contract_fails_closed(self):
        self.events.pop(1)
        with self.assertRaises(ValueError): self.choose('2026-10-29T12:00:00')
        f._cache.clear(); self.events += [event('December','8-9',2026)]*2
        with self.assertRaises(ValueError): self.choose('2026-10-29T12:00:00')

    def test_wrong_year_or_date_rejected(self):
        self.assertFalse(f.matches(event('December','8-9',2025),DEC))
        self.assertFalse(f.matches(event('December','9-10',2026),DEC))

    def test_official_calendar_parser(self):
        html='''<div class="panel"><div class="panel-heading">2026 FOMC Meetings</div>
        <div class="fomc-meeting"><div class="fomc-meeting__month">December</div>
        <div class="fomc-meeting__date">8-9*</div>
        <a href="/newsevents/pressreleases/monetary20261209a.htm">HTML</a></div></div>'''
        self.assertEqual(f.parse_calendar(html),[{**DEC,'statement_published':True}])
        with self.assertRaises(ValueError): f.parse_calendar('maintenance')

    def test_stale_calendar_fallback_keeps_original_timestamp(self):
        import time
        f._cache['schedule'] = ([DEC], time.time()-120)
        before=f._cache['schedule'][1]
        with patch.object(f.time,'time',return_value=before+121):
            self.assertEqual(f.cached('schedule',60,lambda: (_ for _ in ()).throw(ConnectionError()),None),[DEC])
        self.assertEqual(f._cache['schedule'][1],before)
