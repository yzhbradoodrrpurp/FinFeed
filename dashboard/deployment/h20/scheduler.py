"""Optional project-local reminder trigger, enabled only after cutover."""
import json
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path('/mnt/data/users/shx/FinFeed')
opener = build_opener(ProxyHandler({}))
while True:
    started = time.monotonic()
    try:
        config = json.loads((ROOT / '.private/backend.json').read_text())
        token = config.get('FINFEED_NOTIFICATION_CRON_TOKEN', '')
        if len(token) < 32:
            raise ValueError('scheduler token unavailable')
        req = Request('http://127.0.0.1:18765/api/notifications/tick', data=b'{}', method='POST',
                      headers={'Host': urlsplit(config['PUBLIC_ORIGIN']).netloc,
                               'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        with opener.open(req, timeout=50) as response:
            response.read(65536)
            print('Reminder check accepted', flush=True)
    except Exception as error:
        # Never log credentials, endpoint query strings, or response bodies.
        print('Reminder check failed: ' + type(error).__name__, flush=True)
    time.sleep(max(1, 60 - (time.monotonic() - started)))
