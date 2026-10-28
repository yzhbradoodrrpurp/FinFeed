"""Discover the next scheduled FOMC contract, verified against the Fed calendar."""
import calendar
import re
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

CALENDAR = 'https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm'
_cache = {}


def parse_calendar(html):
    meetings = []
    for panel in BeautifulSoup(html, 'html.parser').select('.panel'):
        heading = panel.select_one('.panel-heading')
        year = re.search(r'(\d{4}) FOMC Meetings', heading.get_text() if heading else '')
        if not year:
            continue
        for row in panel.select('.fomc-meeting'):
            month, days = row.select_one('.fomc-meeting__month'), row.select_one('.fomc-meeting__date')
            if not month or not days:
                continue
            name, dates = month.get_text(strip=True), days.get_text(strip=True).replace('*', '')
            if not re.fullmatch(r'\d{1,2}-\d{1,2}', dates):
                continue  # Exclude notation votes and unscheduled meetings.
            months = name.split('/')
            numbers = {n.lower(): i for i, n in enumerate(calendar.month_name) if n}
            numbers.update({n.lower(): i for i, n in enumerate(calendar.month_abbr) if n})
            first, last = [int(d) for d in dates.split('-')]
            start = datetime(int(year[1]), numbers[months[0].lower()], first).date().isoformat()
            end = datetime(int(year[1]), numbers[months[-1].lower()], last).date().isoformat()
            stamp = end.replace('-', '')
            statement = any(re.search(r'/pressreleases/monetary' + stamp + r'a\.htm$', a.get('href', '')) for a in row.select('a'))
            meetings.append({'start': start, 'end': end, 'statement_published': statement})
    if not meetings:
        raise ValueError('No official FOMC meetings parsed')
    return sorted(meetings, key=lambda m: m['end'])


def cached(key, ttl, fetch, store):
    entry = _cache.get(key)
    if entry is None and store:
        entry = store.get_cache(key)
    if entry and time.time() - entry[1] < ttl:
        return entry[0]
    try:
        value = fetch()
    except Exception:
        if entry and time.time() - entry[1] < 7 * 86400:
            return entry[0]  # Previously verified schedule; never invent a meeting.
        raise
    _cache[key] = (value, time.time())
    if store:
        store.set_cache(key, value)
    return value


def matches(event, meeting):
    """Do not infer the meeting year from an event slug or trading end date."""
    end = datetime.fromisoformat(meeting['end'])
    name = calendar.month_name[end.month]
    if event.get('title', '').lower() != f'fed decision in {name.lower()}?':
        return False
    rules = ' '.join(m.get('description', '') for m in event.get('markets', []))
    start_day = int(meeting['start'][-2:])
    return bool(re.search(rf'{name}\s+{start_day}\s*[-–]\s*{end.day},?\s+{end.year}\b', rules, re.I)
                and 'federalreserve.gov/monetarypolicy/fomccalendars.htm' in rules)


def select_event(get, store=None, now=None):
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo('America/New_York'))
    # A short calendar TTL detects newly published statements on decision day.
    meetings = cached('polymarket:fomc-calendar:v1', 60,
                      lambda: parse_calendar(get(CALENDAR, _text=True)), store)
    upcoming = [m for m in meetings if m['end'] >= local.date().isoformat()]
    if not upcoming:
        raise ValueError('Next official meeting not published')
    meeting = upcoming[0]
    decision_time = datetime.fromisoformat(meeting['end']).replace(hour=14, tzinfo=ZoneInfo('America/New_York'))
    if local >= decision_time and meeting['statement_published']:
        upcoming = upcoming[1:]
        if not upcoming:
            raise ValueError('Next official meeting not published')
        meeting = upcoming[0]

    def discover():
        events = []
        for page in range(1, 6):
            data = get('https://gamma-api.polymarket.com/public-search', q='Fed Decision in', limit_per_type=100, page=page)
            events.extend(data.get('events', []))
            if not data.get('pagination', {}).get('hasMore'):
                return events
        raise ValueError('Incomplete Fed market discovery')
    events = cached('polymarket:fed-discovery:v1', 60, discover, store)
    candidates = [e for e in events if matches(e, meeting)]
    if len(candidates) != 1:
        raise ValueError('Next meeting contract missing or ambiguous')
    event = get('https://gamma-api.polymarket.com/events/slug/' + candidates[0]['slug'])
    if not matches(event, meeting) or event.get('closed') or not event.get('active', False):
        raise ValueError('Next meeting contract not active')
    return event, meeting
