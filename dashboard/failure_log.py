"""Structured, credential-safe failures visible in the backend stderr log."""
import json
import logging
import os
import re
import time
from urllib.parse import urlsplit
from datetime import datetime, timezone

LOGGER = logging.getLogger('finfeed.failures')
if not LOGGER.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(message)s'))
    LOGGER.addHandler(handler)
LOGGER.setLevel(logging.WARNING)
LOGGER.propagate = False


def safe_text(value):
    text = str(value)
    # URLs may include credentials in the authority, query, path or fragment.
    text = re.sub(r'https?://\S+', '[url redacted]', text)
    for name, secret in os.environ.items():
        if len(secret) >= 6 and any(word in name.upper() for word in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD', 'COOKIE', 'CRUMB', 'DATABASE_URL', 'PROXY', 'CONFIG_B64')):
            text = text.replace(secret, '[redacted]')
            if 'DATABASE_URL' in name.upper() or 'PROXY' in name.upper():
                try:
                    parsed = urlsplit(secret)
                    for part in (parsed.username, parsed.password):
                        if part:
                            text = text.replace(part, '[redacted]')
                except ValueError:
                    pass
    text = re.sub(r'(?i)\b(api_?key|token|password|secret|cookie|crumb|authorization)\b\s*[:=]\s*[^\s,;]+', r'\1=[redacted]', text)
    return text[:600]


def failure(source, operation, *, error=None, reason=None, symbol=None, started=None, **fields):
    """Log only bounded diagnostic fields, never payloads, cookies or user IDs."""
    response = getattr(error, 'response', None)
    status = getattr(response, 'status_code', None) or getattr(error, 'code', None)
    record = {'event': 'request_failure', 'timestamp': datetime.now(timezone.utc).isoformat(),
              'source': source, 'operation': operation, 'symbol': symbol,
              'error_type': type(error).__name__ if error else 'InvalidResponse',
              'http_status': status if isinstance(status, int) else None,
              'reason': safe_text(reason if reason is not None else error),
              'elapsed_ms': round((time.monotonic()-started)*1000) if started is not None else None}
    record.update({key: safe_text(value) if isinstance(value, str) else value for key, value in fields.items()})
    LOGGER.warning(json.dumps(record, ensure_ascii=False))
