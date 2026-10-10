import unittest
from backend.services import securities as data


class QuarterMetricCases(unittest.TestCase):
    def snapshot(self):
        dates = ['2026-06-30', '2026-03-31', '2025-12-31', '2025-06-30']
        revenue = {p: data.field(100, p, 'TotalRevenue', 'source') for p in dates}
        profit = {p: data.field(v, p, 'GrossProfit', 'source') for p, v in zip(dates, [40, 30, -10, 20])}
        return {'quote_type': 'EQUITY', 'quarter_0': dates[0], 'metrics': {},
                'series': {'revenue': revenue, 'gross_margin': data.margin_series(profit, revenue, 'basis'),
                           'capex': {p: data.field(15, p, 'basis', 'source', currency='USD') for p in dates}}}

    def test_four_periods_share_anchor_and_keep_negative_margin(self):
        result = data.add_quarter_metrics(self.snapshot())
        for suffix, period, value in [('q0', '2026-06-30', .4), ('year_ago', '2025-06-30', .2),
                                      ('q1', '2026-03-31', .3), ('q2', '2025-12-31', -.1)]:
            self.assertEqual(result['metrics']['gross_margin_' + suffix]['period'], period)
            self.assertEqual(result['metrics']['gross_margin_' + suffix]['value'], value)
            self.assertEqual(result['metrics']['capex_' + suffix]['currency'], 'USD')

    def test_gap_does_not_skip_quarter_and_missing_category_stays_missing(self):
        result = self.snapshot()
        del result['series']['revenue']['2026-03-31']
        data.add_quarter_metrics(result)
        self.assertIsNone(result['metrics']['gross_margin_q1']['value'])
        self.assertIsNone(result['metrics']['gross_margin_q2']['value'])
        self.assertIsNone(result['metrics']['operating_margin_q0']['value'])

    def test_nonpositive_revenue_and_etf(self):
        numerator = {'2026-06-30': data.field(-10, '2026-06-30', 'profit', 'source')}
        revenue = {'2026-06-30': data.field(0, '2026-06-30', 'revenue', 'source')}
        self.assertIsNone(data.margin_series(numerator, revenue, 'basis')['2026-06-30']['value'])
        result = data.add_quarter_metrics({'metrics': {'revenue_q0': data.empty_metric('ETF 不适用')}, 'series': {}})
        self.assertEqual(result['metrics']['capex_q0']['reason'], 'ETF 不适用')

    def test_capex_growth_uses_matching_quarters_and_reuses_cached_series(self):
        snapshot = self.snapshot()
        for period, value in zip(snapshot['series']['capex'], [30, 20, 10, 15]):
            snapshot['series']['capex'][period]['value'] = value
        result = data.add_quarter_metrics(snapshot)['metrics']
        self.assertAlmostEqual(result['capex_yoy_q0']['value'], 1)
        self.assertAlmostEqual(result['capex_qoq_q0']['value'], .5)
        self.assertAlmostEqual(result['capex_qoq_q1']['value'], 1)
        self.assertEqual(result['capex_qoq_q1']['period'], '2026-03-31')
        self.assertEqual(result['capex_yoy_q0']['comparison_period'], '2025-06-30')
        snapshot['series']['capex']['2026-03-31']['value'] = 0
        self.assertIsNone(data.add_quarter_metrics(snapshot)['metrics']['capex_qoq_q0']['value'])
        del snapshot['series']['capex']['2026-03-31']
        self.assertIsNone(data.add_quarter_metrics(snapshot)['metrics']['capex_qoq_q0']['value'])
