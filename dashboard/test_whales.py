import unittest
from unittest.mock import patch
import json
from whales import parse_submission, aggregate, snapshot, compare, previous_quarter


def submission(value=100, amendment=''):
    return f'''<XML><edgarSubmission><tableEntryTotal>2</tableEntryTotal><tableValueTotal>{value*2}</tableValueTotal><amendmentType>{amendment}</amendmentType></edgarSubmission></XML><XML><informationTable xmlns="urn:sec">{''.join(f'<infoTable><nameOfIssuer>APPLE</nameOfIssuer><titleOfClass>COM</titleOfClass><cusip>037833100</cusip><value>{value}</value><shrsOrPrnAmt><sshPrnamt>10</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt></infoTable>' for _ in range(2))}</informationTable></XML>'''


class WhaleCases(unittest.TestCase):
    def test_units_aggregation_and_option_separation(self):
        rows, _ = parse_submission(submission(), '2026-08-14')
        combined = aggregate(rows)
        self.assertEqual(combined[0]['shares'], 20)
        self.assertEqual(combined[0]['value'], 200)
        self.assertEqual(combined[0]['weight'], 100)
        old, _ = parse_submission(submission(), '2022-11-14')
        self.assertEqual(aggregate(old)[0]['value'], 200000)
        self.assertEqual(len(aggregate(rows + [{**rows[0], 'put_call': 'PUT'}])), 2)

    def test_reject_incomplete_information_table(self):
        with self.assertRaises(ValueError):
            parse_submission(submission().replace('<tableEntryTotal>2', '<tableEntryTotal>3'), '2026-08-14')
        with self.assertRaises(ValueError):
            parse_submission(submission().replace('<tableValueTotal>200', '<tableValueTotal>300'), '2026-08-14')

    def test_restatement_new_holdings_and_latest_report(self):
        recent = {'form':['13F-HR/A','13F-HR/A','13F-HR','13F-HR/A'],
                  'filingDate':['2026-08-16','2026-08-15','2026-08-14','2026-09-01'],
                  'reportDate':['2026-06-30']*3+['2026-03-31'],
                  'accessionNumber':['0000000001-26-000001','0000000001-26-000002','0000000099-26-000003','0000000001-26-000004']}
        with patch('whales.fetch', side_effect=[json.dumps({'filings':{'recent':recent}}),
            submission(), submission(200,'RESTATEMENT'), submission(50,'NEW HOLDINGS')]):
            data = snapshot('berkshire')
        self.assertEqual(data['report_date'], '2026-06-30')
        self.assertEqual(data['total_value'], 500)
        self.assertEqual(data['holdings'][0]['shares'], 40)
        self.assertEqual(len(data['sources']), 3)

    def test_quantity_changes_include_exits_and_keep_options_separate(self):
        def row(cusip, shares, value=100, option='', title='COM'):
            return {'name':cusip, 'class':title, 'cusip':cusip, 'shares':shares,
                    'value':value, 'weight':10, 'put_call':option, 'amount_type':'SH'}
        before = {'holdings':[row('A',10),row('B',20),row('C',5),row('D',10),row('E',10)]}
        current = {'holdings':[row('A',15,title='COMMON STOCK'),row('B',10),row('D',10),row('F',8),row('E',10,option='PUT')]}
        results = {(x['cusip'],x['put_call']):x for x in compare(current,before)}
        self.assertEqual(results[('A','')]['status'],'increase')
        self.assertEqual(results[('A','')]['shares_change_percent'],50)
        self.assertEqual(results[('B','')]['status'],'decrease')
        self.assertEqual(results[('C','')]['status'],'exit')
        self.assertEqual(results[('C','')]['shares_change_percent'],-100)
        self.assertEqual(results[('D','')]['status'],'unchanged')
        self.assertEqual(results[('F','')]['status'],'new')
        self.assertIsNone(results[('F','')]['shares_change_percent'])
        self.assertEqual(results[('E','PUT')]['status'],'new')
        self.assertEqual(results[('E','')]['status'],'exit')

    def test_previous_quarter_uses_adjacent_calendar_quarter(self):
        self.assertEqual(previous_quarter('2026-03-31'),'2025-12-31')
        self.assertEqual(previous_quarter('2026-06-30'),'2026-03-31')

    def test_partial_current_is_published_when_previous_fails(self):
        import time
        recent = {'form':['13F-HR','13F-HR'], 'filingDate':['2026-08-14','2026-05-15'],
                  'reportDate':['2026-06-30','2026-03-31'], 'accessionNumber':['x','y']}
        published = []
        def load(_cik,_available,period,_deadline):
            if period == '2026-03-31':
                time.sleep(.03)
                raise TimeoutError('previous failed')
            return {'report_date':period,'filed_at':'2026-08-14','holdings':[{'value':100}], 'total_value':100,'sources':[]}
        with patch('whales.fetch',return_value=json.dumps({'filings':{'recent':recent}})), patch('whales.quarter',side_effect=load):
            result = snapshot('berkshire',on_update=published.append)
        self.assertTrue(published[0]['partial'])
        self.assertTrue(result['holdings'])
        self.assertEqual(result['previous_status'],'failed')
        self.assertFalse(result['changes'])
        self.assertTrue(result['errors'])

    def test_failure_never_returns_empty_success(self):
        with patch('whales.fetch', side_effect=TimeoutError('deadline')):
            data = snapshot('pershing')
        self.assertTrue(data['errors'])
        self.assertFalse(data['holdings'])

if __name__ == '__main__':
    unittest.main()
