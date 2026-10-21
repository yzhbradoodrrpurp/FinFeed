import unittest
from datetime import datetime
from backend.providers.longbridge_financial import normalize
from backend.services import securities
from unittest.mock import patch


def fixtures():
    def value(field, rows):
        return {'field':field,'values':[{'period':label,'fp_end':int(datetime.fromisoformat(date+'T04:00:00+00:00').timestamp()),'value':v} for date,label,v in rows]}
    rows=[('2026-09-30','Q3 2026',200),('2026-06-30','Q2 2026',100),
          ('2026-03-31','Q1 2026',80),('2025-09-30','Q3 2025',50)]
    raw={'list':{'IS':{'indicators':[{'accounts':[
        value('OperatingRevenue',rows),value('NetDebt',[(a,b,-v) for a,b,v in rows]),
        value('OperatingIncome',rows[1:]),value('GrossMgn',[(a,b,40) for a,b,v in rows[1:]]),
        value('NetFreeCashFlow',[(a,b,999999) for a,b,v in rows])]}]}}}
    return {'financial':{'data':raw,'fetched_at':'2026-10-21T00:00:00+00:00'},
      'statement_IS':{'data':{'currency':'USD','list':[{'fp_end':'2026-06-30','report_txt':'Q2 2026',
        'fields':[{'field':'rev','value':'100'},{'field':'gp','value':'60'},{'field':'oper_inc','value':'30'}]}]},'fetched_at':'2026-10-21T00:00:01+00:00'},
      'statement_CF':{'data':{'currency':'USD','list':[{'fp_end':'2026-06-30','report_txt':'Q2 2026',
        'fields':[{'field':'cash_oper','value':'40'},{'field':'capex','value':'-10'}]}]},'fetched_at':'2026-10-21T00:00:02+00:00'}}


class LongbridgeFinancialCases(unittest.TestCase):
    def test_new_revenue_never_borrows_prior_quarter_margin_or_cashflow(self):
        value=normalize(fixtures())
        self.assertEqual(value['series']['revenue']['2026-09-30']['value'],200)
        for key in ('gross_margin','operating_margin','capex','fcf'):
            self.assertNotIn('2026-09-30',value['series'][key])
        self.assertEqual(value['series']['fcf']['2026-06-30']['value'],30)
        self.assertEqual(value['series']['fcf']['2026-06-30']['inputs'],{'operating_cash_flow':40,'capital_expenditure':10})
        self.assertAlmostEqual(value['series']['gross_margin']['2026-06-30']['value'],.6)
        self.assertAlmostEqual(value['series']['operating_margin']['2026-06-30']['value'],.3)

    def test_net_debt_preserves_sign_and_negative_base_comparisons(self):
        value=normalize(fixtures())
        debt=value['series']['debt']
        self.assertEqual(debt['2026-09-30']['value'],-200)
        self.assertIn('NetDebt',debt['2026-09-30']['basis'])
        growth=securities.growth(debt,'2026-09-30')
        self.assertEqual(growth['value'],-1)
        self.assertEqual(growth['inputs'],{'current':-200,'previous_quarter':-100})
        self.assertEqual(securities.growth(debt,'2026-09-30',yearly=True)['value'],-3)

    def test_empty_or_failed_source_remains_missing_and_stale_is_visible(self):
        blocks=fixtures();blocks['statement_CF']={'data':{},'failed':True}
        blocks['financial']['stale']=True
        value=normalize(blocks)
        self.assertFalse(value['series']['fcf'])
        self.assertTrue(value['series']['debt']['2026-09-30']['stale'])
        self.assertTrue(value['errors'])

    def test_old_total_debt_cache_is_not_relabelled_as_net_debt(self):
        from unittest.mock import MagicMock
        store=MagicMock()
        old={'schema_version':9,'metrics':{'price':{'value':10},'debt_q0':{'value':100}},
             'series':{'debt':{'2026-06-30':{'value':100}}},'fetched_at':securities.now()}
        store.get_cache.return_value=(old,securities.time.time())
        with patch.object(securities,'fetch_security',side_effect=RuntimeError('offline')),patch.object(securities,'failure'):
            result=securities.security('QA',store=store)
        self.assertNotIn('debt_q0',result['metrics'])
        self.assertEqual(result['series'],{})
        self.assertTrue(result['stale'])
