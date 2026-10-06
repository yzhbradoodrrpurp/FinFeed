import unittest
from unittest.mock import patch
import json
from whales import parse_submission, aggregate, snapshot


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

    def test_failure_never_returns_empty_success(self):
        with patch('whales.fetch', side_effect=TimeoutError('deadline')):
            data = snapshot('pershing')
        self.assertTrue(data['errors'])
        self.assertFalse(data['holdings'])

if __name__ == '__main__':
    unittest.main()
