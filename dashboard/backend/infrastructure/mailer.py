"""Gmail HTTPS mail transport; OAuth credentials remain on the server."""
import base64
from email.message import EmailMessage
from email.utils import formatdate
import hashlib
import json
import os
import re
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_send_lock = threading.Lock()
_last_send = 0.0
EMAIL = re.compile(r'^[A-Za-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}$')


class DeliveryUncertain(RuntimeError):
    """The channel may have accepted a message; automatic retry can duplicate it."""


class Mailer:
    def __init__(self, config=None):
        config = os.environ if config is None else config
        self.provider = config.get('FINFEED_EMAIL_PROVIDER', 'gmail').lower()
        self.sender = config.get('FINFEED_EMAIL_FROM', '')
        self.client_id = config.get('GMAIL_CLIENT_ID', '')
        self.client_secret = config.get('GMAIL_CLIENT_SECRET', '')
        self.refresh_token = config.get('GMAIL_REFRESH_TOKEN', '')
        self._token = ''
        self._token_until = 0
        self._token_lock = threading.Lock()

    @property
    def ready(self):
        credentials = (self.client_id and self.client_secret and self.refresh_token
                       if self.provider == 'gmail' else '')
        return bool(credentials and EMAIL.fullmatch(self.sender) and len(self.sender) <= 254)

    def _access_token(self):
        with self._token_lock:
            if self._token and time.monotonic() < self._token_until:
                return self._token
            request = Request('https://oauth2.googleapis.com/token', data=urlencode({
                'client_id': self.client_id, 'client_secret': self.client_secret,
                'refresh_token': self.refresh_token, 'grant_type': 'refresh_token',
            }).encode(), headers={'Content-Type': 'application/x-www-form-urlencoded'})
            try:
                with urlopen(request, timeout=15) as response:
                    result = json.load(response)
                token = result['access_token']
                lifetime = float(result.get('expires_in', 3600))
                if not isinstance(token, str) or not token:
                    raise ValueError('missing token')
            except Exception:
                # Never include OAuth response bodies or credentials in logs.
                raise RuntimeError('Gmail 发信授权更新失败，请检查服务器授权配置') from None
            self._token = token
            self._token_until = time.monotonic() + max(0, lifetime - 60)
            return token

    def send(self, recipient, subject, body, key, before_send=None):
        if not self.ready:
            raise RuntimeError('邮件服务尚未配置')
        if not EMAIL.fullmatch(recipient) or len(recipient) > 254:
            raise ValueError('收件邮箱无效')
        token = self._access_token()  # Safe to retry if this fails before sending.
        message = EmailMessage()
        message['From'] = self.sender
        message['To'] = recipient
        message['Subject'] = subject[:180]
        message['Date'] = formatdate(localtime=False)
        # Traceability only: Gmail does not promise Message-ID deduplication.
        message['Message-ID'] = '<' + hashlib.sha256(key.encode()).hexdigest() + '@finfeed.local>'
        message.set_content(body[:50000])
        payload = json.dumps({'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()}).encode()
        request = Request('https://gmail.googleapis.com/gmail/v1/users/me/messages/send',
                          data=payload, headers={'Authorization': 'Bearer ' + token,
                          'Content-Type': 'application/json'}, method='POST')
        global _last_send
        with _send_lock:
            time.sleep(max(0, .55 - (time.monotonic() - _last_send)))
            if before_send is not None:
                before_send()  # Durable reservation before an irreversible network send.
            _last_send = time.monotonic()
            try:
                with urlopen(request, timeout=15) as response:
                    result = json.load(response)
                if not result.get('id'):
                    raise ValueError('missing message id')
            except HTTPError as exc:
                if exc.code >= 500 or exc.code == 408:
                    raise DeliveryUncertain('Gmail 接收状态未知，已暂停自动重发') from None
                if exc.code == 401:
                    self._token_until = 0
                raise RuntimeError('Gmail 拒绝发送（HTTP %s）' % exc.code) from None
            except Exception:
                raise DeliveryUncertain('Gmail 接收状态未知，已暂停自动重发') from None
        return result['id']
