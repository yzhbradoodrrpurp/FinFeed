"""Verify optional credentials do not leak or trigger repeated login calls."""
import os
import unittest
from unittest.mock import patch

import yahoo_session
import data


class SessionCases(unittest.TestCase):
    def setUp(self):
        state = patch.object(yahoo_session, "_status", None)
        state.start(); self.addCleanup(state.stop)
        env = patch.dict(os.environ, {}, clear=True)
        env.start(); self.addCleanup(env.stop)

    def test_anonymous_does_not_call_auth(self):
        with patch.object(yahoo_session.yf, "Auth") as auth:
            self.assertEqual(yahoo_session.initialize()["mode"], "anonymous")
            auth.assert_not_called()

    def test_credentials_installed_once_and_never_returned(self):
        with patch.dict(os.environ, {"YAHOO_SESSION_MODE": "login", "YAHOO_COOKIE_T": "private-t", "YAHOO_COOKIE_Y": "private-y"}), patch.object(yahoo_session.yf, "Auth") as auth:
            auth.return_value.set_login_cookies.return_value = True
            result = yahoo_session.initialize()
            self.assertEqual(result, yahoo_session.initialize())
            auth.return_value.set_login_cookies.assert_called_once_with("private-t", "private-y")
            self.assertTrue(result["verified"])
            self.assertNotIn("private-", str(result))
            self.assertTrue(data.financial_due({"yahoo_session": {"mode": "anonymous"}, "fetched_at": "2026-10-04T02:00:00+00:00"}, "2026-10-04T02:01:00+00:00"))

    def test_incomplete_config_does_not_send_partial_credentials(self):
        with patch.dict(os.environ, {"YAHOO_SESSION_MODE": "login", "YAHOO_COOKIE_T": "private-t"}), patch.object(yahoo_session.yf, "Auth") as auth:
            self.assertIsNotNone(yahoo_session.initialize()["error"])
            auth.assert_not_called()

    def test_failure_redacts_provider_exception_and_does_not_retry(self):
        with patch.dict(os.environ, {"YAHOO_SESSION_MODE": "login", "YAHOO_COOKIE_T": "private-t", "YAHOO_COOKIE_Y": "private-y"}), patch.object(yahoo_session.yf, "Auth") as auth:
            auth.return_value.set_login_cookies.side_effect = RuntimeError("secret private-t private-y")
            result = yahoo_session.initialize()
            self.assertFalse(result["verified"])
            self.assertNotIn("private-", str(result))
            yahoo_session.initialize()
            self.assertEqual(auth.return_value.set_login_cookies.call_count, 1)

    def test_saved_credentials_do_not_override_anonymous_mode(self):
        with patch.dict(os.environ, {"YAHOO_COOKIE_T": "private-t", "YAHOO_COOKIE_Y": "private-y"}), patch.object(yahoo_session.yf, "Auth") as auth:
            self.assertEqual(yahoo_session.initialize()["mode"], "anonymous")
            auth.assert_not_called()
            self.assertTrue(data.financial_due({"yahoo_session": {"mode": "login"}, "financial_checked_at": "2026-10-04T02:00:00+00:00"}, "2026-10-04T02:01:00+00:00"))


if __name__ == "__main__":
    unittest.main()
