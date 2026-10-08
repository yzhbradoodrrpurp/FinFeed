"""Gmail HTTPS encoding, token lifecycle and ambiguous delivery protection."""
import base64
from email import policy
from email.parser import BytesParser
import io
import json
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from backend.infrastructure.mailer import Mailer, DeliveryUncertain


class MailerCases(unittest.TestCase):
    def setUp(self):
        self.mailer = Mailer({'FINFEED_EMAIL_PROVIDER': 'gmail', 'FINFEED_EMAIL_FROM': 'sender@gmail.com',
                             'GMAIL_CLIENT_ID': 'client', 'GMAIL_CLIENT_SECRET': 'secret',
                             'GMAIL_REFRESH_TOKEN': 'refresh'})
        self.sleep = patch('backend.infrastructure.mailer.time.sleep').start()
        self.addCleanup(patch.stopall)

    def response(self, payload):
        return io.BytesIO(json.dumps(payload).encode())

    def test_token_cached_and_mime_preserves_chinese(self):
        calls = []
        def request(req, **kwargs):
            calls.append(req)
            if req.full_url.endswith('/token'):
                return self.response({'access_token': 'access', 'expires_in': 3600})
            return self.response({'id': 'sent'})
        with patch('backend.infrastructure.mailer.urlopen', side_effect=request):
            callback = Mock()
            self.assertEqual(self.mailer.send('user@example.com', 'FinFeed · 非农', '北京时间\n内容', 'one', callback), 'sent')
            self.mailer.send('user@example.com', 'second', 'body', 'two')
        self.assertEqual(len(calls), 3)
        callback.assert_called_once_with()
        mime = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(json.loads(calls[1].data)['raw']))
        self.assertEqual(str(mime['Subject']), 'FinFeed · 非农')
        self.assertEqual(str(mime['From']), 'sender@gmail.com')
        self.assertIn('北京时间', mime.get_content())
        self.assertEqual(calls[1].get_header('Authorization'), 'Bearer access')

    def test_token_failure_does_not_reserve_or_send(self):
        callback = Mock()
        with patch('backend.infrastructure.mailer.urlopen', side_effect=TimeoutError('secret')) as fetch:
            with self.assertRaisesRegex(RuntimeError, '授权更新失败'):
                self.mailer.send('user@example.com', 'subject', 'body', 'one', callback)
        callback.assert_not_called()
        self.assertEqual(fetch.call_count, 1)

    def test_send_timeout_and_server_error_are_uncertain(self):
        self.mailer._token='access';self.mailer._token_until=float('inf')
        for error in [TimeoutError(), HTTPError('url', 503, 'unavailable', {}, None)]:
            with patch('backend.infrastructure.mailer.urlopen', side_effect=error):
                with self.assertRaises(DeliveryUncertain):
                    self.mailer.send('user@example.com', 'subject', 'body', 'one')

    def test_explicit_rejection_is_retryable_and_expired_token_invalidated(self):
        self.mailer._token='access';self.mailer._token_until=float('inf')
        with patch('backend.infrastructure.mailer.urlopen', side_effect=HTTPError('url',401,'unauthorized',{},None)):
            with self.assertRaisesRegex(RuntimeError, '401'):
                self.mailer.send('user@example.com','subject','body','one')
        self.assertEqual(self.mailer._token_until, 0)

    def test_unknown_provider_and_missing_config_not_ready(self):
        self.assertFalse(Mailer({}).ready)
        self.assertFalse(Mailer({'FINFEED_EMAIL_PROVIDER':'unknown','RESEND_API_KEY':'key','FINFEED_EMAIL_FROM':'a@b.com'}).ready)
