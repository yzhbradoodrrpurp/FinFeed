"""FRED series transport and response parsing."""
import os
import json
from urllib.parse import urlencode
from backend.providers.http import fetch


def release_dates(release_id):
    """Publisher release dates, including announced dates without observations."""
    key = os.environ.get('FRED_API_KEY', '')
    if not key:
        raise ValueError('FRED_API_KEY 未配置')
    query = urlencode({'api_key': key, 'file_type': 'json', 'release_id': release_id,
                       'sort_order': 'desc', 'limit': 36,
                       'include_release_dates_with_no_data': 'true'})
    data = json.loads(fetch('https://api.stlouisfed.org/fred/release/dates?' + query))
    return sorted({row['date'] for row in data['release_dates']
                   if int(row['release_id']) == release_id})

def observations(series, *, observation_start=None):
    key = os.environ.get('FRED_API_KEY', '')
    if not key:
        raise ValueError('FRED_API_KEY 未配置')
    query = {'api_key': key, 'file_type': 'json', 'series_id': series, 'sort_order': 'desc'}
    if series == 'DGS10':
        query['observation_start'] = observation_start
    else:
        query['limit'] = 36
    params = urlencode(query)
    data = json.loads(fetch('https://api.stlouisfed.org/fred/series/observations?' + params))
    if 'error_message' in data:
        raise ValueError(str(data['error_message']))
    return sorted([{'date': r['date'], 'value': float(r['value'])}
                   for r in data['observations'] if r['value'] != '.'], key=lambda r: r['date'])
