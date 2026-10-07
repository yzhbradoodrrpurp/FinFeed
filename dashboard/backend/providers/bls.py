"""BLS official release calendar transport and parsing."""
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc

def schedule(now):
    from curl_cffi import requests
    response = requests.get('https://www.bls.gov/schedule/news_release/bls.ics', impersonate='chrome', timeout=30)
    response.raise_for_status()
    text = response.text
    text = re.sub(r'\r?\n[ \t]', '', text)
    dates = []
    for event in text.split('BEGIN:VEVENT')[1:]:
        if 'Employment Situation' not in event:
            continue
        match = re.search(r'DTSTART([^:]*):(\d{8}T\d{6}Z?)', event)
        if match:
            raw = match[2]
            dt = datetime.strptime(raw.rstrip('Z'), '%Y%m%dT%H%M%S')
            dates.append(dt.replace(tzinfo=UTC if raw.endswith('Z') else ZoneInfo('America/New_York')))
    source = 'https://www.bls.gov/schedule/news_release/empsit.htm'
    previous = [d for d in dates if d <= now]
    future = [d for d in dates if d > now]
    return {'last_release': max(previous).isoformat() if previous else None,
            'next_release': min(future).isoformat() if future else None, 'calendar_source': source}
