"""Resend HTTPS transport. Credentials stay server-side; no SMTP socket dependency."""
import json
import os
import re
import threading
import time
from urllib.request import Request, urlopen

_send_lock = threading.Lock()
_last_send = 0.0

EMAIL = re.compile(r'^[A-Za-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}$')

class Mailer:
    def __init__(self, config=None):
        config = config or os.environ
        self.key = config.get('RESEND_API_KEY','')
        self.sender = config.get('FINFEED_EMAIL_FROM','')
    @property
    def ready(self):
        return bool(self.key and EMAIL.fullmatch(self.sender) and len(self.sender)<=254)
    def send(self, recipient, subject, body, key):
        if not self.ready:
            raise RuntimeError('邮件服务尚未配置')
        payload = json.dumps({'from':self.sender,'to':[recipient],'subject':subject[:180],
                              'text':body[:50000]},ensure_ascii=False).encode()
        request = Request('https://api.resend.com/emails',data=payload,method='POST',headers={
            'Authorization':'Bearer '+self.key,'Content-Type':'application/json','Idempotency-Key':key})
        global _last_send
        with _send_lock:
            time.sleep(max(0, .55-(time.monotonic()-_last_send)))
            _last_send=time.monotonic()
            with urlopen(request,timeout=15) as response:
                result=json.load(response)
        if not result.get('id'):
            raise RuntimeError('邮件渠道未确认接收')
        return result['id']
