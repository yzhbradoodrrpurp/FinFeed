import unittest
from unittest.mock import MagicMock, patch
import time
import backend.services.securities as data
class YearlyGrowthCases(unittest.TestCase):
    def series(self, old=100):
        return {p:data.field(v,p,'TotalRevenue','source') for p,v in [('2026-06-30',150),('2026-03-31',120),('2025-06-30',old)]}

    def test_compares_year_ago_not_previous_available_quarter(self):
        m=data.growth(self.series(),'2026-06-30',yearly=True)
        self.assertEqual(m['value'],.5)
        self.assertEqual(m['comparison_period'],'2025-06-30')
        self.assertEqual(m['inputs']['previous_year_quarter'],100)
        self.assertIsNone(data.growth({'2026-06-30':self.series()['2026-06-30'],'2026-03-31':self.series()['2026-03-31']},'2026-06-30',yearly=True)['value'])

    def test_53_week_year_and_nonpositive_fcf_base(self):
        s={'2026-01-03':data.field(20,'2026-01-03','FCF','source'),'2024-12-28':data.field(10,'2024-12-28','FCF','source')}
        self.assertEqual(data.growth(s,'2026-01-03',yearly=True)['value'],1)
        for old in [0]:
            m=data.growth(self.series(old),'2026-06-30',yearly=True)
            self.assertIsNone(m['value'])
            self.assertIn('去年同财季',m['reason'])

    def test_negative_yearly_base_keeps_value_status_and_provenance(self):
        m=data.growth(self.series(-100),'2026-06-30',yearly=True)
        self.assertEqual(m['value'],2.5)
        self.assertEqual(m['change_status'],'转正')
        self.assertEqual(m['comparison_period'],'2025-06-30')

    def test_existing_daily_cache_gets_yoy_without_network(self):
        saved={'financial_provider':'longbridge','schema_version':data.SCHEMA_VERSION,'financial_checked_at':data.now(),'quarter_0':'2026-06-30','metrics':{},'series':{k:self.series() for k in ['revenue','debt','fcf']}}
        store=MagicMock();store.get_cache.return_value=(saved,time.time())
        with patch.object(data,'financial_due',return_value=False),patch.object(data,'fetch_security') as fetch:
            r=data.security('YOYTEST',store=store)
        fetch.assert_not_called()
        for k in ['revenue','debt','fcf']:
            self.assertAlmostEqual(r['metrics'][k+'_qoq_q0']['value'],.25)
            self.assertEqual(r['metrics'][k+'_yoy_q0']['value'],.5)

    def test_etf_preserves_not_applicable(self):
        r={'metrics':{'revenue_q0':data.empty_metric('ETF 不适用')},'series':{}}
        self.assertEqual(data.add_yearly_growth(r)['metrics']['revenue_yoy_q0']['reason'],'ETF 不适用')

if __name__=='__main__':unittest.main()
