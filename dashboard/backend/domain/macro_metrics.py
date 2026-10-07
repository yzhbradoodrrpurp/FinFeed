"""Macro calculations and date windows, without network or storage dependencies."""
from datetime import datetime, timezone

UTC = timezone.utc

def growth(rows, lag):
    out = []
    for i in range(lag, len(rows)):
        old, new = rows[i-lag], rows[i]
        # Do not silently span missing months.
        months = (int(new['date'][:4])-int(old['date'][:4]))*12 + int(new['date'][5:7])-int(old['date'][5:7])
        if months == lag and old['value'] > 0:
            out.append({'date': new['date'], 'value': (new['value']/old['value']-1)*100})
    return out

def history_start():
    today = datetime.now(UTC).date()
    try:
        return today.replace(year=today.year-3).isoformat()
    except ValueError:
        return today.replace(year=today.year-3, day=28).isoformat()

def metric(label, rows, unit, source, full_history=False):
    return {'label': label, 'unit': unit, 'latest': rows[-1] if rows else None,
            'previous': rows[-2] if len(rows) > 1 else None,
            'history': rows if full_history else rows[-24:], 'source': source}
