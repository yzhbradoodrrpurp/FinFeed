"""Shared text transport for FRED and BEA; preserves timeouts and safe logging."""
import time
from urllib.request import Request, urlopen
from backend.infrastructure.failure_log import failure

def fetch(url):
    started = time.monotonic()
    try:
        with urlopen(Request(url, headers={'User-Agent': 'FinFeed/1.0 macro research'}), timeout=30) as response:
            return response.read().decode('utf-8')
    except Exception as exc:
        from urllib.parse import urlsplit
        target = urlsplit(url)
        failure(target.hostname, target.path, error=exc, started=started)
        raise
