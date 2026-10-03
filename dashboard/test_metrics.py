"""Financial edge cases that would otherwise produce misleading dashboard values."""
import unittest
from datetime import datetime, timezone

from data import epoch

from metrics import prior_year_period, trailing_pe, volume_metrics, yoy


class FinancialCases(unittest.TestCase):
    def test_vendor_datetime_session_close_is_parsed(self):
        close = datetime(2026, 10, 2, 20, tzinfo=timezone.utc)
        self.assertEqual(epoch(close), close.timestamp())
        self.assertEqual(epoch("2026-10-02 16:00:00-04:00"), close.timestamp())

    def test_loss_to_profit_is_not_a_positive_base_growth_rate(self):
        value, reason = yoy(50, -25)
        self.assertIsNone(value)
        self.assertIn("负值", reason)
        self.assertIsNone(yoy(50, 0)[0])
        self.assertAlmostEqual(yoy(125, 100)[0], 0.25)

    def test_53_week_fiscal_calendar_matches_but_missing_year_does_not(self):
        self.assertEqual(prior_year_period("2026-06-27", ["2025-06-28", "2026-03-28"]), "2025-06-28")
        self.assertIsNone(prior_year_period("2026-06-27", ["2025-03-29", "2025-09-27"]))

    def test_volume_excludes_comparison_day_and_waits_for_close(self):
        rows = [(f"2026-09-{day:02}", 100) for day in range(1, 11)] + [("2026-09-11", 1000)]
        avg, ratio, reason, _ = volume_metrics(rows, "2026-09-11", True)
        self.assertEqual(avg, 100)
        self.assertEqual(ratio, 10)
        self.assertIsNone(reason)
        self.assertIsNone(volume_metrics(rows, "2026-09-11", False)[1])
        self.assertIsNone(volume_metrics(rows[2:], "2026-09-11", True)[0])

    def test_loss_making_equity_does_not_get_a_negative_pe(self):
        self.assertIsNone(trailing_pe(100, -2)[0])
        self.assertIsNone(trailing_pe(100, 0)[0])
        self.assertEqual(trailing_pe(100, 5)[0], 20)


if __name__ == "__main__":
    unittest.main()
