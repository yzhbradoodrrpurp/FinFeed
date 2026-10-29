"""BEA official release calendar transport and parsing."""
import json
from datetime import datetime
from backend.providers.http import fetch

def schedule(now):
    data = json.loads(fetch('https://apps.bea.gov/API/signup/release_dates.json'))
    dates = [datetime.fromisoformat(s) for s in data['Personal Income and Outlays']['release_dates']]
    source = 'https://www.bea.gov/news/schedule/full'
    previous = sorted(set(d for d in dates if d <= now))
    future = [d for d in dates if d > now]
    return {'previous_release': previous[-2].isoformat() if len(previous) >= 2 else None,
            'last_release': max(previous).isoformat() if previous else None,
            'next_release': min(future).isoformat() if future else None, 'calendar_source': source}
