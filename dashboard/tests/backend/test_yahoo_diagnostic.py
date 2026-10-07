import unittest
from types import SimpleNamespace
import pandas as pd
from backend.providers.yahoo.diagnostic import balance_with_diagnostics


class DiagnosticCases(unittest.TestCase):
    def test_raw_and_parsed_are_distinct_and_credentials_are_never_saved(self):
        payload = [{"quarterlyTotalDebt": [{"asOfDate": "2026-03-31", "reportedValue": {"raw": 90}}]}]
        financials = SimpleNamespace(_fetch_fundamentals_payload=lambda url: payload)
        original = financials._fetch_fundamentals_payload
        def balance(freq):
            financials._fetch_fundamentals_payload("https://example.com/?type=quarterlyTotalDebt&period1=1&period2=2&crumb=secret")
            return pd.DataFrame({pd.Timestamp("2026-03-31"): {"TotalDebt": 90}})
        item = SimpleNamespace(ticker="GOOG", _fundamentals=SimpleNamespace(financials=financials), get_balance_sheet=balance)
        output = {}
        balance_with_diagnostics(item, output)
        self.assertIs(financials._fetch_fundamentals_payload, original)
        self.assertEqual(output["parsed_debt"], output["batches"][0]["debt"])
        self.assertEqual(output["narrow_debt"], output["parsed_debt"])
        self.assertNotIn("secret", str(output))
        self.assertNotIn("crumb", str(output))
