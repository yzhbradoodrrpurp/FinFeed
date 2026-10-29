"""Run only the FinFeed backend using its private project environment."""
import json
import os
from pathlib import Path
import sys

root = Path(os.environ.get('FINFEED_H20_ROOT', '/mnt/data/users/shx/FinFeed')).resolve()
for key in list(os.environ):
    if key.lower() in {'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy'}:
        os.environ.pop(key)
os.environ.update(json.loads((root / '.private/backend.json').read_text()))
os.environ['YAHOO_PROXY_URL'] = 'http://127.0.0.1:17890'
os.environ['FINFEED_H20_ROOT'] = str(root)
os.environ['FINFEED_TUNNEL_WATCHDOG'] = '1'
os.environ['FINFEED_MARKET_REFRESH'] = '1'
os.environ['PYTHONPATH'] = str(root / 'app/dashboard')
os.chdir(root / 'app/dashboard')
os.execv(sys.executable, [sys.executable, str(root / 'app/dashboard/deployment/worker.py'),
                        'backend.app:create_app()', '--bind', '127.0.0.1:18765',
                        '--workers', '1', '--threads', '64', '--timeout', '180',
                        '--access-logfile', '-', '--error-logfile', '-'])
