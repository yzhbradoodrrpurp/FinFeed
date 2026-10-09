"""BLS official release calendar transport and parsing."""
import re
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc

def schedule(now):
    try:
        return official_schedule(now)
    except Exception:
        # FRED publishes BLS-announced dates, not a guessed first-Friday rule.
        # Its API has dates only. Use the BLS regular 08:30 Eastern slot and
        # keep that time basis explicit in the payload rather than claiming
        # FRED supplied an exact timestamp.
        from backend.providers.fred import release_dates
        dates = [datetime.fromisoformat(day + 'T08:30:00').replace(tzinfo=ZoneInfo('America/New_York'))
                 for day in release_dates(50)]
        previous = [day for day in dates if day <= now]
        future = [day for day in dates if day > now]
        if not future:
            raise ValueError('非农发布日历没有已公布的未来日期')
        return {'last_release': max(previous).isoformat() if previous else None,
                'next_release': min(future).isoformat(),
                'calendar_source': 'https://fred.stlouisfed.org/release?rid=50',
                'official_calendar_source': 'https://www.bls.gov/schedule/news_release/empsit.htm',
                'calendar_time_basis': 'BLS 常规发布时间 08:30 美国东部；FRED 提供 BLS 公布的日期，未提供时刻'}


def official_schedule(now):
    from curl_cffi import requests
    options = {'proxy': os.environ['BLS_PROXY_URL']} if os.environ.get('BLS_PROXY_URL') else {}
    response = requests.get('https://www.bls.gov/schedule/news_release/bls.ics', impersonate='chrome', timeout=30, **options)
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
